from pathlib import Path
import unittest

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from autocamtracker.cloud.postgres_schema import metadata


class PostgresSchemaTests(unittest.TestCase):
    def test_formal_schema_contains_phase_two_tables(self) -> None:
        self.assertEqual(
            set(metadata.tables),
            {
                "organizations",
                "organization_members",
                "nodes",
                "organization_nodes",
                "vehicles",
                "vehicle_id_mappings",
                "sessions",
                "events",
                "vehicle_features",
                "gallery_rollback_events",
                "idempotency_keys",
                "audit_logs",
                "api_rate_limits",
                "registered_models",
                "model_versions",
                "benchmark_jobs",
                "notification_channels",
                "alert_rules",
                "cloud_event_outbox",
            },
        )

    def test_mapping_database_constraints_bind_all_three_identity_columns(self) -> None:
        ddl = str(
            CreateTable(metadata.tables["vehicle_id_mappings"]).compile(
                dialect=postgresql.dialect()
            )
        )

        self.assertIn(
            "FOREIGN KEY(node_id, local_id, cloud_id) "
            "REFERENCES vehicles (source_node_id, local_id, cloud_id)",
            " ".join(ddl.split()),
        )
        self.assertIn("UNIQUE (cloud_id)", ddl)

    def test_initial_alembic_revision_is_present(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "20260729_0001_phase2_schema.py"
        )

        self.assertTrue(migration.is_file())
        self.assertIn('revision = "20260729_0001"', migration.read_text(encoding="utf-8"))

    def test_phase_three_migration_contains_append_only_audit_trigger(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "20260729_0002_auth_write_api.py"
        ).read_text(encoding="utf-8")

        self.assertIn('down_revision = "20260729_0001"', migration)
        self.assertIn("trg_audit_logs_append_only", migration)
        self.assertIn("BEFORE UPDATE OR DELETE ON audit_logs", migration)

    def test_phase_six_migration_contains_advanced_control_plane(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "20260729_0003_phase6_advanced_cloud.py"
        ).read_text(encoding="utf-8")

        self.assertIn('down_revision = "20260729_0002"', migration)
        for table in (
            "organizations",
            "organization_members",
            "organization_nodes",
            "registered_models",
            "model_versions",
            "benchmark_jobs",
            "notification_channels",
            "alert_rules",
            "cloud_event_outbox",
        ):
            self.assertIn(f'"{table}"', migration)


if __name__ == "__main__":
    unittest.main()
