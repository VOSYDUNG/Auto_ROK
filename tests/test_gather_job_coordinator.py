"""Five real MissionRunner ticks with synthetic observation and actuation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.gather_job_authority import GatherJobAuthority
from harness.gather_job_coordinator import (
    GatherJobCoordinationError, GatherJobCoordinator, gather_slot_run_id,
    persist_gather_job_closeout,
)
from harness.gather_job_store import JsonGatherJobStore
from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore


ROOT = Path(__file__).resolve().parents[1]
ACTION = "MARCH_WITH_CURRENT_SELECTION"
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}
PRECONDITION = "troop/commander selection policy is valid for this mission"


def job() -> GatherJobAuthority:
    now = datetime.now(timezone.utc)
    return GatherJobAuthority(
        "synthetic-five", "task-five", "character-five", "digest-five",
        now - timedelta(minutes=1), now + timedelta(minutes=20), frozenset({ACTION}),
    )


def compiled():
    return compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )


class SyntheticMarchTool:
    """A bounded capture/actuator substitute; MissionRunner still owns decisions."""

    def __init__(self, job, ledger, sequence, *, frame_prefix="frame", after_count=None):
        self.job, self.ledger, self.sequence = job, ledger, sequence
        self.frame_prefix, self.after_count = frame_prefix, after_count
        self.observations = 0
        self.actions = []
        self.start = datetime.now(timezone.utc).timestamp() + sequence * 3

    def observe(self, context):
        self.observations += 1
        if self.observations == 1:
            frame = f"{self.frame_prefix}-march-{self.sequence}"
            facts = {"character_id": self.job.character_id,
                     "window": WINDOW, "precondition_evidence": {PRECONDITION: True},
                     "gather_job_id": self.job.job_id,
                     "new_troop_formation_ready": True}
            if self.sequence > 1:
                facts["completion_baseline"] = {
                    "predicate_id": "march_queue_used_increased",
                    "counter_fact": "march_queue_used", "counter_value": self.sequence - 1,
                    "capacity": 5, "source_frame_id": f"{self.frame_prefix}-baseline-{self.sequence}",
                    "source": "visible_ocr_queue_anchor", "character_id": self.job.character_id,
                    "source_timestamp": self.start,
                }
            return ToolSnapshot(
                context.mission_id, context.task_id, frame, "NEW_TROOP_SETUP",
                facts=facts,
                allowed_actions=(AllowedAction(ACTION, True, ("TROOP_MARCH",)),),
                target_ids=("TROOP_MARCH",), observed_at=self.start,
            )
        if self.observations == 2:
            return ToolSnapshot(
                context.mission_id, context.task_id,
                f"{self.frame_prefix}-queue-{self.sequence}", "WORLD_MAP_VIEW",
                facts={"march_queue_used": self.after_count if self.after_count is not None else self.sequence,
                       "march_queue_capacity": 5,
                       "march_queue_source": "visible_ocr_queue_anchor",
                       "character_id": self.job.character_id, "window": WINDOW},
                observed_at=self.start + 1,
            )
        raise AssertionError("caller must not spin on observations")

    def execute(self, context, before, choice):
        reservation = self.ledger.reserve_dispatch(
            self.job, run_id=context.run_id, frame_id=before.frame_id, action=choice.action_id,
        )
        self.actions.append((context.run_id, choice.action_id))
        return ToolFeedback(True, "DISPATCHED", facts={
            "gather_job_id": self.job.job_id,
            "gather_job_dispatch_sequence": reservation.sequence,
            "receipt": {
                "action_id": choice.action_id, "target_id": choice.target_id,
                "before_frame_id": before.frame_id,
                "bounded_arguments": dict(choice.arguments),
                "character_id": self.job.character_id,
                "non_interference_confirmed": True,
            },
        })


def coordinator(tmp_path, current_job):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    checkpoints = JsonMissionStore(tmp_path / "checkpoints")
    return GatherJobCoordinator(current_job, ledger, checkpoints)


def test_five_marches_run_through_real_runner_and_close_only_from_journal(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    for sequence in range(1, 6):
        plan = coord.plan()
        assert plan.sequence == sequence
        assert plan.run_id == gather_slot_run_id(current_job, sequence)
        tool = SyntheticMarchTool(current_job, coord.ledger, sequence)
        result = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
        assert result.result.status is CheckpointStatus.COMPLETE
        assert result.journaled_this_tick and result.error is None
        assert result.progress.verified_marches == sequence
        assert result.progress.dispatched_marches == sequence
        assert len(tool.actions) == 1
        coord = coordinator(tmp_path, current_job)  # process restart retains the slot
    closed = coord.plan()
    assert closed.closed and closed.run_id is None
    assert [item["after_count"] for item in closed.closeout] == [1, 2, 3, 4, 5]
    closeout = persist_gather_job_closeout(current_job, closed, tmp_path / "evidence")
    assert closeout.is_file()
    assert persist_gather_job_closeout(current_job, coord.plan(), tmp_path / "evidence") == closeout
    assert coord.tick(MissionRunner(compiled(), object(), coord.checkpoints)).result is None


def test_pending_reservation_without_matching_checkpoint_blocks_next_input(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    coord.ledger.reserve_dispatch(
        current_job, run_id=gather_slot_run_id(current_job, 1),
        frame_id="orphan", action=ACTION,
    )
    with pytest.raises(GatherJobCoordinationError, match="pending reservation"):
        coord.plan()


def test_complete_checkpoint_recovers_verified_proof_after_journal_write_failure(tmp_path, monkeypatch):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)

    def fail_once(*args, **kwargs):
        raise OSError("synthetic journal interruption")

    monkeypatch.setattr(coord.ledger, "record_verified", fail_once)
    tool = SyntheticMarchTool(current_job, coord.ledger, 1)
    interrupted = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
    assert interrupted.result.status is CheckpointStatus.COMPLETE
    assert interrupted.progress.verified_marches == 0
    assert interrupted.error is not None
    assert len(tool.actions) == 1
    restarted = coordinator(tmp_path, current_job)
    assert restarted.plan().sequence == 2
    assert restarted.ledger.progress(current_job).verified_marches == 1


def test_ambiguous_postcheck_does_not_advance_and_replay_does_not_dispatch_again(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    tool = SyntheticMarchTool(current_job, coord.ledger, 1, after_count=3)
    first = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
    assert first.result.status is CheckpointStatus.REOBSERVE
    assert first.error is None
    assert first.progress.verified_marches == 0
    assert len(tool.actions) == 1
    pending = coord.plan()
    assert pending.sequence == 1 and pending.progress.verified_marches == 0
    assert len(tool.actions) == 1


def test_replayed_prior_frame_is_rejected_before_another_dispatch(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    first = SyntheticMarchTool(current_job, coord.ledger, 1)
    assert coord.tick(MissionRunner(compiled(), first, coord.checkpoints)).progress.verified_marches == 1
    duplicate = SyntheticMarchTool(current_job, coord.ledger, 2)
    original_observe = duplicate.observe

    def replay(context):
        snapshot = original_observe(context)
        return replace(snapshot, frame_id="frame-queue-1")

    duplicate.observe = replay
    with pytest.raises(GatherJobCoordinationError, match="fresh"):
        coord.tick(MissionRunner(compiled(), duplicate, coord.checkpoints))
    assert duplicate.actions == []


def test_revocation_stops_before_observation(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.revoke(current_job)
    with pytest.raises(GatherJobCoordinationError, match="revoked"):
        coord.plan()
