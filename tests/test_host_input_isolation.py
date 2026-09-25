from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from harness.gather_job_store import GatherClientBinding
from harness.host_input_isolation import (HostInputIsolationEvidence, HostInputIsolationEvidenceError,
                                           validate_gather_job_host_trace)
from scripts.record_host_input_isolation import _recovery_contract, _stale_frame_contract


def evidence(**overrides):
    raw = {
        "schema_version": 1,
        "evidence_id": "host-r2-01",
        "run_id": "run-r2-01",
        "session_id": "windows-session-01",
        "environment": "windows_host_direct",
        "started_at": "2026-09-18T00:00:00+00:00",
        "ended_at": "2026-09-18T00:00:02+00:00",
        "duration_seconds": 2,
        "capture_refreshes": 2,
        "target_binding_verified": True,
        "target_foreground_verified": True,
        "host_focus_changes": 0,
        "unexpected_input_events": 0,
        "operator_input_quiescent": True,
        "stale_frame_rejected": True,
        "cancel_tested": True,
        "host_fallback_used": False,
    }
    raw.update(overrides)
    return HostInputIsolationEvidence.from_dict(raw)


def test_direct_host_trace_is_ready_without_guest_or_vm():
    item = evidence()
    assert item.ready is True
    assert item.reasons == ()
    assert item.to_dict()["environment"] == "windows_host_direct"


def test_operator_quiescence_and_fallback_fail_closed():
    item = evidence(operator_input_quiescent=False, host_fallback_used=True)
    assert item.ready is False
    assert "operator input" in " ".join(item.reasons)
    assert "fallback" in " ".join(item.reasons)


def test_guest_environment_is_rejected_for_direct_product():
    with pytest.raises(HostInputIsolationEvidenceError):
        evidence(environment="windows_guest")


def test_missing_field_fails_closed():
    raw = evidence().to_dict()
    raw.pop("target_binding_verified")
    with pytest.raises(HostInputIsolationEvidenceError):
        HostInputIsolationEvidence.from_dict(raw)


def test_recorder_stale_frame_self_check_uses_current_capture(tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"capture-bytes")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    capture = {
        "schema_version": 1,
        "status": "captured",
        "backend": {"name": "windows-capture", "version": "2.0.1"},
        "target": {"title": "Rise of Kingdoms", "exe": "MASS.exe", "hwnd": 1, "pid": 2},
        "frame": {
            "id": "frame-1",
            "captured_at": "2026-09-18T00:00:00+00:00",
            "width": 4,
            "height": 4,
            "client_bounds": [0, 0, 4, 4],
            "dpi_scale": 1.0,
            "image_sha256": digest,
        },
    }
    result = _stale_frame_contract(capture, image)
    assert result["passed"] is True
    assert "stale" in result["reason"]


def test_recovery_contract_rejects_input_emitting_report(tmp_path):
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps({
        "status": "pass",
        "input_emitted_any": False,
        "cancel": {"requested": 1, "passed": 1},
        "restart": {"requested": 1, "passed": 1},
    }), encoding="utf-8")
    assert _recovery_contract(path)["passed"] is True
    path.write_text(json.dumps({
        "status": "pass",
        "input_emitted_any": True,
        "cancel": {"requested": 1, "passed": 1},
        "restart": {"requested": 1, "passed": 1},
    }), encoding="utf-8")
    assert _recovery_contract(path)["passed"] is False


