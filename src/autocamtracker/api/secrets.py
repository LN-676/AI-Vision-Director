"""Fail-closed public API settings with file-backed secret support."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


def _secret(environ: Mapping[str, str], name: str) -> str | None:
    direct = environ.get(name)
    file_name = environ.get(f"{name}_FILE")
    if direct and file_name:
        raise ValueError(f"set only one of {name} or {name}_FILE")
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise ValueError(f"{name}_FILE does not exist")
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = (direct or "").strip()
    return value or None


@dataclass(frozen=True, slots=True)
class PublicApiSettings:
    database_url: str = field(repr=False)
    firebase_project_id: str
    cors_allow_origins: tuple[str, ...]
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    forwarded_allow_ips: str = "127.0.0.1"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "PublicApiSettings":
        values = os.environ if environ is None else environ
        database_url = _secret(values, "AIVD_DATABASE_URL")
        project_id = _secret(values, "AIVD_FIREBASE_PROJECT_ID")
        if not database_url:
            raise ValueError("AIVD_DATABASE_URL or AIVD_DATABASE_URL_FILE is required")
        if not project_id:
            raise ValueError("AIVD_FIREBASE_PROJECT_ID is required")
        origins = tuple(
            origin.strip()
            for origin in values.get("AIVD_CORS_ALLOW_ORIGINS", "").split(",")
            if origin.strip()
        )
        if not origins:
            raise ValueError("AIVD_CORS_ALLOW_ORIGINS must contain an explicit allowlist")
        if "*" in origins:
            raise ValueError("wildcard CORS origins are not allowed")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid CORS origin: {origin}")
        requests = int(values.get("AIVD_RATE_LIMIT_REQUESTS", "30"))
        window = int(values.get("AIVD_RATE_LIMIT_WINDOW_SECONDS", "60"))
        if requests <= 0 or window <= 0:
            raise ValueError("rate limit settings must be positive")
        forwarded_allow_ips = values.get("AIVD_FORWARDED_ALLOW_IPS", "127.0.0.1").strip()
        if not forwarded_allow_ips:
            raise ValueError("AIVD_FORWARDED_ALLOW_IPS must not be empty")
        if forwarded_allow_ips == "*":
            raise ValueError("wildcard trusted proxy addresses are not allowed")
        return cls(
            database_url,
            project_id,
            origins,
            requests,
            window,
            forwarded_allow_ips,
        )
