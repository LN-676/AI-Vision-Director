"""SQLite persistence for ReID gallery features."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from time import time

from autocamtracker.tracking.feature_models import (
    CropQuality,
    FeatureMatch,
    FeatureSnapshot,
    GalleryRollbackEvent,
    GalleryRollbackResult,
    GalleryType,
    StoredFeature,
)
from autocamtracker.tracking.sqlite_worker import SQLiteConnectionProxy, SQLiteWorker
from autocamtracker.vision.detector import TrackedDetection


class FeatureRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = SQLiteWorker(self.db_path, name="feature-database")
        self.connection = SQLiteConnectionProxy(self._database)
        self._ensure_schema()

    def close(self) -> None:
        self._database.close()

    def insert(self, vehicle_id: int, gallery_type: GalleryType, detection: TrackedDetection,
               quality: CropQuality, embedding: list[float], duplicate_score: float | None,
               crop_jpeg: bytes | None, model_path: str, provenance: dict[str, object]) -> int:
        required_provenance = {
            "write_id", "source", "global_vehicle_id", "local_track_id", "frame_index",
            "identity_state", "identity_reason_code", "identity_score", "identity_sub_scores",
            "decision_accepted", "motor_safe_to_track",
        }
        missing = sorted(required_provenance - set(provenance))
        if missing:
            raise ValueError(f"embedding provenance is missing fields: {missing}")
        if not str(provenance["write_id"]).strip() or not str(provenance["source"]).strip():
            raise ValueError("embedding provenance write_id and source are required")
        identity_score = float(provenance["identity_score"])
        if not isfinite(identity_score) or not isinstance(provenance["identity_sub_scores"], dict):
            raise ValueError("embedding provenance identity scores are invalid")
        if provenance["global_vehicle_id"] != vehicle_id:
            raise ValueError("embedding provenance GID does not match destination GID")
        if int(provenance["frame_index"]) != detection.frame_index:
            raise ValueError("embedding provenance frame does not match detection frame")
        if detection.track_id is not None and provenance["local_track_id"] != detection.track_id:
            raise ValueError("embedding provenance LID does not match detection LID")
        if (
            provenance["identity_state"] != "LOCKED"
            or identity_score < 0.84
            or not bool(provenance["decision_accepted"])
            or not bool(provenance["motor_safe_to_track"])
        ):
            raise ValueError("embedding provenance is not a high-confidence LOCKED identity")
        cursor = self._database.execute(
            """INSERT INTO vehicle_features (vehicle_id, gallery_type, created_at, frame_index,
            track_id, bbox_json, quality_score, duplicate_score, embedding_json, crop_jpeg,
            metadata_json, provenance_json, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (vehicle_id, gallery_type, time(), detection.frame_index, detection.track_id,
             json.dumps(list(detection.bbox)), quality.score, duplicate_score,
             json.dumps([float(value) for value in embedding]), crop_jpeg,
             json.dumps({"class_name": detection.class_name, "confidence": detection.confidence,
                         "reid_model_label": Path(model_path).name or model_path,
                         "reid_model_path": model_path, "quality_reason": quality.reason,
                         "crop_width": quality.width, "crop_height": quality.height,
                         "sharpness": quality.sharpness, "brightness": quality.brightness}, sort_keys=True),
             json.dumps(provenance, sort_keys=True)),
            commit=True,
        )
        return int(cursor.lastrowid)

    def stored_features(self, gallery_type: GalleryType, vehicle_id: int | None = None) -> list[StoredFeature]:
        rows = self._database.execute(
            """SELECT id, vehicle_id, gallery_type, embedding_json, quality_score, frame_index
            FROM vehicle_features WHERE gallery_type = ? AND embedding_json IS NOT NULL
            AND is_active = 1 AND (? IS NULL OR vehicle_id = ?)""",
            (gallery_type, vehicle_id, vehicle_id),
        ).fetchall()
        features = []
        for row in rows:
            try:
                embedding = [float(item) for item in json.loads(row["embedding_json"])]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            features.append(StoredFeature(FeatureMatch(int(row["id"]), int(row["vehicle_id"]),
                str(row["gallery_type"]), 0.0, float(row["quality_score"]), int(row["frame_index"])), embedding))  # type: ignore[arg-type]
        return features

    def has_master_features(self, vehicle_id: int) -> bool:
        row = self._database.execute("SELECT COUNT(*) AS count FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master' AND is_active=1", (vehicle_id,)).fetchone()
        return bool(row and int(row["count"]) > 0)

    def dominant_master_class(self, vehicle_id: int) -> str | None:
        row = self._database.execute("""SELECT json_extract(metadata_json, '$.class_name') AS class_name, COUNT(*) AS count
            FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master' AND is_active=1 AND class_name IS NOT NULL
            GROUP BY class_name ORDER BY count DESC, class_name ASC LIMIT 1""", (vehicle_id,)).fetchone()
        return str(row["class_name"]) if row and row["class_name"] else None

    def summary_by_vehicle(self) -> dict[int, dict[str, int]]:
        rows = self._database.execute("SELECT vehicle_id, gallery_type, COUNT(*) AS count FROM vehicle_features WHERE is_active=1 GROUP BY vehicle_id, gallery_type").fetchall()
        summary: dict[int, dict[str, int]] = {}
        for row in rows:
            summary.setdefault(int(row["vehicle_id"]), {})[str(row["gallery_type"])] = int(row["count"])
        return summary

    def model_labels_by_vehicle(self, gallery_type: GalleryType = "master") -> dict[int, str]:
        rows = self._database.execute("""SELECT vehicle_id, COALESCE(NULLIF(json_extract(metadata_json,
            '$.reid_model_label'), ''), NULLIF(json_extract(metadata_json, '$.reid_model_path'), ''), 'Unknown') AS label,
            COUNT(*) AS count, MAX(created_at) AS latest FROM vehicle_features WHERE gallery_type=? AND is_active=1
            GROUP BY vehicle_id, label ORDER BY vehicle_id, count DESC, latest DESC""", (gallery_type,)).fetchall()
        labels: dict[int, str] = {}
        for row in rows:
            labels.setdefault(int(row["vehicle_id"]), str(row["label"] or "Unknown"))
        return labels

    def delete_vehicle_features(self, vehicle_id: int) -> int:
        cursor = self._database.execute("DELETE FROM vehicle_features WHERE vehicle_id=?", (vehicle_id,), commit=True)
        return int(cursor.rowcount or 0)

    def delete_features(self, feature_ids: list[int], vehicle_id: int | None = None) -> int:
        ids = sorted({int(item) for item in feature_ids if int(item) > 0})
        if not ids:
            return 0
        clause = " AND vehicle_id=?" if vehicle_id is not None else ""
        parameters = ids + ([int(vehicle_id)] if vehicle_id is not None else [])
        cursor = self._database.execute(
            f"DELETE FROM vehicle_features WHERE id IN ({','.join('?' for _ in ids)}){clause}",
            parameters,
            commit=True,
        )
        return int(cursor.rowcount or 0)

    def snapshots(
        self,
        vehicle_id: int,
        gallery_type: GalleryType = "master",
        *,
        include_rolled_back: bool = False,
    ) -> list[FeatureSnapshot]:
        active_clause = "" if include_rolled_back else " AND is_active=1"
        rows = self._database.execute("""SELECT id, vehicle_id, gallery_type, created_at, frame_index,
            track_id, quality_score, duplicate_score, crop_jpeg, metadata_json, provenance_json,
            is_active, rolled_back_at, rollback_reason FROM vehicle_features
            WHERE vehicle_id=? AND gallery_type=?""" + active_clause +
            " ORDER BY created_at DESC, id DESC", (vehicle_id, gallery_type)).fetchall()
        result = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            try:
                provenance = json.loads(row["provenance_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                provenance = {}
            result.append(FeatureSnapshot(int(row["id"]), int(row["vehicle_id"]), str(row["gallery_type"]),
                float(row["created_at"]), int(row["frame_index"]), row["track_id"], float(row["quality_score"]),
                float(row["duplicate_score"]) if row["duplicate_score"] is not None else None,
                bytes(row["crop_jpeg"]) if row["crop_jpeg"] is not None else None,
                metadata if isinstance(metadata, dict) else {},
                provenance if isinstance(provenance, dict) else {}, bool(row["is_active"]),
                float(row["rolled_back_at"]) if row["rolled_back_at"] is not None else None,
                str(row["rollback_reason"]) if row["rollback_reason"] else None))  # type: ignore[arg-type]
        return result

    def first_crop_jpeg(self, vehicle_id: int) -> bytes | None:
        row = self._database.execute("""SELECT crop_jpeg FROM vehicle_features WHERE vehicle_id=? AND is_active=1 AND crop_jpeg IS NOT NULL
            ORDER BY CASE gallery_type WHEN 'master' THEN 0 WHEN 'candidate' THEN 1 ELSE 2 END, created_at, id LIMIT 1""", (vehicle_id,)).fetchone()
        return bytes(row["crop_jpeg"]) if row and row["crop_jpeg"] is not None else None

    def prune_master(self, vehicle_id: int, limit: int) -> int:
        rows = self._database.execute("SELECT id FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master' AND is_active=1 ORDER BY quality_score, created_at", (vehicle_id,)).fetchall()
        ids = [int(row["id"]) for row in rows[:max(0, len(rows) - limit)]]
        if not ids:
            return 0
        return self.rollback_features(ids, reason="master gallery limit", actor="gallery_policy").rolled_back_count

    def rollback_features(
        self,
        feature_ids: list[int],
        *,
        reason: str,
        actor: str,
        vehicle_id: int | None = None,
    ) -> GalleryRollbackResult:
        if not reason.strip() or not actor.strip():
            raise ValueError("rollback actor and reason are required")
        ids = sorted({int(item) for item in feature_ids if int(item) > 0})
        if not ids:
            return GalleryRollbackResult(None, (), 0, reason)

        def operation(connection):
            placeholders = ",".join("?" for _ in ids)
            vehicle_clause = " AND vehicle_id=?" if vehicle_id is not None else ""
            selection_parameters = [*ids] + ([int(vehicle_id)] if vehicle_id is not None else [])
            active_rows = connection.execute(
                f"SELECT id FROM vehicle_features WHERE is_active=1 "
                f"AND id IN ({placeholders}){vehicle_clause}",
                selection_parameters,
            ).fetchall()
            changed_ids = tuple(int(row["id"]) for row in active_rows)
            if not changed_ids:
                return GalleryRollbackResult(None, (), 0, reason)
            changed_placeholders = ",".join("?" for _ in changed_ids)
            cursor = connection.execute(
                f"""UPDATE vehicle_features SET is_active=0, rolled_back_at=?, rollback_reason=?
                WHERE is_active=1 AND id IN ({changed_placeholders})""",
                [time(), reason, *changed_ids],
            )
            event = connection.execute(
                """INSERT INTO gallery_rollback_events
                (created_at, actor, reason, feature_ids_json) VALUES (?, ?, ?, ?)""",
                (time(), actor, reason, json.dumps(changed_ids)),
            )
            connection.commit()
            return GalleryRollbackResult(
                int(event.lastrowid), changed_ids, int(cursor.rowcount or 0), reason
            )

        return self._database.call(operation)

    def rollback_write(
        self, write_id: str, *, reason: str, actor: str
    ) -> GalleryRollbackResult:
        rows = self._database.execute(
            """SELECT id FROM vehicle_features WHERE is_active=1
            AND json_extract(provenance_json, '$.write_id')=?""",
            (write_id,),
        ).fetchall()
        return self.rollback_features(
            [int(row["id"]) for row in rows], reason=reason, actor=actor
        )

    def rollback_events(self, limit: int = 100) -> list[GalleryRollbackEvent]:
        rows = self._database.execute(
            """SELECT id, created_at, actor, reason, feature_ids_json
            FROM gallery_rollback_events ORDER BY id DESC LIMIT ?""",
            (max(1, int(limit)),),
        ).fetchall()
        events = []
        for row in rows:
            try:
                feature_ids = tuple(int(item) for item in json.loads(row["feature_ids_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                feature_ids = ()
            events.append(GalleryRollbackEvent(
                int(row["id"]), float(row["created_at"]), str(row["actor"]),
                str(row["reason"]), feature_ids,
            ))
        return events

    def _ensure_schema(self) -> None:
        self._database.execute("""CREATE TABLE IF NOT EXISTS vehicle_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
            gallery_type TEXT NOT NULL CHECK(gallery_type IN ('master','pending','candidate')),
            created_at REAL NOT NULL, frame_index INTEGER NOT NULL, track_id INTEGER,
            bbox_json TEXT NOT NULL, quality_score REAL NOT NULL, duplicate_score REAL,
            embedding_json TEXT NOT NULL, crop_jpeg BLOB, metadata_json TEXT,
            provenance_json TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            rolled_back_at REAL, rollback_reason TEXT)""", commit=True)
        self._ensure_column("vehicle_features", "provenance_json", "TEXT")
        self._ensure_column("vehicle_features", "is_active", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("vehicle_features", "rolled_back_at", "REAL")
        self._ensure_column("vehicle_features", "rollback_reason", "TEXT")
        self._database.execute("""UPDATE vehicle_features
            SET provenance_json=json_object(
                'write_id', 'legacy-' || id,
                'source', 'legacy_migration',
                'global_vehicle_id', vehicle_id,
                'local_track_id', track_id,
                'frame_index', frame_index,
                'identity_state', 'UNKNOWN',
                'identity_reason_code', 'LEGACY_MIGRATION',
                'identity_score', 0.0)
            WHERE provenance_json IS NULL OR provenance_json=''""", commit=True)
        self._database.execute("""CREATE TABLE IF NOT EXISTS gallery_rollback_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
            actor TEXT NOT NULL, reason TEXT NOT NULL, feature_ids_json TEXT NOT NULL)""", commit=True)
        self._database.execute("""CREATE TRIGGER IF NOT EXISTS trg_vehicle_features_provenance
            BEFORE INSERT ON vehicle_features
            WHEN NEW.provenance_json IS NULL
              OR json_valid(NEW.provenance_json)=0
              OR json_extract(NEW.provenance_json, '$.write_id') IS NULL
              OR json_extract(NEW.provenance_json, '$.source') IS NULL
              OR json_extract(NEW.provenance_json, '$.global_vehicle_id') IS NULL
              OR json_extract(NEW.provenance_json, '$.frame_index') IS NULL
              OR COALESCE(json_extract(NEW.provenance_json, '$.identity_state'), '') != 'LOCKED'
              OR json_extract(NEW.provenance_json, '$.identity_reason_code') IS NULL
              OR COALESCE(json_type(NEW.provenance_json, '$.identity_sub_scores'), '') != 'object'
              OR COALESCE(json_extract(NEW.provenance_json, '$.identity_score'), 0.0) < 0.84
              OR COALESCE(json_extract(NEW.provenance_json, '$.decision_accepted'), 0) != 1
              OR COALESCE(json_extract(NEW.provenance_json, '$.motor_safe_to_track'), 0) != 1
            BEGIN
                SELECT RAISE(ABORT, 'embedding provenance with write_id is required');
            END""", commit=True)
        self._database.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_features_vehicle_gallery ON vehicle_features(vehicle_id, gallery_type)", commit=True)
        self._database.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_features_gallery ON vehicle_features(gallery_type)", commit=True)

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self._database.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {str(row["name"]) for row in rows}:
            self._database.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}", commit=True
            )
