import pytest

from harness.guest_isolation import GuestIsolationEvidence, GuestIsolationEvidenceError


def evidence(**overrides):
    raw = {
        "schema_version": 1,
        "evidence_id": "guest-r2-01",
        "run_id": "g-r2-01",
        "guest_id": "rok-guest-01",
        "environment": "windows_guest",
        "started_at": "2026-09-18T00:00:00+00:00",
        "ended_at": "2026-09-18T00:31:00+00:00",
        "duration_seconds": 1860,
        "capture_refreshes": 31,
        "target_binding_verified": True,
        "host_input_events_before": 4,
        "host_input_events_after": 4,
        "host_focus_changes": 0,
        "guest_input_events": 1,
        "benign_guest_action_verified": True,
        "disconnect_tested": True,
        "resize_tested": True,
        "cancel_tested": True,
        "host_fallback_used": False,
    }
    raw.update(overrides)
    return GuestIsolationEvidence.from_dict(raw)


def test_complete_guest_trace_assesses_ready():
    item = evidence()
    result = item.assess()
    assert result.ready is True
    assert result.reasons == ()
    assert item.host_input_delta == 0
    assert item.to_dict()["environment"] == "windows_guest"


def test_short_or_interfering_trace_fails_closed_with_reasons():
    item = evidence(
        duration_seconds=120,
        host_input_events_after=5,
        host_focus_changes=1,
        host_fallback_used=True,
        resize_tested=False,
    )
    result = item.assess()
    assert result.ready is False
    assert "R2 minimum duration" in " ".join(result.reasons)
    assert "host input counter changed" in " ".join(result.reasons)
    assert "host focus changed" in " ".join(result.reasons)
    assert "fallback" in " ".join(result.reasons)
    assert "resize" in " ".join(result.reasons)


def test_host_capture_or_host_environment_cannot_be_promoted():
    with pytest.raises(GuestIsolationEvidenceError):
        evidence(environment="windows_host")
    assert evidence(target_binding_verified=False).assess().ready is False


def test_missing_required_field_fails_closed():
    raw = evidence().to_dict()
    raw.pop("guest_id")
    with pytest.raises(GuestIsolationEvidenceError):
        GuestIsolationEvidence.from_dict(raw)
