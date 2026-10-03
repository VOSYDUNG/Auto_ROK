"""Caller-driven coordination of one journaled five-march GATHER job.

Each call advances at most one MissionRunner tick. The durable verification
journal, never a reservation or a completed checkpoint alone, selects the next
slot. A caller must supply a new observation for each subsequent tick.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from harness.gather_job_authority import GatherJobAuthority, GatherJobProgress
from harness.gather_job_store import GatherClientBinding, JsonGatherJobStore
from harness.gather_job_verification import (
    record_verified_gather_tick, recover_verified_gather_checkpoint,
    first_slot_queue_is_absent_or_measured_zero,
)
from harness.mission_runner import MissionRunner, MissionTickResult, gather_queue_completion_baseline
from harness.mission_runtime import MissionContext, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint


class GatherJobCoordinationError(RuntimeError):
    """The job cannot safely advance from its durable state."""


def gather_slot_run_id(job: GatherJobAuthority, sequence: int) -> str:
    if type(sequence) is not int or not 1 <= sequence <= job.max_marches:
        raise GatherJobCoordinationError("invalid GATHER job slot")
    identity = "\0".join((job.job_id, job.task_id, job.character_id, job.catalog_digest))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"gather-{digest}-march-{sequence}"


@dataclass(frozen=True)
class GatherJobPlan:
    progress: GatherJobProgress
    run_id: str | None
    sequence: int | None
    closed: bool
    closeout: tuple[dict[str, Any], ...] | None = None


@dataclass(frozen=True)
class GatherJobTick:
    plan: GatherJobPlan
    result: MissionTickResult | None
    progress: GatherJobProgress
    journaled_this_tick: bool
    error: str | None

    @property
    def closed(self) -> bool:
        return self.progress.verified_marches == 5 and self.error is None


class _FreshObservationTool:
    """Reject replay before the runner can select or emit an action."""

    def __init__(self, inner: Any, *, job: GatherJobAuthority,
                 prior_frame_ids: frozenset[str], minimum_observed_at: float | None,
                 previous_checkpoint_frame: str | None,
                 persisted_baseline: Mapping[str, Any] | None,
                 client: GatherClientBinding | None, client_provider=None) -> None:
        self.inner = inner
        self.job = job
        self.prior_frame_ids = prior_frame_ids
        self.minimum_observed_at = minimum_observed_at
        self.previous_checkpoint_frame = previous_checkpoint_frame
        self.persisted_baseline = persisted_baseline
        self.client = client
        self.client_provider = client_provider

    def observe(self, context: MissionContext) -> ToolSnapshot:
        snapshot = self.inner.observe(context)
        # The canonical capture provider binds an unused job during its first
        # observation. Read that durable binding after observation, rather than
        # retaining the pre-capture None. A prior binding still cannot change.
        if self.client is None and self.client_provider is not None:
            self.client = self.client_provider()
        if (snapshot.mission_id != self.job.mission_id or snapshot.task_id != self.job.task_id
                or not snapshot.frame_id
                or snapshot.frame_id in self.prior_frame_ids
                or snapshot.frame_id == self.previous_checkpoint_frame
                or (self.minimum_observed_at is not None and
                    (snapshot.observed_at is None or snapshot.observed_at <= self.minimum_observed_at))):
            raise GatherJobCoordinationError("GATHER job needs a fresh matching observation")
        if snapshot.facts.get("character_id") != self.job.character_id:
            raise GatherJobCoordinationError("GATHER observation character changed")
        if self.client is not None and GatherClientBinding.from_window(snapshot.facts.get("window")) != self.client:
            raise GatherJobCoordinationError("GATHER observation client changed")
        if self.expected_count == 0 and snapshot.state == "TROOP_DISPATCH_DRAWER":
            if not first_slot_queue_is_absent_or_measured_zero(snapshot, self.job, self.client):
                raise GatherJobCoordinationError("first GATHER slot has ineligible pre-March queue evidence")
            # Retain actual optional zero facts while preventing MissionRunner
            # from adopting them as a required numeric completion baseline.
            snapshot = replace(snapshot, facts=dict(snapshot.facts) | {"gather_job_first_slot_queue_optional": True})
        if self.expected_count > 0 and snapshot.state == "TROOP_DISPATCH_DRAWER":
            facts = snapshot.facts
            measured = gather_queue_completion_baseline(snapshot)
            if (type(facts.get("march_queue_used")) is not int
                    or facts["march_queue_used"] != self.expected_count
                    or type(facts.get("march_queue_capacity")) is not int
                    or facts["march_queue_capacity"] != self.job.max_marches
                    or measured is None):
                raise GatherJobCoordinationError("GATHER queue baseline diverges from verified journal")
            # CREATE_NEW_TROOP's post-observation passes through this same
            # wrapper before MissionRunner can persist its new checkpoint.
            # Carry the actual Drawer reading into that post-observation;
            # otherwise a first Drawer tick has no pre-existing baseline.
            self.persisted_baseline = measured
            snapshot = replace(snapshot, facts=dict(facts) | {"completion_baseline": self.persisted_baseline})
        if any(item.action_id == "MARCH_WITH_CURRENT_SELECTION" for item in snapshot.allowed_actions):
            baseline = snapshot.facts.get("completion_baseline") or self.persisted_baseline
            if self.expected_count == 0:
                if (snapshot.state != "NEW_TROOP_SETUP" or (
                        baseline is not None and not self._prior_initial_marker_matches(baseline, snapshot))
                        or not first_slot_queue_is_absent_or_measured_zero(snapshot, self.job, self.client)
                        or snapshot.facts.get("gather_job_id") != self.job.job_id
                        or snapshot.facts.get("new_troop_formation_ready") is not True
                        or not isinstance(snapshot.observed_at, (int, float))
                        or isinstance(snapshot.observed_at, bool)
                        or not snapshot.frame_id):
                    raise GatherJobCoordinationError("first March lacks fresh job-bound New Troop evidence")
                # This is an initial job-slot marker, not an observed queue 0/5.
                baseline = {
                    "predicate_id": "first_march_queue_appeared_at_one",
                    "counter_fact": "march_queue_used", "capacity": self.job.max_marches,
                    "source_frame_id": snapshot.frame_id,
                    "source_timestamp": snapshot.observed_at,
                    "source": "job_initial_slot_ordinal",
                    "character_id": self.job.character_id, "job_id": self.job.job_id,
                }
                snapshot = replace(snapshot, facts=dict(snapshot.facts) | {"completion_baseline": baseline})
            elif (not isinstance(baseline, Mapping) or
                    type(baseline.get("counter_value")) is not int or
                    baseline["counter_value"] != self.expected_count or
                    baseline.get("capacity") != self.job.max_marches or
                    baseline.get("character_id") != self.job.character_id or
                    baseline.get("source") not in {
                        "visible_ocr_queue_anchor", "visible_ocr_march_queue_region"
                    }):
                raise GatherJobCoordinationError("March baseline does not match durable job progress")
            else:
                snapshot = replace(snapshot, facts=dict(snapshot.facts) | {"completion_baseline": dict(baseline)})
        return snapshot

    def _prior_initial_marker_matches(self, baseline, snapshot) -> bool:
        """An earlier navigation postcheck marker carries no dispatch quota.

        Only the exact stored first-slot ordinal may be refreshed. Numeric or
        foreign baselines never become first-slot authority by being discarded.
        """
        at = baseline.get("source_timestamp") if isinstance(baseline, Mapping) else None
        return (
            isinstance(baseline, Mapping)
            and baseline.get("predicate_id") == "first_march_queue_appeared_at_one"
            and baseline.get("source") == "job_initial_slot_ordinal"
            and baseline.get("counter_fact") == "march_queue_used"
            and "counter_value" not in baseline
            and baseline.get("job_id") == self.job.job_id
            and baseline.get("character_id") == self.job.character_id
            and type(baseline.get("capacity")) is int and baseline["capacity"] == self.job.max_marches
            and self.previous_checkpoint_frame is not None
            and baseline.get("source_frame_id") == self.previous_checkpoint_frame
            and isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at)
            and isinstance(snapshot.observed_at, (int, float)) and not isinstance(snapshot.observed_at, bool)
            and math.isfinite(snapshot.observed_at) and at < snapshot.observed_at
        )

    @property
    def expected_count(self) -> int:
        return self._expected_count

    @expected_count.setter
    def expected_count(self, value: int) -> None:
        self._expected_count = value

    def execute(self, context: MissionContext, snapshot: ToolSnapshot, choice: Any) -> Any:
        return self.inner.execute(context, snapshot, choice)


class GatherJobCoordinator:
    """Use MissionRunner for transitions and the job journal for progress."""

    def __init__(self, job: GatherJobAuthority, ledger: JsonGatherJobStore,
                 checkpoints: JsonMissionStore) -> None:
        self.job = job
        self.ledger = ledger
        self.checkpoints = checkpoints

    def _context(self, sequence: int) -> MissionContext:
        return MissionContext(self.job.mission_id, self.job.task_id,
                              gather_slot_run_id(self.job, sequence))

    def plan(self) -> GatherJobPlan:
        progress = self.ledger.progress(self.job)
        if progress.revoked:
            raise GatherJobCoordinationError("GATHER job revoked")
        if progress.dispatched_marches == progress.verified_marches + 1:
            pending_context = self._context(progress.dispatched_marches)
            pending_checkpoint = self.checkpoints.load(pending_context)
            if pending_checkpoint is not None and pending_checkpoint.status is CheckpointStatus.COMPLETE:
                recovered = recover_verified_gather_checkpoint(
                    self.job, pending_context, pending_checkpoint, self.ledger,
                )
                if recovered is not None:
                    progress = recovered
        reservations = self.ledger.reservations(self.job)
        journal = self.ledger.verifications(self.job)
        if (len(reservations) != progress.dispatched_marches or
                len(journal) != progress.verified_marches or
                len(reservations) - len(journal) > 1):
            raise GatherJobCoordinationError("GATHER reservation and verification counts diverge")
        for sequence, item in enumerate(journal, 1):
            context = self._context(sequence)
            checkpoint = self.checkpoints.load(context)
            if (reservations[sequence - 1].run_id != context.run_id or
                    item["run_id"] != context.run_id or
                    item["sequence"] != sequence or
                    item["before_count"] != sequence - 1 or
                    item["after_count"] != sequence or
                    checkpoint is None or checkpoint.status is not CheckpointStatus.COMPLETE or
                    checkpoint.last_frame_id != item["after_frame_id"] or
                    checkpoint.pending_verification is not None):
                raise GatherJobCoordinationError("GATHER journal and completed checkpoint diverge")
        if progress.verified_marches == self.job.max_marches:
            if progress.dispatched_marches != self.job.max_marches:
                raise GatherJobCoordinationError("GATHER closeout lacks five reservations")
            return GatherJobPlan(progress, None, None, True, journal)
        sequence = progress.verified_marches + 1
        context = self._context(sequence)
        checkpoint = self.checkpoints.load(context)
        if progress.dispatched_marches == sequence:
            reservation = reservations[-1]
            pending = checkpoint.pending_verification if checkpoint is not None else None
            before = pending.get("before_snapshot") if isinstance(pending, dict) else None
            action = pending.get("action") if isinstance(pending, dict) else None
            feedback = pending.get("feedback") if isinstance(pending, dict) else None
            feedback_facts = feedback.get("facts") if isinstance(feedback, dict) else None
            if (reservation.run_id != context.run_id or
                    checkpoint is None or checkpoint.status is not CheckpointStatus.REOBSERVE or
                    not isinstance(before, dict) or before.get("frame_id") != reservation.frame_id or
                    not isinstance(action, dict) or action.get("action_id") != reservation.action or
                    not isinstance(feedback_facts, dict) or
                    feedback_facts.get("gather_job_id") != self.job.job_id or
                    feedback_facts.get("gather_job_dispatch_sequence") != sequence):
                raise GatherJobCoordinationError("pending reservation lacks a matching verification checkpoint")
        elif progress.dispatched_marches != progress.verified_marches:
            raise GatherJobCoordinationError("GATHER reservation sequence was skipped")
        elif checkpoint is not None and checkpoint.status is CheckpointStatus.COMPLETE:
            raise GatherJobCoordinationError("completed occurrence lacks durable job verification")
        return GatherJobPlan(progress, context.run_id, sequence, False)

    def tick(self, runner: MissionRunner) -> GatherJobTick:
        plan = self.plan()
        if plan.closed:
            return GatherJobTick(plan, None, plan.progress, False, None)
        assert plan.sequence is not None
        context = self._context(plan.sequence)
        prior = self.ledger.verifications(self.job)
        checkpoint = self.checkpoints.load(context)
        fresh = _FreshObservationTool(
            runner.tool, job=self.job,
            prior_frame_ids=frozenset(
                frame for entry in prior
                for frame in (entry["before_frame_id"], entry["after_frame_id"])
            ),
            minimum_observed_at=prior[-1]["after_observed_at"] if prior else None,
            previous_checkpoint_frame=checkpoint.last_frame_id if checkpoint else None,
            persisted_baseline=checkpoint.completion_baseline if checkpoint else None,
            client=self.ledger.client_binding(self.job),
            client_provider=lambda: self.ledger.client_binding(self.job),
        )
        fresh.expected_count = plan.progress.verified_marches
        original_tool = runner.tool
        try:
            runner.tool = fresh
            result = runner.tick(context)
        finally:
            runner.tool = original_tool
        error = None
        journaled = False
        if result.status is CheckpointStatus.COMPLETE:
            try:
                journaled = record_verified_gather_tick(self.job, context, result, self.ledger) is not None
                if not journaled:
                    raise GatherJobCoordinationError("mission COMPLETE lacks a new VERIFIED job journal entry")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
        progress = self.ledger.progress(self.job)
        if journaled and progress.verified_marches != plan.progress.verified_marches + 1:
            error = "GATHER journal did not advance exactly one slot"
        return GatherJobTick(plan, result, progress, journaled, error)


def persist_gather_job_closeout(
    job: GatherJobAuthority, plan: GatherJobPlan, evidence_root: str | Path,
) -> Path:
    """Write an idempotent close record backed by five validated journal edges."""
    if (not plan.closed or plan.progress.job_id != job.job_id or
            plan.progress.verified_marches != job.max_marches or
            plan.closeout is None or len(plan.closeout) != job.max_marches or
            [entry.get("after_count") for entry in plan.closeout] != list(range(1, job.max_marches + 1))):
        raise GatherJobCoordinationError("GATHER closeout lacks five validated transitions")
    digest = hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()
    path = Path(evidence_root) / "jobs" / f"gather-job-{digest}-closeout.json"
    payload = {
        "schema_version": 1,
        "job_id": job.job_id,
        "task_id": job.task_id,
        "character_id": job.character_id,
        "catalog_digest": job.catalog_digest,
        "verified_marches": job.max_marches,
        "transitions": list(plan.closeout),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GatherJobCoordinationError("GATHER closeout record is unreadable") from exc
        if existing != payload:
            raise GatherJobCoordinationError("GATHER closeout record differs from journal")
    return path
