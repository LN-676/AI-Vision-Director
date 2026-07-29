from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from autocamtracker.api.app import ApiSettings, create_app
from autocamtracker.edge_control.agent import EdgeAgent
from autocamtracker.edge_control.api import EdgeControlSettings
from autocamtracker.edge_control.control_port import SimulatedControlPort
from autocamtracker.edge_control.models import CommandStatus, CommandType


class EdgeControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.client = TestClient(
            create_app(
                ApiSettings(
                    identity_db_path=root / "identity.sqlite3",
                    telemetry_dir=root / "telemetry",
                    edge_control=EdgeControlSettings(
                        database_path=root / "control.sqlite3",
                        device_token="test-device-token",
                        offline_after_seconds=5,
                        lease_seconds=10,
                    ),
                )
            )
        )
        self.headers = {"X-Device-Token": "test-device-token"}
        self.node = "edge-mac-01"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(
        self,
        command_type: str = "start_tracking",
        *,
        command_id: str | None = None,
        parameters: dict | None = None,
        expires_delta: int = 30,
    ):
        return self.client.post(
            f"/api/v3/edge/nodes/{self.node}/commands",
            json={
                "command_id": command_id or str(uuid4()),
                "actor_uid": "tablet-test",
                "command_type": command_type,
                "parameters": parameters or {},
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=expires_delta)
                ).isoformat(),
            },
        )

    def claim(self):
        return self.client.get(
            f"/api/v3/edge/nodes/{self.node}/commands/claim",
            headers=self.headers,
        )

    def test_valid_command_is_created_and_idempotent(self) -> None:
        command_id = str(uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        payload = {
            "command_id": command_id,
            "actor_uid": "tablet-test",
            "command_type": "start_tracking",
            "parameters": {},
            "expires_at": expires_at.isoformat(),
        }
        first = self.client.post(
            f"/api/v3/edge/nodes/{self.node}/commands", json=payload
        )
        second = self.client.post(
            f"/api/v3/edge/nodes/{self.node}/commands", json=payload
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["command_id"], second.json()["command_id"])
        self.assertEqual(self.claim().json()["command_id"], command_id)
        self.assertIsNone(self.claim().json())

    def test_unknown_command_and_extra_fields_are_rejected(self) -> None:
        unknown = self.command("motor_velocity")
        self.assertEqual(unknown.status_code, 422)
        response = self.client.post(
            f"/api/v3/edge/nodes/{self.node}/commands",
            json={
                "command_id": str(uuid4()),
                "actor_uid": "tablet-test",
                "command_type": "home",
                "parameters": {},
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=30)
                ).isoformat(),
                "yaw_velocity": 1.0,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_expired_command_cannot_be_claimed(self) -> None:
        response = self.command(expires_delta=-1)
        self.assertEqual(response.json()["status"], "expired")
        self.assertIsNone(self.claim().json())

    def test_lease_expiry_allows_reclaim(self) -> None:
        command_id = self.command().json()["command_id"]
        first = self.client.get(
            f"/api/v3/edge/nodes/{self.node}/commands/claim?lease_seconds=2",
            headers=self.headers,
        ).json()
        self.assertEqual(first["command_id"], command_id)
        self.assertIsNone(self.claim().json())
        repository = self.client.app.state.edge_control_repository
        with repository._connect() as connection:
            connection.execute(
                "UPDATE edge_commands SET lease_expires_at=? WHERE command_id=?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    command_id,
                ),
            )
            connection.commit()
        reclaimed = self.claim().json()
        self.assertEqual(reclaimed["command_id"], command_id)

    def test_emergency_stop_has_priority(self) -> None:
        normal = self.command().json()
        emergency = self.command("emergency_stop").json()
        claimed = self.claim().json()
        self.assertEqual(claimed["command_id"], emergency["command_id"])
        self.assertGreater(emergency["priority"], normal["priority"])

    def test_heartbeat_updates_online_state_and_requires_token(self) -> None:
        payload = {
            "app_version": "test",
            "online": True,
            "iphone_connected": False,
            "dockkit_ready": False,
            "tracking_running": True,
            "tracking_mode": "ai_tracking",
            "current_target": None,
            "available_targets": [],
            "fps": 29.5,
            "latency_ms": 40.0,
            "last_error": None,
            "simulated": False,
        }
        unauthorized = self.client.post(
            f"/api/v3/edge/nodes/{self.node}/heartbeat", json=payload
        )
        self.assertEqual(unauthorized.status_code, 401)
        heartbeat = self.client.post(
            f"/api/v3/edge/nodes/{self.node}/heartbeat",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.json()["online"])
        self.assertTrue(heartbeat.json()["tracking_running"])

    def test_control_state_websocket_streams_nodes(self) -> None:
        with self.client.websocket_connect("/ws/control-state") as socket:
            message = socket.receive_json()
        self.assertEqual(message["type"], "control_state")
        self.assertEqual(message["nodes"], [])

    def test_ack_lifecycle(self) -> None:
        command_id = self.command().json()["command_id"]
        self.claim()
        headers = {**self.headers, "X-Edge-Node-ID": self.node}
        executing = self.client.post(
            f"/api/v3/edge/commands/{command_id}/ack",
            json={"status": "executing", "result": None, "error_message": None},
            headers=headers,
        )
        self.assertEqual(executing.json()["status"], "executing")
        succeeded = self.client.post(
            f"/api/v3/edge/commands/{command_id}/ack",
            json={
                "status": "succeeded",
                "result": {"ok": True},
                "error_message": None,
            },
            headers=headers,
        )
        self.assertEqual(succeeded.json()["status"], "succeeded")


class FakeAgentClient:
    node_id = "edge-test"

    def __init__(self) -> None:
        self.acks: list[tuple[str, str, dict]] = []

    def ack(self, command_id, status, **fields):
        self.acks.append((command_id, status, fields))
        return {}


class EdgeAgentTests(unittest.TestCase):
    def command(self, command_type: str, parameters: dict | None = None, expires=30):
        from autocamtracker.edge_control.models import EdgeCommand

        now = datetime.now(timezone.utc)
        return EdgeCommand(
            command_id=uuid4(),
            node_id="edge-test",
            actor_uid="test",
            command_type=CommandType(command_type),
            parameters=parameters or {},
            priority=100,
            status=CommandStatus.CLAIMED,
            created_at=now,
            expires_at=now + timedelta(seconds=expires),
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=10),
        )

    def test_agent_acks_executing_and_success_through_control_port(self) -> None:
        client = FakeAgentClient()
        control = SimulatedControlPort()
        agent = EdgeAgent(client, control)  # type: ignore[arg-type]
        agent.execute(self.command("start_tracking"))
        self.assertTrue(control.running)
        self.assertEqual([item[1] for item in client.acks], ["executing", "succeeded"])

    def test_agent_acks_failure_and_skips_expired_command(self) -> None:
        client = FakeAgentClient()
        class FailingControl(SimulatedControlPort):
            def select_target(self, target_gid: int) -> None:
                raise RuntimeError("Desktop selection unavailable")

        control = FailingControl()
        agent = EdgeAgent(client, control)  # type: ignore[arg-type]
        agent.execute(self.command("select_target", {"target_gid": 0}))
        self.assertEqual([item[1] for item in client.acks], ["executing", "failed"])
        client.acks.clear()
        agent.execute(self.command("start_tracking", expires=-1))
        self.assertEqual(client.acks, [])
        self.assertFalse(control.running)


if __name__ == "__main__":
    unittest.main()
