from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from harness.gather_job_authority import GatherJobAuthority
from harness.gather_job_store import GatherJobStoreError, JsonGatherJobStore
from harness.gather_job_verification import record_verified_gather_tick, recover_verified_gather_checkpoint
from harness.mission_engine import EngineDecision, EngineStepResult
from harness.mission_runner import MissionTickResult, _verified_transition_from_result
from harness.mission_runtime import ActionChoice, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint


NOW = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
ACTION = "MARCH_WITH_CURRENT_SELECTION"
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}


def job():
    return GatherJobAuthority(
        "job-1", "task-1", "character-1", "digest",
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=20), frozenset({ACTION}),
    )


def result_for(number, *, run_id=None):
    run = run_id or f"run-{number}"
    before_frame, after_frame = f"march-{number}", f"queue-{number}"
    baseline = {
        "predicate_id": "first_march_queue_appeared_at_one" if number == 1 else "march_queue_used_increased",
        "counter_fact": "march_queue_used", "capacity": 5,
        "source_frame_id": before_frame if number == 1 else f"queue-{number - 1}",
        "source": "job_initial_slot_ordinal" if number == 1 else "visible_ocr_march_queue_region",
        "character_id": "character-1", "source_timestamp": NOW.timestamp() + number * 3,
        **({"job_id": "job-1"} if number == 1 else {"counter_value": number - 1}),
    }
    before = ToolSnapshot(
        "GATHER_RESOURCE", "task-1", before_frame, "NEW_TROOP_SETUP",
        facts={"completion_baseline": baseline, "character_id": "character-1", "window": WINDOW},
        observed_at=NOW.timestamp() + number * 3,
    )
    after = ToolSnapshot(
        "GATHER_RESOURCE", "task-1", after_frame, "WORLD_MAP_VIEW",
        facts={"march_queue_used": number, "march_queue_capacity": 5,
               "march_queue_source": "visible_ocr_march_queue_region",
               "character_id": "character-1", "window": WINDOW},
        observed_at=NOW.timestamp() + number * 3 + 1,
    )
    choice = ActionChoice(ACTION, "TROOP_MARCH")
    feedback = ToolFeedback(True, "VERIFIED", facts={
        "gather_job_id": "job-1", "gather_job_dispatch_sequence": number,
        "receipt": {
            "action_id": ACTION, "target_id": "TROOP_MARCH",
            "before_frame_id": before_frame, "after_frame_id": after_frame,
            "character_id": "character-1", "non_interference_confirmed": True,
        },
    })
    step = EngineStepResult(EngineDecision.COMPLETE, before, choice, feedback, after)
    checkpoint = MissionCheckpoint(
        "GATHER_RESOURCE", "task-1", run, 0,
        status=CheckpointStatus.COMPLETE, last_frame_id=after_frame,
    )
    return MissionContext("GATHER_RESOURCE", "task-1", run), MissionTickResult(
        CheckpointStatus.COMPLETE, checkpoint, before, engine_result=step,
    )