def _fresh_trace(tmp_path: Path, **changes):
    root = tmp_path
    evidence_root, runs_root = root / "evidence", root / "runs" / "run-1"
    evidence_root.mkdir(parents=True)
    runs_root.mkdir(parents=True)
    ended = datetime(2026, 9, 25, 0, 0, 5, tzinfo=timezone.utc)
    image = runs_root / "frame.png"
    image.write_bytes(b"capture")
    client = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}
    capture = {"schema_version": 1, "status": "captured",
               "backend": {"name": "windows-capture", "version": "2", "target_mode": "window_hwnd"},
               "target": client, "pre_capture": client, "post_capture": client,
               "frame": {"id": "frame-1", "captured_at": ended.isoformat(),
                         "image_sha256": hashlib.sha256(b"capture").hexdigest()},
               "png": str(image),
               "non_interference": {"foreground_activation": False, "mouse_input": False,
                                     "keyboard_input": False, "desktop_fallback": False}}
    meta = runs_root / "frame.capture.json"
    meta.write_text(json.dumps(capture), encoding="utf-8")
    trace = evidence(evidence_id="evidence-id", run_id="run-1", started_at=(ended - timedelta(seconds=1)).isoformat(),
                     ended_at=ended.isoformat(), capture_refreshes=1, target_binding_verified=True,
                     target_foreground_verified=True, host_focus_changes=0, unexpected_input_events=0,
                     operator_input_quiescent=True, stale_frame_rejected=True, cancel_tested=True,
                     host_fallback_used=False).to_dict()
    trace.update({"capture_meta": str(meta), "capture_output": str(image),
                  "foreground_before_hwnd": 1001, "foreground_after_hwnd": 1001})
    trace_path = evidence_root / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    return root, trace_path, GatherClientBinding.from_window(client), ended


def test_gather_job_host_trace_validator_accepts_fresh_bound_capture(tmp_path):
    root, trace, client, ended = _fresh_trace(tmp_path)
    result = validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                            workspace_root=root, now=ended)
    assert result["ready"] is True
    assert result["input_telemetry"] == "recorder_self_report_only"


def _capture_json(root: Path) -> tuple[Path, dict]:
    path = root / "runs" / "run-1" / "frame.capture.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return path, raw


@pytest.mark.parametrize("mutation", [
    lambda capture, image: capture["target"].update(hwnd=9999),
    lambda capture, image: capture["target"].update(pid=9999),
    lambda capture, image: capture["target"].update(process_path=r"C:\Other\MASS.exe"),
    lambda capture, image: capture["backend"].update(target_mode="desktop"),
    lambda capture, image: capture["frame"].update(image_sha256="bad"),
    lambda capture, image: capture.update(png=str(image.parent / "other.png")),
])
def test_gather_job_host_trace_validator_rejects_foreign_or_invalid_capture(tmp_path, mutation):
    root, trace, client, ended = _fresh_trace(tmp_path)
    meta, capture = _capture_json(root)
    mutation(capture, root / "runs" / "run-1" / "frame.png")
    meta.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(HostInputIsolationEvidenceError):
        validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                       workspace_root=root, now=ended)


def test_gather_job_host_trace_validator_rejects_stale_and_naive_now(tmp_path):
    root, trace, client, ended = _fresh_trace(tmp_path)
    with pytest.raises(HostInputIsolationEvidenceError):
        validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                       workspace_root=root, now=ended + timedelta(seconds=11))
    with pytest.raises(HostInputIsolationEvidenceError):
        validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                       workspace_root=root, now=ended.replace(tzinfo=None))


def test_gather_job_host_trace_validator_rejects_missing_capture_metadata(tmp_path):
    root, trace, client, ended = _fresh_trace(tmp_path)
    (root / "runs" / "run-1" / "frame.capture.json").unlink()
    with pytest.raises(HostInputIsolationEvidenceError):
        validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                       workspace_root=root, now=ended)


@pytest.mark.parametrize("change", [
    {"run_id": "wrong"},
    {"foreground_after_hwnd": 9999},
])
def test_gather_job_host_trace_validator_rejects_binding_and_focus_changes(tmp_path, change):
    root, trace, client, ended = _fresh_trace(tmp_path)
    raw = json.loads(trace.read_text(encoding="utf-8")); raw.update(change)
    trace.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HostInputIsolationEvidenceError):
        validate_gather_job_host_trace(trace, expected_run_id="run-1", expected_client=client,
                                       workspace_root=root, now=ended)
