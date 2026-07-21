"""SQLite persistence for ReID gallery features."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from time import time

from autocamtracker.tracking.feature_models import CropQuality, FeatureMatch, FeatureSnapshot, GalleryType, StoredFeature
from autocamtracker.vision.detector import TrackedDetection


class FeatureRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        self.connection.close()

    def insert(self, vehicle_id: int, gallery_type: GalleryType, detection: TrackedDetection,
               quality: CropQuality, embedding: list[float], duplicate_score: float | None,
               crop_jpeg: bytes | None, model_path: str) -> int:
        cursor = self.connection.execute(
            """INSERT INTO vehicle_features (vehicle_id, gallery_type, created_at, frame_index,
            track_id, bbox_json, quality_score, duplicate_score, embedding_json, crop_jpeg, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, gallery_type, time(), detection.frame_index, detection.track_id,
             json.dumps(list(detection.bbox)), quality.score, duplicate_score,
             json.dumps([float(value) for value in embedding]), crop_jpeg,
             json.dumps({"class_name": detection.class_name, "confidence": detection.confidence,
                         "reid_model_label": Path(model_path).name or model_path,
                         "reid_model_path": model_path, "quality_reason": quality.reason,
                         "crop_width": quality.width, "crop_height": quality.height,
                         "sharpness": quality.sharpness, "brightness": quality.brightness}, sort_keys=True)))
        self.connection.commit()
        return int(cursor.lastrowid)

    def stored_features(self, gallery_type: GalleryType, vehicle_id: int | None = None) -> list[StoredFeature]:
        rows = self.connection.execute(
            """SELECT id, vehicle_id, gallery_type, embedding_json, quality_score, frame_index
            FROM vehicle_features WHERE gallery_type = ? AND embedding_json IS NOT NULL
            AND (? IS NULL OR vehicle_id = ?)""", (gallery_type, vehicle_id, vehicle_id)).fetchall()
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
        row = self.connection.execute("SELECT COUNT(*) AS count FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master'", (vehicle_id,)).fetchone()
        return bool(row and int(row["count"]) > 0)

    def dominant_master_class(self, vehicle_id: int) -> str | None:
        row = self.connection.execute("""SELECT json_extract(metadata_json, '$.class_name') AS class_name, COUNT(*) AS count
            FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master' AND class_name IS NOT NULL
            GROUP BY class_name ORDER BY count DESC, class_name ASC LIMIT 1""", (vehicle_id,)).fetchone()
        return str(row["class_name"]) if row and row["class_name"] else None

    def summary_by_vehicle(self) -> dict[int, dict[str, int]]:
        rows = self.connection.execute("SELECT vehicle_id, gallery_type, COUNT(*) AS count FROM vehicle_features GROUP BY vehicle_id, gallery_type").fetchall()
        summary: dict[int, dict[str, int]] = {}
        for row in rows:
            summary.setdefault(int(row["vehicle_id"]), {})[str(row["gallery_type"])] = int(row["count"])
        return summary

    def model_labels_by_vehicle(self, gallery_type: GalleryType = "master") -> dict[int, str]:
        rows = self.connection.execute("""SELECT vehicle_id, COALESCE(NULLIF(json_extract(metadata_json,
            '$.reid_model_label'), ''), NULLIF(json_extract(metadata_json, '$.reid_model_path'), ''), 'Unknown') AS label,
            COUNT(*) AS count, MAX(created_at) AS latest FROM vehicle_features WHERE gallery_type=?
            GROUP BY vehicle_id, label ORDER BY vehicle_id, count DESC, latest DESC""", (gallery_type,)).fetchall()
        labels: dict[int, str] = {}
        for row in rows:
            labels.setdefault(int(row["vehicle_id"]), str(row["label"] or "Unknown"))
        return labels

    def delete_vehicle_features(self, vehicle_id: int) -> int:
        cursor = self.connection.execute("DELETE FROM vehicle_features WHERE vehicle_id=?", (vehicle_id,))
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def delete_features(self, feature_ids: list[int], vehicle_id: int | None = None) -> int:
        ids = sorted({int(item) for item in feature_ids if int(item) > 0})
        if not ids:
            return 0
        clause = " AND vehicle_id=?" if vehicle_id is not None else ""
        parameters = ids + ([int(vehicle_id)] if vehicle_id is not None else [])
        cursor = self.connection.execute(f"DELETE FROM vehicle_features WHERE id IN ({','.join('?' for _ in ids)}){clause}", parameters)
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def snapshots(self, vehicle_id: int, gallery_type: GalleryType = "master") -> list[FeatureSnapshot]:
        rows = self.connection.execute("""SELECT id, vehicle_id, gallery_type, created_at, frame_index,
            track_id, quality_score, duplicate_score, crop_jpeg, metadata_json FROM vehicle_features
            WHERE vehicle_id=? AND gallery_type=? ORDER BY created_at DESC, id DESC""", (vehicle_id, gallery_type)).fetchall()
        result = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            result.append(FeatureSnapshot(int(row["id"]), int(row["vehicle_id"]), str(row["gallery_type"]),
                float(row["created_at"]), int(row["frame_index"]), row["track_id"], float(row["quality_score"]),
                float(row["duplicate_score"]) if row["duplicate_score"] is not None else None,
                bytes(row["crop_jpeg"]) if row["crop_jpeg"] is not None else None,
                metadata if isinstance(metadata, dict) else {}))  # type: ignore[arg-type]
        return result

    def first_crop_jpeg(self, vehicle_id: int) -> bytes | None:
        row = self.connection.execute("""SELECT crop_jpeg FROM vehicle_features WHERE vehicle_id=? AND crop_jpeg IS NOT NULL
            ORDER BY CASE gallery_type WHEN 'master' THEN 0 WHEN 'candidate' THEN 1 ELSE 2 END, created_at, id LIMIT 1""", (vehicle_id,)).fetchone()
        return bytes(row["crop_jpeg"]) if row and row["crop_jpeg"] is not None else None

    def prune_master(self, vehicle_id: int, limit: int) -> int:
        rows = self.connection.execute("SELECT id FROM vehicle_features WHERE vehicle_id=? AND gallery_type='master' ORDER BY quality_score, created_at", (vehicle_id,)).fetchall()
        ids = [int(row["id"]) for row in rows[:max(0, len(rows) - limit)]]
        if not ids:
            return 0
        cursor = self.connection.execute(f"DELETE FROM vehicle_features WHERE id IN ({','.join('?' for _ in ids)})", ids)
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def _ensure_schema(self) -> None:
        self.connection.execute("""CREATE TABLE IF NOT EXISTS vehicle_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
            gallery_type TEXT NOT NULL CHECK(gallery_type IN ('master','pending','candidate')),
            created_at REAL NOT NULL, frame_index INTEGER NOT NULL, track_id INTEGER,
            bbox_json TEXT NOT NULL, quality_score REAL NOT NULL, duplicate_score REAL,
            embedding_json TEXT NOT NULL, crop_jpeg BLOB, metadata_json TEXT)""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_features_vehicle_gallery ON vehicle_features(vehicle_id, gallery_type)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_features_gallery ON vehicle_features(gallery_type)")
        self.connection.commit()