def test_first_slot_rejects_numeric_zero_as_an_observed_queue_baseline(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, result = result_for(1)
    step = result.engine_result
    before = replace(step.snapshot, facts=dict(step.snapshot.facts) | {"march_queue_used": 0})
    result = replace(result, engine_result=replace(step, snapshot=before))
    with pytest.raises(GatherJobStoreError, match="inconsistent queue"):
        record_verified_gather_tick(job(), context, result, ledger)


def test_first_postcheck_must_be_one_of_five(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, result = result_for(1)
    step = result.engine_result
    after = replace(step.after_snapshot, facts=dict(step.after_snapshot.facts) | {"march_queue_used": 2})
    result = replace(result, engine_result=replace(step, after_snapshot=after))
    with pytest.raises(GatherJobStoreError, match="inconsistent queue"):
        record_verified_gather_tick(job(), context, result, ledger)


def reserve(ledger, number):
    return ledger.reserve_dispatch(
        job(), run_id=f"run-{number}", frame_id=f"march-{number}",
        action=ACTION, now=NOW,
    )


def test_five_distinct_occurrences_advance_one_slot_each_and_survive_restart(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    for number in range(1, 6):
        reserve(ledger, number)
        with pytest.raises(GatherJobStoreError):
            reserve(ledger, number + 1)
        context, result = result_for(number)
        progress = record_verified_gather_tick(job(), context, result, ledger)
        assert progress.dispatched_marches == number
        assert progress.verified_marches == number
        ledger = JsonGatherJobStore(tmp_path / "ledger")
        assert ledger.progress(job()).verified_marches == number
        assert len(ledger.verifications(job())) == number
    assert ledger.progress(job()).verified_marches == 5
    with pytest.raises(GatherJobStoreError):
        reserve(ledger, 6)


def test_complete_checkpoint_replay_and_receipt_only_do_not_mint_verification(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, result = result_for(1)
    assert record_verified_gather_tick(job(), context, replace(result, engine_result=None), ledger) is None
    assert ledger.progress(job()).verified_marches == 0
    dispatched = replace(result.engine_result.feedback, code="DISPATCHED")
    with pytest.raises(GatherJobStoreError):
        record_verified_gather_tick(
            job(), context, replace(result, engine_result=replace(result.engine_result, feedback=dispatched)), ledger,
        )
    assert ledger.progress(job()).verified_marches == 0
    record_verified_gather_tick(job(), context, result, ledger)
    assert record_verified_gather_tick(job(), context, result, ledger).verified_marches == 1
    assert len(ledger.verifications(job())) == 1


@pytest.mark.parametrize("damage", [
    "skip", "stale", "wrong_client", "wrong_character", "wrong_job",
    "wrong_run", "wrong_post_frame", "wrong_receipt", "bad_source",
])
def test_bad_verified_evidence_never_advances_journal(tmp_path, damage):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, result = result_for(1)
    step = result.engine_result
    assert step is not None and step.after_snapshot is not None and step.feedback is not None
    after, before, feedback = step.after_snapshot, step.snapshot, step.feedback
    if damage == "skip":
        after = replace(after, facts=dict(after.facts) | {"march_queue_used": 2})
    elif damage == "stale":
        after = replace(after, observed_at=before.observed_at)
    elif damage == "wrong_client":
        after = replace(after, facts=dict(after.facts) | {"window": WINDOW | {"pid": 9999}})
    elif damage == "wrong_character":
        after = replace(after, facts=dict(after.facts) | {"character_id": "other"})
    elif damage == "wrong_job":
        feedback = replace(feedback, facts=dict(feedback.facts) | {"gather_job_id": "other"})
    elif damage == "wrong_run":
        context = replace(context, run_id="run-other")
    elif damage == "wrong_post_frame":
        after = replace(after, frame_id=before.frame_id)
    elif damage == "wrong_receipt":
        receipt = dict(feedback.facts["receipt"]) | {"after_frame_id": "other"}
        feedback = replace(feedback, facts=dict(feedback.facts) | {"receipt": receipt})
    elif damage == "bad_source":
        after = replace(after, facts=dict(after.facts) | {"march_queue_source": "generic_ratio"})
    step = replace(step, after_snapshot=after, feedback=feedback)
    result = replace(result, engine_result=step,
                     checkpoint=replace(result.checkpoint, last_frame_id=after.frame_id))
    with pytest.raises(GatherJobStoreError):
        record_verified_gather_tick(job(), context, result, ledger)
    assert ledger.progress(job()).verified_marches == 0
    with pytest.raises(GatherJobStoreError):
        reserve(ledger, 2)


def test_revocation_preserves_verified_history_and_denies_pending_adoption(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, result = result_for(1)
    record_verified_gather_tick(job(), context, result, ledger)
    reserve(ledger, 2)
    ledger.revoke(job())
    context, result = result_for(2)
    with pytest.raises(GatherJobStoreError):
        record_verified_gather_tick(job(), context, result, ledger)
    progress = JsonGatherJobStore(tmp_path / "ledger").progress(job())
    assert progress.revoked and progress.dispatched_marches == 2 and progress.verified_marches == 1


def durable_checkpoint(tmp_path, number):
    context, result = result_for(number)
    proof = _verified_transition_from_result(context, result.engine_result)
    assert proof is not None
    checkpoint = replace(result.checkpoint, last_decision="complete", verified_transition=proof)
    store = JsonMissionStore(tmp_path / "checkpoints")
    store.save(checkpoint)
    restored = store.load(context)
    assert restored is not None
    return context, restored


def test_crash_after_complete_recovers_once_without_second_dispatch(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, checkpoint = durable_checkpoint(tmp_path, 1)
    assert ledger.progress(job()).verified_marches == 0
    # A new process sees the COMPLETE checkpoint and adopts its exact proof.
    restarted = JsonGatherJobStore(tmp_path / "ledger")
    progress = recover_verified_gather_checkpoint(job(), context, checkpoint, restarted)
    assert progress.verified_marches == 1
    assert recover_verified_gather_checkpoint(job(), context, checkpoint, restarted) == progress
    assert len(restarted.reservations(job())) == 1
    assert len(restarted.verifications(job())) == 1
    reserve(restarted, 2)
    assert restarted.progress(job()).dispatched_marches == 2


def test_failed_journal_write_is_recovered_from_complete_checkpoint(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, checkpoint = durable_checkpoint(tmp_path, 1)
    original = ledger.record_verified
    writes = [0]

    def fail_once(job_arg, entry):
        writes[0] += 1
        if writes[0] == 1:
            raise OSError("injected journal write failure")
        return original(job_arg, entry)

    ledger.record_verified = fail_once
    with pytest.raises(OSError, match="injected"):
        recover_verified_gather_checkpoint(job(), context, checkpoint, ledger)
    assert ledger.progress(job()).verified_marches == 0
    with pytest.raises(GatherJobStoreError):
        reserve(ledger, 2)
    restarted = JsonGatherJobStore(tmp_path / "ledger")
    assert recover_verified_gather_checkpoint(job(), context, checkpoint, restarted).verified_marches == 1
    assert len(restarted.reservations(job())) == 1


@pytest.mark.parametrize("damage", ["receipt_only", "foreign_run", "wrong_frame", "wrong_client", "changed_proof"])
def test_recovery_rejects_missing_foreign_or_conflicting_proof(tmp_path, damage):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    reserve(ledger, 1)
    context, checkpoint = durable_checkpoint(tmp_path, 1)
    proof = dict(checkpoint.verified_transition)
    if damage == "receipt_only":
        checkpoint = replace(checkpoint, verified_transition=None)
        assert recover_verified_gather_checkpoint(job(), context, checkpoint, ledger) is None
    else:
        if damage == "foreign_run":
            proof["run_id"] = "other-run"
        elif damage == "wrong_frame":
            proof["before_snapshot"] = dict(proof["before_snapshot"]) | {"frame_id": "other-frame"}
        elif damage == "wrong_client":
            after = dict(proof["after_snapshot"])
            after["facts"] = dict(after["facts"]) | {"window": WINDOW | {"pid": 9999}}
            proof["after_snapshot"] = after
        checkpoint = replace(checkpoint, verified_transition=proof)
        if damage == "changed_proof":
            assert recover_verified_gather_checkpoint(job(), context, checkpoint, ledger).verified_marches == 1
            after = dict(proof["after_snapshot"])
            after["observed_at"] += 1
            checkpoint = replace(checkpoint, verified_transition=proof | {"after_snapshot": after})
        with pytest.raises(GatherJobStoreError):
            recover_verified_gather_checkpoint(job(), context, checkpoint, ledger)
    assert ledger.progress(job()).verified_marches == (1 if damage == "changed_proof" else 0)
