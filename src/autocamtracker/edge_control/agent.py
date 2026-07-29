"""Bounded-retry Edge Agent for heartbeat, claim, execute, and ack."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import random
from threading import Event, Thread
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from autocamtracker.edge_control.control_port import (
    ControlPort,
    SimulatedControlPort,
    UnavailableControlPort,
)
from autocamtracker.edge_control.models import CommandStatus, EdgeCommand


class ControlApiClient:
    def __init__(self, base_url: str, node_id: str, device_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.node_id = node_id
        self.device_token = device_token

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v3/edge/nodes/{quote(self.node_id)}/heartbeat",
            payload,
        )

    def claim(self) -> dict[str, Any] | None:
        return self._request(
            "GET", f"/api/v3/edge/nodes/{quote(self.node_id)}/commands/claim"
        )

    def ack(
        self,
        command_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v3/edge/commands/{quote(command_id)}/ack",
            {
                "status": status,
                "result": result,
                "error_message": error_message,
            },
            extra_headers={"X-Edge-Node-ID": self.node_id},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        body = (
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {
            "Accept": "application/json",
            "X-Device-Token": self.device_token,
            **(extra_headers or {}),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=2.0) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"control API returned {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise ConnectionError(f"control API unavailable: {error}") from error
        return json.loads(raw) if raw else None


class EdgeAgent:
    def __init__(
        self,
        client: ControlApiClient,
        control: ControlPort,
        *,
        heartbeat_interval: float = 1.5,
        idle_interval: float = 0.5,
        maximum_backoff: float = 15.0,
    ) -> None:
        self.client = client
        self.control = control
        self.heartbeat_interval = max(0.5, heartbeat_interval)
        self.idle_interval = max(0.1, idle_interval)
        self.maximum_backoff = max(1.0, maximum_backoff)
        self.stop_event = Event()
        self._thread: Thread | None = None
        self._last_heartbeat = 0.0
        self._failures = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = Thread(target=self.run, name="aivd-edge-agent", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                now = monotonic()
                if now - self._last_heartbeat >= self.heartbeat_interval:
                    self.client.heartbeat(self.control.telemetry().model_dump(mode="json"))
                    self._last_heartbeat = now
                claimed = self.client.claim()
                if claimed is not None:
                    self.execute(EdgeCommand.model_validate(claimed))
                self._failures = 0
                self.stop_event.wait(self.idle_interval)
            except (ConnectionError, RuntimeError, ValueError):
                self._failures = min(self._failures + 1, 16)
                delay = min(
                    self.maximum_backoff,
                    0.5 * (2 ** (self._failures - 1)),
                )
                delay *= random.uniform(0.85, 1.15)
                self.stop_event.wait(delay)

    def execute(self, command: EdgeCommand) -> None:
        if command.expires_at <= datetime.now(timezone.utc):
            return
        self.client.ack(str(command.command_id), CommandStatus.EXECUTING.value)
        try:
            parameters = command.parameters
            actions = {
                "start_tracking": lambda: self.control.start_tracking(),
                "stop_tracking": lambda: self.control.stop_tracking(),
                "home": lambda: self.control.home(),
                "emergency_stop": lambda: self.control.emergency_stop(),
                "set_tracking_mode": lambda: self.control.set_tracking_mode(
                    str(parameters["mode"])
                ),
                "select_target": lambda: self.control.select_target(
                    int(parameters["target_gid"])
                ),
                "find_target": lambda: self.control.find_target(
                    int(parameters["target_gid"])
                ),
            }
            actions[command.command_type.value]()
        except Exception as error:
            self.client.ack(
                str(command.command_id),
                CommandStatus.FAILED.value,
                error_message=str(error)[:2000],
            )
            return
        self.client.ack(
            str(command.command_id),
            CommandStatus.SUCCEEDED.value,
            result={"executed_by": self.client.node_id},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Vision Director Edge Agent")
    parser.add_argument("--demo", action="store_true", help="use clearly labeled simulated state")
    args = parser.parse_args()
    base_url = os.environ.get("AIVD_CONTROL_API_URL", "http://127.0.0.1:8080")
    node_id = os.environ.get("AIVD_EDGE_NODE_ID", "edge-mac-01")
    token = os.environ.get("AIVD_EDGE_DEVICE_TOKEN", "")
    if not token:
        raise SystemExit("AIVD_EDGE_DEVICE_TOKEN is required")
    control: ControlPort = SimulatedControlPort() if args.demo else UnavailableControlPort()
    agent = EdgeAgent(ControlApiClient(base_url, node_id, token), control)
    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop_event.set()


if __name__ == "__main__":
    main()
