from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AccessRequest:
    request_id: str
    request_type: str
    principal_email: str
    resource_name: str
    role: str
    status: str
    approved_at: datetime | None


@dataclass(frozen=True)
class ExecutionResult:
    result: str  # SUCCESS / FAILED / SKIPPED
    action: str
    target: str
    before_hash: str | None
    after_hash: str | None
    error_code: str | None = None
    error_message: str | None = None
    details: dict[str, Any] | None = None
