"""Command-line entry point for the local read-only API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from autocamtracker.api.app import ApiSettings, create_app
from autocamtracker.edge_control.api import EdgeControlSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Vision Director read-only API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--identity-db", type=Path, default=Path("outputs/vehicle_identity.sqlite3"))
    parser.add_argument("--telemetry-dir", type=Path, default=Path("outputs/telemetry"))
    parser.add_argument("--node-id", default=None)
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=[],
        help="Exact dashboard origin, for example http://192.168.1.20:3000",
    )
    args = parser.parse_args()
    defaults = ApiSettings()
    settings = ApiSettings(
        identity_db_path=args.identity_db,
        telemetry_dir=args.telemetry_dir,
        node_id=args.node_id or defaults.node_id,
        cors_allow_origins=tuple(
            args.cors_origin
            or filter(
                None,
                (
                    value.strip()
                    for value in os.environ.get(
                        "AIVD_CORS_ALLOW_ORIGINS", ""
                    ).split(",")
                ),
            )
        ),
        edge_control=(
            EdgeControlSettings.from_env()
            if os.environ.get("AIVD_EDGE_DEVICE_TOKEN")
            else None
        ),
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
