from __future__ import annotations

import hashlib
import json

import pytest

from harness.host_input_isolation import HostInputIsolationEvidence, HostInputIsolationEvidenceError
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
