"""Adopt one MissionEngine VERIFIED GATHER transition into the job journal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from harness.gather_job_authority import GatherJobAuthority, GatherJobProgress
from harness.gather_job_store import GatherClientBinding, GatherJobStoreError, JsonGatherJobStore
from harness.mission_engine import EngineDecision
from harness.mission_runner import MissionTickResult, restore_verified_transition
from harness.mission_runtime import MissionContext
from harness.mission_store import CheckpointStatus, MissionCheckpoint


_QUEUE_SOURCES = {"visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}


def record_verified_gather_tick(
    job: GatherJobAuthority, context: MissionContext, result: MissionTickResult,
    ledger: JsonGatherJobStore,
) -> GatherJobProgress | None:
    """Return new journal progress, or None when this tick verified no March.

    A bare COMPLETE replay has no engine result and cannot mint verification.
    Recovery may adopt its separate durable exact VERIFIED proof; invalid
    COMPLETE evidence raises and never promotes the job.
    """
    if result.status is not CheckpointStatus.COMPLETE:
        return None
    step = result.engine_result
    if step is None:
        return None
    feedback = step.feedback
    before, after, choice = step.snapshot, step.after_snapshot, step.choice
    if (context.mission_id != job.mission_id or context.task_id != job.task_id
            or not result.checkpoint.matches(context)
            or result.checkpoint.status is not CheckpointStatus.COMPLETE
            or step.decision is not EngineDecision.COMPLETE
            or feedback is None or feedback.success is not True or feedback.code != "VERIFIED"
            or choice is None or choice.action_id != "MARCH_WITH_CURRENT_SELECTION"
            or choice.target_id != "TROOP_MARCH" or after is None
            or not before.frame_id or not after.frame_id or before.frame_id == after.frame_id
            or result.checkpoint.last_frame_id != after.frame_id
            or before.mission_id != job.mission_id or before.task_id != job.task_id
            or after.mission_id != job.mission_id or after.task_id != job.task_id):
        raise GatherJobStoreError("mission COMPLETE lacks matching VERIFIED GATHER transition")
    baseline = before.facts.get("completion_baseline")
    receipt = feedback.facts.get("receipt")
    if not isinstance(baseline, Mapping) or not isinstance(receipt, Mapping):
        raise GatherJobStoreError("verified GATHER transition lacks baseline or receipt")
    before_count, after_count = baseline.get("counter_value"), after.facts.get("march_queue_used")
    if (baseline.get("predicate_id") != "march_queue_used_increased"
            or baseline.get("counter_fact") != "march_queue_used"
            or type(before_count) is not int or type(after_count) is not int
            or after_count != before_count + 1
            or baseline.get("capacity") != job.max_marches
            or after.facts.get("march_queue_capacity") != job.max_marches
            or baseline.get("source") not in _QUEUE_SOURCES
            or after.facts.get("march_queue_source") not in _QUEUE_SOURCES
            or baseline.get("character_id") != job.character_id
            or before.facts.get("character_id") != job.character_id
            or after.facts.get("character_id") != job.character_id
            or not isinstance(baseline.get("source_frame_id"), str)
            or not baseline["source_frame_id"]
            or baseline["source_frame_id"] == after.frame_id
            or feedback.facts.get("gather_job_id") != job.job_id
            or type(feedback.facts.get("gather_job_dispatch_sequence")) is not int
            or receipt.get("action_id") != choice.action_id
            or receipt.get("target_id") != choice.target_id
            or receipt.get("before_frame_id") != before.frame_id
            or receipt.get("after_frame_id") != after.frame_id
            or receipt.get("character_id") != job.character_id
            or receipt.get("non_interference_confirmed") is not True):
        raise GatherJobStoreError("verified GATHER transition has inconsistent queue or receipt")
    bound = ledger.require_client(job, before.facts.get("window"))
    if GatherClientBinding.from_window(after.facts.get("window")) != bound:
        raise GatherJobStoreError("verified GATHER post-frame changed client")
    entry = {
        "sequence": feedback.facts["gather_job_dispatch_sequence"],
        "job_id": job.job_id, "run_id": context.run_id,
        "before_frame_id": before.frame_id, "after_frame_id": after.frame_id,
        "baseline_frame_id": baseline["source_frame_id"],
        "before_count": before_count, "after_count": after_count,
        "capacity": job.max_marches,
        "before_source": baseline["source"], "after_source": after.facts["march_queue_source"],
        "character_id": job.character_id, "client_binding": bound.to_json(),
        "before_observed_at": before.observed_at,
        "after_observed_at": after.observed_at,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "receipt": {key: receipt[key] for key in (
            "action_id", "target_id", "before_frame_id", "after_frame_id",
            "character_id", "non_interference_confirmed",
        )},
    }
    return ledger.record_verified(job, entry)


def recover_verified_gather_checkpoint(
    job: GatherJobAuthority, context: MissionContext, checkpoint: MissionCheckpoint,
    ledger: JsonGatherJobStore,
) -> GatherJobProgress | None:
    """Adopt a durable Engine VERIFIED proof after a journal-write crash.

    A COMPLETE checkpoint without proof cannot advance the job. The caller must
    still block any pending reservation before selecting another occurrence.
    """
    if checkpoint.status is not CheckpointStatus.COMPLETE:
        return None
    if checkpoint.verified_transition is None:
        return None
    try:
        step = restore_verified_transition(checkpoint, context)
    except (ValueError, TypeError, KeyError) as exc:
        raise GatherJobStoreError("GATHER checkpoint has invalid VERIFIED proof") from exc
    return record_verified_gather_tick(
        job, context, MissionTickResult(CheckpointStatus.COMPLETE, checkpoint, step.snapshot,
                                       engine_result=step), ledger,
    )
