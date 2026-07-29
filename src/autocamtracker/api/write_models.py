"""Models and ports for authenticated public mutations."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autocamtracker.api.auth import Principal


class VehiclePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(min_length=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "VehiclePatchRequest":
        if self.display_name is None and self.metadata is None:
            raise ValueError("display_name or metadata is required")
        return self


class VehicleWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cloud_id: str
    node_id: str
    local_id: int = Field(ge=1)
    display_name: str
    metadata: dict[str, Any]
    updated_at: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class AuditContext:
    request_id: str
    actor: Principal
    source_ip: str | None
    user_agent: str | None


class VehicleNotFound(LookupError):
    pass


class VehicleWriteConflict(RuntimeError):
    pass


class VehicleScopeDenied(PermissionError):
    pass


@runtime_checkable
class VehicleWriteService(Protocol):
    def patch_vehicle(
        self,
        cloud_id: str,
        patch: VehiclePatchRequest,
        audit: AuditContext,
    ) -> VehicleWriteResponse: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


@runtime_checkable
class RateLimiter(Protocol):
    def consume(self, subject: str, route: str) -> RateLimitDecision: ...


class InMemoryRateLimiter:
    """Reference fixed-window limiter for tests and single-process development."""

    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = max(1, requests)
        self.window_seconds = max(1, window_seconds)
        self._counts: dict[tuple[str, str, int], int] = {}
        self._lock = Lock()

    def consume(self, subject: str, route: str) -> RateLimitDecision:
        now = int(time())
        window = now - now % self.window_seconds
        key = (subject, route, window)
        with self._lock:
            count = self._counts.get(key, 0) + 1
            self._counts[key] = count
        if count <= self.requests:
            return RateLimitDecision(True)
        return RateLimitDecision(False, max(1, window + self.window_seconds - now))
