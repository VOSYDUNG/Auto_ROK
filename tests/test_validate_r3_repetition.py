from __future__ import annotations

from scripts.validate_r3_repetition import validate_manifest, validate_record


CONTRACT = {
    "mission_id": "GATHER_RESOURCE",
    "task_id": "one-character",
    "character_id": "char-direct-01",
    "required_runs": 2,
    "minimum_successes": 2,
    "required_queue_delta": 1,
    "require_live_armed": True,
    "require_occurrence_bound_approval": True,
    "require_non_interference": True,
}


def _record(run_id: str = "run-1", *, delta: int = 1) -> dict:
    return {
        "identity": {"mission_id": "GATHER_RESOURCE", "task_id": "one-character", "character_id": "char-direct-01", "run_id": run_id},
        "runtime": {
            "live_armed": True,
            "policy_approval": {"approved": True, "bound_to_occurrence": True, "mission_id": "GATHER_RESOURCE", "task_id": "one-character", "character_id": "char-direct-01", "run_id": run_id},
            "host_input_isolation": {"ready": True, "unexpected_input_events": 0},
        },
        "engine": {
            "before_facts": {"march_queue_used": 0},
            "after_facts": {"march_queue_used": delta},
            "feedback": {"code": "VERIFIED", "success": True, "facts": {"receipt": {"non_interference_confirmed": True, "character_id": "char-direct-01"}}},
        },
    }


def test_valid_record_requires_exact_queue_delta_and_occurrence() -> None:
    result = validate_record(_record(), {"run_id": "run-1", "evidence_path": "x"}, CONTRACT)
    assert result["status"] == "pass"
    assert result["queue_delta"] == 1


def test_queue_mismatch_fails_closed() -> None:
    result = validate_record(_record(delta=2), {"run_id": "run-1", "evidence_path": "x"}, CONTRACT)
    assert result["status"] == "fail"
    assert any("delta" in reason for reason in result["reasons"])


def test_completion_baseline_is_accepted_as_bound_before_counter() -> None:
    record = _record()
    record["engine"]["before_facts"] = {"completion_baseline": {"counter_value": 0}}
    result = validate_record(record, {"run_id": "run-1", "evidence_path": "x"}, CONTRACT)
    assert result["status"] == "pass"
    assert result["queue_delta"] == 1


def test_manifest_stays_blocked_until_registered_threshold_is_met() -> None:
    manifest = {"schema_version": 1, "contract": CONTRACT, "runs": []}
    report = validate_manifest(manifest)
    assert report["status"] == "blocked"
    assert report["counts"]["registered"] == 0
