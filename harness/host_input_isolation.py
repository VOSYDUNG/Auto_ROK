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
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from harness.gather_job_store import GatherClientBinding, GatherJobStoreError


class HostInputIsolationEvidenceError(ValueError):
    """Raised when direct-host evidence is malformed."""


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostInputIsolationEvidenceError(f"{label} is unreadable") from exc
    if not isinstance(value, Mapping):
        raise HostInputIsolationEvidenceError(f"{label} must be an object")
    return value


def _under(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HostInputIsolationEvidenceError(f"{label} must be under {root}") from exc
    if resolved == root.resolve() or not resolved.is_file():
        raise HostInputIsolationEvidenceError(f"{label} must be an existing file")
    return resolved


def _trace_path(value: Any, base: Path, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise HostInputIsolationEvidenceError(f"{label} path is missing")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return _under(path, root, label)


def validate_gather_job_host_trace(
    path: Path,
    *,
    expected_run_id: str,
    expected_client: GatherClientBinding,
    workspace_root: Path,
    now: datetime | None = None,
    max_age_seconds: float = 10.0,
) -> dict[str, object]:
    """Validate one fresh recorder trace for a GATHER job preflight.

    This validates recorder self-report and capture provenance only.  It does
    not turn ``input_telemetry`` into independent host instrumentation.
    """
    if not isinstance(expected_run_id, str) or not expected_run_id:
        raise HostInputIsolationEvidenceError("expected_run_id must be non-empty")
    if type(max_age_seconds) not in (int, float) or max_age_seconds < 0:
        raise HostInputIsolationEvidenceError("max_age_seconds must be non-negative")
    workspace = Path(workspace_root).resolve()
    if now is not None and now.tzinfo is None:
        raise HostInputIsolationEvidenceError("now must include timezone")
    evidence_root, runs_root = workspace / "evidence", workspace / "runs"
    trace_path = _under(Path(path), evidence_root, "trace")
    raw = _read_json(trace_path, "trace")
    trace = raw.get("evidence") if isinstance(raw.get("evidence"), Mapping) else raw
    evidence = HostInputIsolationEvidence.from_dict(trace)
    if evidence.run_id != expected_run_id:
        raise HostInputIsolationEvidenceError("trace run_id does not match expected run")
    ready, reasons = evidence.assess()
    if not ready:
        raise HostInputIsolationEvidenceError("host input-isolation evidence is not ready: " + "; ".join(reasons))

    def parse_time(value: Any, label: str) -> datetime:
        if not isinstance(value, str):
            raise HostInputIsolationEvidenceError(f"{label} must be ISO-8601")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HostInputIsolationEvidenceError(f"{label} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise HostInputIsolationEvidenceError(f"{label} must include timezone")
        return parsed.astimezone(timezone.utc)

    started, ended = parse_time(evidence.started_at, "started_at"), parse_time(evidence.ended_at, "ended_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if ended > current:
        raise HostInputIsolationEvidenceError("trace ended_at is in the future")
    if (current - ended).total_seconds() > float(max_age_seconds):
        raise HostInputIsolationEvidenceError("trace is stale")

    # Recorder paths are normally absolute; relative paths are rooted at the
    # supplied workspace so synthetic/offline traces have one unambiguous base.
    capture_meta = _trace_path(raw.get("capture_meta"), workspace, runs_root, "capture metadata")
    png_path = _trace_path(raw.get("capture_output"), workspace, runs_root, "capture PNG")
    capture = _read_json(capture_meta, "capture metadata")
    if capture.get("status") != "captured":
        raise HostInputIsolationEvidenceError("capture metadata status is not captured")
    backend = capture.get("backend")
    if (not isinstance(backend, Mapping) or backend.get("name") != "windows-capture"
            or backend.get("target_mode") != "window_hwnd"):
        raise HostInputIsolationEvidenceError("capture backend is not native windows-capture")
    frame = capture.get("frame")
    if not isinstance(frame, Mapping):
        raise HostInputIsolationEvidenceError("capture frame metadata is missing")
    manifest_png = _trace_path(capture.get("png"), workspace, runs_root, "capture manifest PNG")
    if manifest_png != png_path:
        raise HostInputIsolationEvidenceError("capture manifest PNG does not match trace capture PNG")
    captured_at = parse_time(frame.get("captured_at"), "frame captured_at")
    if captured_at < started or captured_at > ended:
        raise HostInputIsolationEvidenceError("frame was not captured within trace window")
    for name in ("target", "pre_capture", "post_capture"):
        try:
            observed = GatherClientBinding.from_window(capture.get(name))
        except (GatherJobStoreError, ValueError, TypeError) as exc:
            raise HostInputIsolationEvidenceError(f"capture {name} binding is invalid") from exc
        if observed != expected_client:
            raise HostInputIsolationEvidenceError(f"capture {name} binding does not match expected client")
    if raw.get("foreground_before_hwnd") != expected_client.hwnd or raw.get("foreground_after_hwnd") != expected_client.hwnd:
        raise HostInputIsolationEvidenceError("trace foreground target does not match expected client")
    if raw.get("host_focus_changes") != 0:
        raise HostInputIsolationEvidenceError("trace records a host focus change")
    non_interference = capture.get("non_interference")
    interference_flags = {"foreground_activation", "mouse_input", "keyboard_input", "desktop_fallback"}
    if (not isinstance(non_interference, Mapping)
            or not interference_flags.issubset(non_interference)
            or any(non_interference.get(flag) is not False for flag in interference_flags)):
        raise HostInputIsolationEvidenceError("capture non_interference must contain only false values")
    expected_hash = frame.get("image_sha256")
    if not isinstance(expected_hash, str) or hashlib.sha256(png_path.read_bytes()).hexdigest() != expected_hash:
        raise HostInputIsolationEvidenceError("capture PNG hash does not match frame metadata")
    return {
        "ready": True,
        "trace_id": evidence.evidence_id,
        "evidence_id": evidence.evidence_id,
        "run_id": evidence.run_id,
        "client": expected_client.to_json(),
        "ended_at": evidence.ended_at,
        "input_telemetry": "recorder_self_report_only",
    }


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
