"""Five real MissionRunner ticks with synthetic observation and actuation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.gather_job_authority import GatherJobAuthority
from harness.gather_job_coordinator import (
    GatherJobCoordinationError, GatherJobCoordinator, gather_slot_run_id,
    persist_gather_job_closeout, _FreshObservationTool,
)
from harness.gather_job_store import GatherClientBinding, JsonGatherJobStore
from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
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


def zero_facts(current_job, timestamp):
    return {"character_id": current_job.character_id, "window": WINDOW,
            "march_queue_used": 0, "march_queue_capacity": 5,
            "march_queue_source": "visible_ocr_queue_anchor", "image_sha256": "a" * 64,
            "captured_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat()}


class StoredSnapshotTool:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def observe(self, context):
        return self.snapshot

    def execute(self, *args):
        raise AssertionError("observation-only fixture cannot emit input")


class NumericDrawerNavigationTool:
    def __init__(self, current_job, damage=None):
        self.job = current_job
        self.actions = []
        self.observations = 0
        self.at = datetime.now(timezone.utc).timestamp()
        self.damage = damage or {}

    def observe(self, context):
        self.observations += 1
        facts = {"character_id": self.job.character_id, "window": WINDOW}
        if self.observations == 1:
            facts.update(march_queue_used=1, march_queue_capacity=5,
                         march_queue_source="visible_ocr_queue_anchor")
            facts.update(self.damage)
            return ToolSnapshot(context.mission_id, context.task_id, "numeric-drawer", "TROOP_DISPATCH_DRAWER",
                                facts=facts, observed_at=self.at,
                                allowed_actions=(AllowedAction("CREATE_NEW_TROOP", True, ("NEW_TROOP",)),),
                                target_ids=("NEW_TROOP",))
        facts.update(gather_job_id=self.job.job_id, new_troop_formation_ready=True,
                     precondition_evidence={PRECONDITION: True})
        return ToolSnapshot(context.mission_id, context.task_id, "numeric-new-troop", "NEW_TROOP_SETUP",
                            facts=facts, observed_at=self.at + 1,
                            allowed_actions=(AllowedAction(ACTION, True, ("TROOP_MARCH",)),),
                            target_ids=("TROOP_MARCH",))

    def execute(self, context, before, choice):
        assert choice.action_id == "CREATE_NEW_TROOP"
        self.actions.append(choice.action_id)
        return ToolFeedback(True, "DISPATCHED", facts={"receipt": {
            "action_id": choice.action_id, "target_id": choice.target_id,
            "before_frame_id": before.frame_id, "character_id": self.job.character_id,
            "bounded_arguments": {}, "non_interference_confirmed": True,
        }})


def numeric_navigation_wrapper(current_job, inner):
    tool = _FreshObservationTool(inner, job=current_job, prior_frame_ids=frozenset(),
                                 minimum_observed_at=None, previous_checkpoint_frame=None,
                                 persisted_baseline=None, client=GatherClientBinding.from_window(WINDOW))
    tool.expected_count = 1
    return tool


def test_numeric_drawer_baseline_reaches_new_troop_before_first_checkpoint_write(tmp_path):
    current_job = job()
    inner = NumericDrawerNavigationTool(current_job)
    wrapper = numeric_navigation_wrapper(current_job, inner)
    context = MissionContext("GATHER_RESOURCE", current_job.task_id, "numeric-navigation")
    result = MissionRunner(compiled(), wrapper, JsonMissionStore(tmp_path / "checkpoints")).tick(context)
    assert result.status is CheckpointStatus.RUNNING
    assert inner.actions == ["CREATE_NEW_TROOP"] and inner.observations == 2
    baseline = result.checkpoint.completion_baseline
    assert baseline["counter_value"] == 1
    assert baseline["source_frame_id"] == "numeric-drawer"
    assert baseline["source_timestamp"] == inner.at
    assert result.engine_result.after_snapshot.facts["completion_baseline"] == baseline
    assert baseline["source"] == "visible_ocr_queue_anchor"


@pytest.mark.parametrize("damage", [
    {"march_queue_used": 0}, {"march_queue_used": True}, {"march_queue_used": 2},
    {"march_queue_capacity": 4}, {"march_queue_capacity": 5.0},
    {"march_queue_source": "generic_ratio"}, {"march_queue_source": None},
    {"character_id": "foreign"}, {"window": WINDOW | {"pid": 9999}},
])
def test_numeric_navigation_never_carries_foreign_or_unsourced_drawer_before_input(tmp_path, damage):
    current_job = job()
    inner = NumericDrawerNavigationTool(current_job, damage)
    context = MissionContext("GATHER_RESOURCE", current_job.task_id, "numeric-negative")
    with pytest.raises(GatherJobCoordinationError):
        MissionRunner(compiled(), numeric_navigation_wrapper(current_job, inner),
                      JsonMissionStore(tmp_path / "checkpoints")).tick(context)
    assert inner.actions == []


def fresh_zero(current_job, snapshot, **changes):
    tool = _FreshObservationTool(
        StoredSnapshotTool(snapshot), job=current_job, prior_frame_ids=frozenset(),
        minimum_observed_at=None, previous_checkpoint_frame=None, persisted_baseline=None,
        client=GatherClientBinding.from_window(WINDOW), **changes)
    tool.expected_count = 0
    return tool


@pytest.mark.parametrize("measured", [False, True])
def test_first_drawer_optional_zero_never_becomes_numeric_baseline(tmp_path, measured):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    timestamp = datetime.now(timezone.utc).timestamp()
    facts = zero_facts(current_job, timestamp) if measured else {
        "character_id": current_job.character_id, "window": WINDOW}
    drawer = ToolSnapshot("GATHER_RESOURCE", current_job.task_id, "drawer-zero",
                          "TROOP_DISPATCH_DRAWER", facts=facts, observed_at=timestamp)
    waiting = coord.tick(MissionRunner(compiled(), StoredSnapshotTool(drawer), coord.checkpoints))
    assert waiting.result.checkpoint.completion_baseline is None
    assert waiting.progress.dispatched_marches == 0
    march = SyntheticMarchTool(current_job, coord.ledger, 1)
    original = march.observe

    def observe(context):
        snapshot = original(context)
        if measured and snapshot.state == "NEW_TROOP_SETUP":
            return replace(snapshot, facts=dict(snapshot.facts) | zero_facts(current_job, snapshot.observed_at))
        return snapshot

    march.observe = observe
    completed = coord.tick(MissionRunner(compiled(), march, coord.checkpoints))
    assert completed.journaled_this_tick and completed.progress.verified_marches == 1
    before = completed.result.engine_result.snapshot
    assert before.facts["completion_baseline"]["source"] == "job_initial_slot_ordinal"
    assert "counter_value" not in before.facts["completion_baseline"]
    assert ("march_queue_used" in before.facts) is measured
    assert len(march.actions) == 1


@pytest.mark.parametrize("damage", [
    {"march_queue_source": "generic_ratio"}, {"march_queue_source": None},
    {"march_queue_capacity": 4}, {"march_queue_capacity": 5.0},
    {"march_queue_used": 1}, {"march_queue_used": 0.0}, {"march_queue_used": False},
    {"march_queue_used": None}, {"captured_at": "2020-01-01T00:00:00+00:00"},
    {"image_sha256": "bad"}, {"window": WINDOW | {"pid": 9999}},
])
def test_first_drawer_invalid_zero_fails_before_input(damage):
    current_job = job()
    timestamp = datetime.now(timezone.utc).timestamp()
    context = MissionContext("GATHER_RESOURCE", current_job.task_id, "offline-slot")
    snapshot = ToolSnapshot(context.mission_id, context.task_id, "current", "TROOP_DISPATCH_DRAWER",
                            facts=zero_facts(current_job, timestamp) | damage, observed_at=timestamp)
    with pytest.raises(GatherJobCoordinationError):
        fresh_zero(current_job, snapshot).observe(context)


def test_first_drawer_sourced_zero_cannot_reuse_checkpoint_frame():
    current_job = job()
    timestamp = datetime.now(timezone.utc).timestamp()
    context = MissionContext("GATHER_RESOURCE", current_job.task_id, "offline-slot")
    snapshot = ToolSnapshot(context.mission_id, context.task_id, "stale", "TROOP_DISPATCH_DRAWER",
                            facts=zero_facts(current_job, timestamp), observed_at=timestamp)
    tool = fresh_zero(current_job, snapshot)
    tool.previous_checkpoint_frame = snapshot.frame_id
    with pytest.raises(GatherJobCoordinationError, match="fresh"):
        tool.observe(context)


def test_first_capture_binds_client_before_optional_zero_is_validated(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    assert coord.ledger.client_binding(current_job) is None
    timestamp = datetime.now(timezone.utc).timestamp()
    drawer = ToolSnapshot("GATHER_RESOURCE", current_job.task_id, "first-capture",
                          "TROOP_DISPATCH_DRAWER", facts=zero_facts(current_job, timestamp),
                          observed_at=timestamp)

    class FirstBoundCapture(StoredSnapshotTool):
        def observe(self, context):
            coord.ledger.bind_client(current_job, self.snapshot.facts["window"])
            return super().observe(context)

    result = coord.tick(MissionRunner(compiled(), FirstBoundCapture(drawer), coord.checkpoints))
    assert coord.ledger.client_binding(current_job) == GatherClientBinding.from_window(WINDOW)
    assert result.result.checkpoint.completion_baseline is None
    assert result.progress.dispatched_marches == result.progress.verified_marches == 0


def test_first_capture_bound_client_mismatch_is_refused(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    timestamp = datetime.now(timezone.utc).timestamp()
    drawer = ToolSnapshot("GATHER_RESOURCE", current_job.task_id, "first-capture",
                          "TROOP_DISPATCH_DRAWER", facts=zero_facts(current_job, timestamp),
                          observed_at=timestamp)

    class WrongBoundCapture(StoredSnapshotTool):
        def observe(self, context):
            coord.ledger.bind_client(current_job, WINDOW | {"pid": 9999})
            return self.snapshot

    with pytest.raises(GatherJobCoordinationError, match="client changed"):
        coord.tick(MissionRunner(compiled(), WrongBoundCapture(drawer), coord.checkpoints))
    assert coord.ledger.progress(current_job).dispatched_marches == 0


def test_first_navigation_pending_then_march_refreshes_ordinal_without_replay(tmp_path):
    current_job = job()
    coord = coordinator(tmp_path, current_job)
    coord.ledger.bind_client(current_job, WINDOW)
    start = datetime.now(timezone.utc).timestamp()
    observations = []
    for index, state in enumerate(("TROOP_DISPATCH_DRAWER", "UNKNOWN_STATE",
                                   "NEW_TROOP_SETUP", "NEW_TROOP_SETUP", "WORLD_MAP_VIEW")):
        facts = {"character_id": current_job.character_id, "window": WINDOW}
        allowed, targets = (), ()
        if state == "TROOP_DISPATCH_DRAWER":
            facts.update(zero_facts(current_job, start + index))
            allowed = (AllowedAction("CREATE_NEW_TROOP", True, ("NEW_TROOP",)),)
            targets = ("NEW_TROOP",)
        elif state == "NEW_TROOP_SETUP":
            facts.update(gather_job_id=current_job.job_id, new_troop_formation_ready=True,
                         precondition_evidence={PRECONDITION: True})
            allowed = (AllowedAction(ACTION, True, ("TROOP_MARCH",)),)
            targets = ("TROOP_MARCH",)
        elif state == "WORLD_MAP_VIEW":
            facts.update(march_queue_used=1, march_queue_capacity=5,
                         march_queue_source="visible_ocr_queue_anchor")
        observations.append(ToolSnapshot("GATHER_RESOURCE", current_job.task_id,
            f"navigation-{index}", state, facts=facts, allowed_actions=allowed,
            target_ids=targets, observed_at=start + index))

    class NavigationTool:
        actions = []
        snapshots = iter(observations)
        def observe(self, context): return next(self.snapshots)
        def execute(self, context, before, choice):
            self.actions.append((choice.action_id, before))
            receipt = {"action_id": choice.action_id, "target_id": choice.target_id,
                       "before_frame_id": before.frame_id, "bounded_arguments": {},
                       "character_id": current_job.character_id, "non_interference_confirmed": True}
            facts = {"gather_job_id": current_job.job_id, "receipt": receipt}
            if choice.action_id == ACTION:
                reservation = coord.ledger.reserve_dispatch(current_job, run_id=context.run_id,
                    frame_id=before.frame_id, action=choice.action_id)
                facts["gather_job_dispatch_sequence"] = reservation.sequence
            return ToolFeedback(True, "DISPATCHED", facts=facts)

    tool = NavigationTool()
    first = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
    assert first.result.status is CheckpointStatus.REOBSERVE
    second = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
    assert second.result.checkpoint.pending_verification is None
    assert second.result.checkpoint.completion_baseline["source_frame_id"] == "navigation-2"
    third = coord.tick(MissionRunner(compiled(), tool, coord.checkpoints))
    assert third.journaled_this_tick and third.progress.verified_marches == 1
    assert [action for action, _ in tool.actions] == ["CREATE_NEW_TROOP", ACTION]
    march_before = tool.actions[-1][1]
    assert march_before.facts["completion_baseline"]["source_frame_id"] == "navigation-3"
    assert march_before.facts["completion_baseline"]["source_timestamp"] == march_before.observed_at
    assert "counter_value" not in march_before.facts["completion_baseline"]
    assert third.result.checkpoint.completion_baseline["source_frame_id"] == "navigation-3"


@pytest.mark.parametrize("damage", [{"counter_value": 0}, {"job_id": "other"},
    {"source": "visible_ocr_queue_anchor"}, {"source_frame_id": "foreign"},
    {"source_timestamp": float("nan")}, {"source_timestamp": float("inf")},
    {"capacity": 5.0}, {"character_id": "other"}])
def test_invalid_persisted_first_marker_cannot_be_refreshed(damage):
    current_job = job()
    timestamp = datetime.now(timezone.utc).timestamp()
    facts = {"character_id": current_job.character_id, "window": WINDOW,
             "gather_job_id": current_job.job_id, "new_troop_formation_ready": True}
    snapshot = ToolSnapshot("GATHER_RESOURCE", current_job.task_id, "current", "NEW_TROOP_SETUP",
        facts=facts, allowed_actions=(AllowedAction(ACTION, True, ("TROOP_MARCH",)),),
        target_ids=("TROOP_MARCH",), observed_at=timestamp)
    tool = fresh_zero(current_job, snapshot)
    tool.previous_checkpoint_frame = "prior"
    tool.persisted_baseline = {"predicate_id": "first_march_queue_appeared_at_one",
        "counter_fact": "march_queue_used", "capacity": 5,
        "character_id": current_job.character_id, "job_id": current_job.job_id,
        "source": "job_initial_slot_ordinal", "source_frame_id": "prior",
        "source_timestamp": timestamp - 1} | damage
    with pytest.raises(GatherJobCoordinationError, match="first March"):
        tool.observe(MissionContext("GATHER_RESOURCE", current_job.task_id, "slot-1"))


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
