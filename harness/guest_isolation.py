"""Historical guest/input-isolation validator retained for old replay records.

The current product does not use a guest/VM.  Direct runtime gates use
``harness.host_input_isolation``.  This module validates only old archived
guest fixtures; it never creates a positive trace or falls back to host input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


class GuestIsolationEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class GuestIsolationAssessment:
    ready: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GuestIsolationEvidence:
    evidence_id: str
    run_id: str
    guest_id: str
    started_at: str
    ended_at: str
    duration_seconds: float
    capture_refreshes: int
    target_binding_verified: bool
    host_input_events_before: int
    host_input_events_after: int
    host_focus_changes: int
    guest_input_events: int
    benign_guest_action_verified: bool
    disconnect_tested: bool
    resize_tested: bool
    cancel_tested: bool
    host_fallback_used: bool
    environment: str = "windows_guest"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise GuestIsolationEvidenceError("unsupported guest-isolation schema_version")
        for name in ("evidence_id", "run_id", "guest_id", "started_at", "ended_at", "environment"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GuestIsolationEvidenceError(f"{name} must be a non-empty string")
        if self.environment != "windows_guest":
            raise GuestIsolationEvidenceError("environment must be windows_guest")
        if type(self.duration_seconds) not in (int, float) or self.duration_seconds < 0:
            raise GuestIsolationEvidenceError("duration_seconds must be non-negative")
        for name in (
            "capture_refreshes",
            "host_input_events_before",
            "host_input_events_after",
            "host_focus_changes",
            "guest_input_events",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise GuestIsolationEvidenceError(f"{name} must be a non-negative integer")
        for name in (
            "target_binding_verified",
            "benign_guest_action_verified",
            "disconnect_tested",
            "resize_tested",
            "cancel_tested",
            "host_fallback_used",
        ):
            if type(getattr(self, name)) is not bool:
                raise GuestIsolationEvidenceError(f"{name} must be boolean")
        try:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            ended = datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GuestIsolationEvidenceError("started_at/ended_at must be ISO-8601") from exc
        if started.tzinfo is None or ended.tzinfo is None:
            raise GuestIsolationEvidenceError("started_at/ended_at must include timezone")
        if ended < started:
            raise GuestIsolationEvidenceError("ended_at must not precede started_at")

    @property
    def host_input_delta(self) -> int:
        return self.host_input_events_after - self.host_input_events_before

    def assess(self, *, minimum_duration_seconds: float = 1800.0) -> GuestIsolationAssessment:
        if minimum_duration_seconds <= 0:
            raise GuestIsolationEvidenceError("minimum_duration_seconds must be positive")
        reasons: list[str] = []
        if self.duration_seconds < minimum_duration_seconds:
            reasons.append("guest trace is shorter than the R2 minimum duration")
        if self.capture_refreshes < 1:
            reasons.append("no refreshed guest capture is recorded")
        if not self.target_binding_verified:
            reasons.append("guest target/frame binding is not verified")
        if self.host_input_delta != 0:
            reasons.append("host input counter changed during the trace")
        if self.host_focus_changes != 0:
            reasons.append("host focus changed during the trace")
        if self.host_fallback_used:
            reasons.append("host-input fallback was used")
        if self.guest_input_events < 1 or not self.benign_guest_action_verified:
            reasons.append("no benign guest-only action is verified")
        if not self.disconnect_tested:
            reasons.append("disconnect behavior was not tested")
        if not self.resize_tested:
            reasons.append("resize behavior was not tested")
        if not self.cancel_tested:
            reasons.append("cancel behavior was not tested")
        return GuestIsolationAssessment(not reasons, tuple(reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "guest_id": self.guest_id,
            "environment": self.environment,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "capture_refreshes": self.capture_refreshes,
            "target_binding_verified": self.target_binding_verified,
            "host_input_events_before": self.host_input_events_before,
            "host_input_events_after": self.host_input_events_after,
            "host_focus_changes": self.host_focus_changes,
            "guest_input_events": self.guest_input_events,
            "benign_guest_action_verified": self.benign_guest_action_verified,
            "disconnect_tested": self.disconnect_tested,
            "resize_tested": self.resize_tested,
            "cancel_tested": self.cancel_tested,
            "host_fallback_used": self.host_fallback_used,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GuestIsolationEvidence":
        if not isinstance(raw, Mapping):
            raise GuestIsolationEvidenceError("guest-isolation evidence must be an object")
        required = {
            "evidence_id", "run_id", "guest_id", "environment", "started_at", "ended_at",
            "duration_seconds", "capture_refreshes", "target_binding_verified",
            "host_input_events_before", "host_input_events_after", "host_focus_changes",
            "guest_input_events", "benign_guest_action_verified", "disconnect_tested",
            "resize_tested", "cancel_tested", "host_fallback_used",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise GuestIsolationEvidenceError("guest-isolation evidence is missing: " + ", ".join(missing))
        try:
            return cls(
                schema_version=int(raw.get("schema_version", 1)),
                evidence_id=str(raw["evidence_id"]),
                run_id=str(raw["run_id"]),
                guest_id=str(raw["guest_id"]),
                environment=str(raw["environment"]),
                started_at=str(raw["started_at"]),
                ended_at=str(raw["ended_at"]),
                duration_seconds=raw["duration_seconds"],
                capture_refreshes=raw["capture_refreshes"],
                target_binding_verified=raw["target_binding_verified"],
                host_input_events_before=raw["host_input_events_before"],
                host_input_events_after=raw["host_input_events_after"],
                host_focus_changes=raw["host_focus_changes"],
                guest_input_events=raw["guest_input_events"],
                benign_guest_action_verified=raw["benign_guest_action_verified"],
                disconnect_tested=raw["disconnect_tested"],
                resize_tested=raw["resize_tested"],
                cancel_tested=raw["cancel_tested"],
                host_fallback_used=raw["host_fallback_used"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, GuestIsolationEvidenceError):
                raise
            raise GuestIsolationEvidenceError("malformed guest-isolation evidence") from exc
