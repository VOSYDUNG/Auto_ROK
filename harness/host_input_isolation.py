"""Fail-closed input-isolation evidence for the real one-user Windows host.

The product target is one physical Windows machine and one operator session.
This contract deliberately does not mention a guest, VM, Docker or a second
desktop.  It proves only the narrower property the direct-host product can
claim: a fresh target-bound frame is current, the operator has handed the
foreground to ROK for the bounded action window, and the action channel did
not fall back to an unbound desktop surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


class HostInputIsolationEvidenceError(ValueError):
    """Raised when direct-host evidence is malformed."""


@dataclass(frozen=True)
class HostInputIsolationEvidence:
    evidence_id: str
    run_id: str
    session_id: str
    started_at: str
    ended_at: str
    duration_seconds: float
    capture_refreshes: int
    target_binding_verified: bool
    target_foreground_verified: bool
    host_focus_changes: int
    unexpected_input_events: int
    operator_input_quiescent: bool
    stale_frame_rejected: bool
    cancel_tested: bool
    host_fallback_used: bool
    environment: str = "windows_host_direct"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise HostInputIsolationEvidenceError("unsupported host input-isolation schema_version")
        for name in (
            "evidence_id", "run_id", "session_id", "started_at", "ended_at", "environment"
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise HostInputIsolationEvidenceError(f"{name} must be a non-empty string")
        if self.environment != "windows_host_direct":
            raise HostInputIsolationEvidenceError(
                "environment must be windows_host_direct; guest/VM evidence is out of product scope"
            )
        if type(self.duration_seconds) not in (int, float) or self.duration_seconds < 0:
            raise HostInputIsolationEvidenceError("duration_seconds must be non-negative")
        for name in ("capture_refreshes", "host_focus_changes", "unexpected_input_events"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise HostInputIsolationEvidenceError(f"{name} must be a non-negative integer")
        for name in (
            "target_binding_verified", "target_foreground_verified", "operator_input_quiescent",
            "stale_frame_rejected", "cancel_tested", "host_fallback_used",
        ):
            if type(getattr(self, name)) is not bool:
                raise HostInputIsolationEvidenceError(f"{name} must be boolean")
        try:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            ended = datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HostInputIsolationEvidenceError("started_at/ended_at must be ISO-8601") from exc
        if started.tzinfo is None or ended.tzinfo is None:
            raise HostInputIsolationEvidenceError("started_at/ended_at must include timezone")
        if ended < started:
            raise HostInputIsolationEvidenceError("ended_at must not precede started_at")

    def assess(self) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if self.capture_refreshes < 1:
            reasons.append("no refreshed direct-host capture is recorded")
        if not self.target_binding_verified:
            reasons.append("direct-host target/frame binding is not verified")
        if not self.target_foreground_verified:
            reasons.append("ROK target was not foreground at the guard check")
        if self.host_focus_changes != 0:
            reasons.append("host focus changed during the bounded direct-host window")
        if self.unexpected_input_events != 0:
            reasons.append("unexpected input events were observed")
        if not self.operator_input_quiescent:
            reasons.append("operator input was not explicitly quiescent for the bounded window")
        if not self.stale_frame_rejected:
            reasons.append("stale-frame rejection is not evidenced")
        if not self.cancel_tested:
            reasons.append("cancel behavior is not evidenced")
        if self.host_fallback_used:
            reasons.append("unbound desktop/input fallback was used")
        return not reasons, tuple(reasons)

    @property
    def ready(self) -> bool:
        return self.assess()[0]

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.assess()[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "environment": self.environment,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "capture_refreshes": self.capture_refreshes,
            "target_binding_verified": self.target_binding_verified,
            "target_foreground_verified": self.target_foreground_verified,
            "host_focus_changes": self.host_focus_changes,
            "unexpected_input_events": self.unexpected_input_events,
            "operator_input_quiescent": self.operator_input_quiescent,
            "stale_frame_rejected": self.stale_frame_rejected,
            "cancel_tested": self.cancel_tested,
            "host_fallback_used": self.host_fallback_used,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "HostInputIsolationEvidence":
        if not isinstance(raw, Mapping):
            raise HostInputIsolationEvidenceError("host input-isolation evidence must be an object")
        required = {
            "evidence_id", "run_id", "session_id", "environment", "started_at", "ended_at",
            "duration_seconds", "capture_refreshes", "target_binding_verified",
            "target_foreground_verified", "host_focus_changes", "unexpected_input_events",
            "operator_input_quiescent", "stale_frame_rejected", "cancel_tested",
            "host_fallback_used",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise HostInputIsolationEvidenceError("host input-isolation evidence is missing: " + ", ".join(missing))
        try:
            return cls(
                schema_version=int(raw.get("schema_version", 1)),
                evidence_id=str(raw["evidence_id"]),
                run_id=str(raw["run_id"]),
                session_id=str(raw["session_id"]),
                environment=str(raw["environment"]),
                started_at=str(raw["started_at"]),
                ended_at=str(raw["ended_at"]),
                duration_seconds=raw["duration_seconds"],
                capture_refreshes=raw["capture_refreshes"],
                target_binding_verified=raw["target_binding_verified"],
                target_foreground_verified=raw["target_foreground_verified"],
                host_focus_changes=raw["host_focus_changes"],
                unexpected_input_events=raw["unexpected_input_events"],
                operator_input_quiescent=raw["operator_input_quiescent"],
                stale_frame_rejected=raw["stale_frame_rejected"],
                cancel_tested=raw["cancel_tested"],
                host_fallback_used=raw["host_fallback_used"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, HostInputIsolationEvidenceError):
                raise
            raise HostInputIsolationEvidenceError("malformed host input-isolation evidence") from exc
