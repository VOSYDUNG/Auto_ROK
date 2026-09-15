from pathlib import Path

from harness.gather_replay_evidence import (
    build_gather_tick_evidence,
    load_gather_replay_records,
    save_gather_tick_evidence,
    validate_gather_replay,
)
from harness.mission_engine import EngineDecision, EngineStepResult
from harness.mission_runner import MissionTickResult
from harness.mission_runtime import ActionChoice, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, MissionCheckpoint


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-replay")


def valid_record():
    before = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "frame-before",
        "NEW_TROOP_SETUP",
        facts={
            "character_id": "char-a",
            "march_queue_used": 0,
            "march_queue_capacity": 5,
            "precondition_evidence_source": "explicit_operator_configuration",
        },
    )
    after = ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        "frame-after",
        "WORLD_MAP_VIEW",
        facts={
            "character_id": "char-a",
            "march_queue_used": 1,
            "march_queue_capacity": 5,
        },
    )
    choice = ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH")
    feedback = ToolFeedback(
        True,
        "VERIFIED",
        facts={
            "receipt": {
                "action_id": choice.action_id,
                "target_id": choice.target_id,
                "before_frame_id": "frame-before",
                "after_frame_id": "frame-after",
                "bounded_arguments": {},
                "non_interference_confirmed": True,
                "character_id": "char-a",
            }
        },
        completed=False,
        reobserve_required=False,
    )
    step = EngineStepResult(
        EngineDecision.COMPLETE,
        before,
        choice,
        feedback,
        after,
    )
    checkpoint = MissionCheckpoint(
        mission_id="GATHER_RESOURCE",
        task_id="one-character",
        run_id="run-replay",
        attempt=0,
        parameters={"resource_type": "WOOD", "resource_level": 6},
        status=CheckpointStatus.COMPLETE,
        revision=8,
        last_frame_id="frame-after",
        last_state="WORLD_MAP_VIEW",
        last_decision="complete",
        updated_at="2026-09-15T00:00:00+00:00",
    )
    result = MissionTickResult(
        CheckpointStatus.COMPLETE,
        checkpoint,
        snapshot=before,
        engine_result=step,
    )
    return build_gather_tick_evidence(
        context=CONTEXT,
        character_id="char-a",
        result=result,
        live_armed=True,
        policy_approval={
            "approval_id": "approval-1",
            "bound_to_occurrence": True,
            "approved": True,
        },
        main_view_profile_trained=True,
        resource_level_profile_trained=True,
    )


def test_valid_completion_replay_requires_verified_fresh_queue_increase():
    record = valid_record()
    report = validate_gather_replay([record])
    assert report["status"] == "PASS"
    assert report["completion_records"] == 1
    assert report["errors"] == []


def test_dispatch_is_not_accepted_as_live_completion():
    record = valid_record()
    record["engine"]["feedback"]["code"] = "DISPATCHED"
    report = validate_gather_replay([record])
    assert report["status"] == "FAIL"
    assert any("VERIFIED" in item for item in report["errors"])


def test_stale_frame_or_no_queue_increase_is_rejected():
    stale = valid_record()
    stale["engine"]["after_frame_id"] = stale["engine"]["before_frame_id"]
    stale["engine"]["feedback"]["facts"]["receipt"]["after_frame_id"] = stale["engine"]["before_frame_id"]
    report = validate_gather_replay([stale])
    assert any("not fresh" in item for item in report["errors"])

    no_increase = valid_record()
    no_increase["engine"]["after_facts"]["march_queue_used"] = 0
    report = validate_gather_replay([no_increase])
    assert any("did not increase" in item for item in report["errors"])


def test_live_profiles_policy_and_receipt_identity_are_required():
    record = valid_record()
    record["runtime"]["live_armed"] = False
    record["runtime"]["main_view_profile_trained"] = False
    record["runtime"]["resource_level_profile_trained"] = False
    record["runtime"]["policy_approval"] = {}
    record["engine"]["feedback"]["facts"]["receipt"]["character_id"] = "other-char"
    report = validate_gather_replay([record])
    assert report["status"] == "FAIL"
    joined = " | ".join(report["errors"])
    assert "live input armed" in joined
    assert "main-view" in joined
    assert "resource-level" in joined
    assert "troop selection approval" in joined
    assert "receipt character_id" in joined


def test_mixed_occurrence_evidence_is_rejected():
    a = valid_record()
    b = valid_record()
    b["identity"]["run_id"] = "different-run"
    report = validate_gather_replay([a, b])
    assert report["status"] == "FAIL"
    assert any("more than one" in item for item in report["errors"])


def test_tick_evidence_persistence_is_append_only_per_invocation(tmp_path: Path):
    record = valid_record()
    first = save_gather_tick_evidence(tmp_path, record)
    second = save_gather_tick_evidence(tmp_path, record)
    assert first != second
    assert first.exists() and second.exists()
    loaded = load_gather_replay_records(first.parent)
    assert len(loaded) == 2
    assert all(item["identity"]["run_id"] == "run-replay" for item in loaded)
