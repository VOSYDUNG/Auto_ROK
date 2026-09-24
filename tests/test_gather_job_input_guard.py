from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from harness.action_surface import SemanticActionSurface
from harness.contracts import BoundingBox
from harness.gather_job_authority import GatherCatalogIdentity, GatherJobAuthority
from harness.gather_job_store import JsonGatherJobStore
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolSnapshot
from harness.mission_tool import HumanInterfaceActionProvider, InterferenceCheck
from harness.scene_graph import SceneGraph, VisualTarget
from harness.troop_policy import TROOP_SELECTION_PRECONDITION
from harness.windows_interference_guard import GatherJobInputGuard


NOW = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
ACTION = "MARCH_WITH_CURRENT_SELECTION"
CONTEXT = MissionContext("GATHER_RESOURCE", "task-1", "run-1")
CATALOG = GatherCatalogIdentity("compiled-digest", frozenset({ACTION}))
WINDOW = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}


def job():
    return GatherJobAuthority(
        "job-1", "task-1", "character-1", CATALOG.digest,
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=20),
        frozenset({ACTION}),
    )


def current_frame(frame_id="frame-1", **fact_overrides):
    facts = {
        "character_id": "character-1",
        "gather_job_id": "job-1",
        "precondition_evidence_source": "bounded_gather_job",
        "precondition_evidence": {TROOP_SELECTION_PRECONDITION: True},
        "new_troop_formation_ready": True,
        "window": WINDOW,
        "gather_client_binding_source": "same_frame_capture_target_and_post_capture",
        "completion_baseline": {
            "predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used",
            "counter_value": 0, "capacity": 5, "source_frame_id": "queue-zero",
            "source_timestamp": NOW.timestamp() - 1,
            "source": "visible_ocr_queue_anchor", "character_id": "character-1",
        },
    }
    facts.update(fact_overrides)
    target = VisualTarget(
        "TROOP_MARCH", frame_id, "MARCH", BoundingBox(10, 20, 50, 60),
        1.0, "test",
    )
    scene = SceneGraph(frame_id, None, (target,), facts)
    before = ToolSnapshot(
        "GATHER_RESOURCE", "task-1", frame_id, "NEW_TROOP_SETUP",
        facts=facts,
        allowed_actions=(AllowedAction(ACTION, True, ("TROOP_MARCH",)),),
        target_ids=("TROOP_MARCH",), observed_at=NOW.timestamp() - 1,
    )
    return before, scene


class HostGuard:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def check(self, context, before, choice, scene, resolved):
        return InterferenceCheck(self.allowed, "HOST_OK" if self.allowed else "HOST_DENIED")


class ChangingHostGuard:
    def __init__(self):
        self.calls = 0

    def check(self, context, before, choice, scene, resolved):
        self.calls += 1
        return InterferenceCheck(self.calls == 1, "HOST_OK" if self.calls == 1 else "HOST_CHANGED")


class Recorder:
    def __init__(self):
        self.actions = []

    def perform(self, action):
        self.actions.append(action)


def provider(tmp_path, *, authority=None, host=None):
    authority = authority or job()
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(authority, WINDOW)
    guard = GatherJobInputGuard(
        host or HostGuard(), authority, ledger, CATALOG, clock=lambda: NOW,
    )
    recorder = Recorder()
    return HumanInterfaceActionProvider(SemanticActionSurface(), recorder, guard), ledger, recorder


def dispatch(action_provider, before, scene, context=CONTEXT):
    return action_provider.dispatch(
        context, before, ActionChoice(ACTION, "TROOP_MARCH"), scene,
    )


def test_reserved_march_reaches_input_once_and_duplicate_run_is_denied(tmp_path):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    first = dispatch(action_provider, before, scene)
    assert first.dispatched is True
    assert first.facts["gather_job_dispatch_sequence"] == 1
    assert len(recorder.actions) == 1
    assert ledger.progress(job()).dispatched_marches == 1

    next_before, next_scene = current_frame("frame-2")
    second = dispatch(action_provider, next_before, next_scene)
    assert second.dispatched is False
    assert second.code == "GATHER_JOB_PREVIOUS_MARCH_UNVERIFIED"
    assert len(recorder.actions) == 1
    assert ledger.progress(job()).dispatched_marches == 1


def test_next_run_requires_verified_count_and_matching_fresh_baseline(tmp_path):
    action_provider, ledger, recorder = provider(tmp_path)
    first_before, first_scene = current_frame()
    assert dispatch(action_provider, first_before, first_scene).dispatched is True
    entry = {
        "sequence": 1, "job_id": "job-1", "run_id": "run-1",
        "before_frame_id": "frame-1", "after_frame_id": "queue-1",
        "baseline_frame_id": "queue-zero", "before_count": 0, "after_count": 1,
        "capacity": 5, "before_source": "visible_ocr_queue_anchor",
        "after_source": "visible_ocr_march_queue_region", "character_id": "character-1",
        "client_binding": ledger.client_binding(job()).to_json(),
        "before_observed_at": NOW.timestamp() - 1,
        "after_observed_at": NOW.timestamp(), "verified_at": NOW.isoformat(),
        "receipt": {
            "action_id": ACTION, "target_id": "TROOP_MARCH",
            "before_frame_id": "frame-1", "after_frame_id": "queue-1",
            "character_id": "character-1", "non_interference_confirmed": True,
        },
    }
    ledger.record_verified(job(), entry)
    next_before, next_scene = current_frame("frame-2")
    assert dispatch(action_provider, next_before, next_scene,
                    replace(CONTEXT, run_id="run-2")).code == "GATHER_JOB_QUEUE_BASELINE_INVALID"
    next_baseline = dict(next_before.facts["completion_baseline"]) | {
        "counter_value": 1, "source_frame_id": "queue-1",
    }
    facts = dict(next_scene.facts) | {"completion_baseline": next_baseline}
    next_before = replace(next_before, facts=facts)
    next_scene = replace(next_scene, facts=facts)
    receipt = dispatch(action_provider, next_before, next_scene,
                       replace(CONTEXT, run_id="run-2"))
    assert receipt.dispatched is True
    assert receipt.facts["gather_job_dispatch_sequence"] == 2
    assert len(recorder.actions) == 2
    assert ledger.progress(job()).dispatched_marches == 2
    assert ledger.progress(job()).verified_marches == 1

@pytest.mark.parametrize("change,expected", [
    ({"observed_at": NOW.timestamp() - 30}, "GATHER_JOB_SCOPE_OR_FRAME_MISMATCH"),
    ({"state": "CITY_VIEW"}, "GATHER_JOB_NEW_TROOP_NOT_READY"),
    ({"character_id": "other-character"}, "GATHER_JOB_SCOPE_OR_FRAME_MISMATCH"),
    ({"new_troop_formation_ready": False}, "GATHER_JOB_NEW_TROOP_NOT_READY"),
    ({"gather_job_id": "other-job"}, "GATHER_JOB_NEW_TROOP_NOT_READY"),
])
def test_wrong_or_stale_scope_denies_before_actuator(tmp_path, change, expected):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    if "observed_at" in change or "state" in change:
        before = replace(before, **change)
    else:
        facts = dict(before.facts) | change
        before = replace(before, facts=facts)
        scene = replace(scene, facts=facts)
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == expected
    assert receipt.dispatched is False
    assert recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 0


def test_expired_revoked_and_host_denied_never_emit_input(tmp_path):
    before, scene = current_frame()
    expired, expired_ledger, expired_recorder = provider(
        tmp_path / "expired", authority=replace(job(), expires_at=NOW),
    )
    assert dispatch(expired, before, scene).code == "GATHER_JOB_ACTION_NOT_AUTHORIZED"
    assert expired_recorder.actions == []
    assert expired_ledger.progress(replace(job(), expires_at=NOW)).dispatched_marches == 0

    revoked, ledger, revoked_recorder = provider(tmp_path / "revoked")
    ledger.revoke(job())
    assert dispatch(revoked, before, scene).code == "GATHER_JOB_STOPPED_OR_FULL"
    assert revoked_recorder.actions == []

    denied, ledger, denied_recorder = provider(tmp_path / "host", host=HostGuard(False))
    assert dispatch(denied, before, scene).code == "HOST_DENIED"
    assert denied_recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 0


def test_host_change_after_durable_reservation_keeps_slot_but_emits_no_input(tmp_path):
    host = ChangingHostGuard()
    action_provider, ledger, recorder = provider(tmp_path, host=host)
    before, scene = current_frame()
    receipt = dispatch(action_provider, before, scene)
    assert host.calls == 2
    assert receipt.dispatched is False
    assert receipt.code == "GATHER_JOB_HOST_CHANGED_AFTER_LEDGER"
    assert receipt.facts["gather_job_dispatch_sequence"] == 1
    assert ledger.progress(job()).dispatched_marches == 1
    assert recorder.actions == []


@pytest.mark.parametrize("change", [
    {"hwnd": 1002}, {"pid": 2002}, {"process_path": r"C:\Other\MASS.exe"},
])
def test_client_replacement_at_input_boundary_denies_without_reservation(tmp_path, change):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    facts = dict(scene.facts)
    facts["window"] = WINDOW | change
    before = replace(before, facts=facts)
    scene = replace(scene, facts=facts)
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == "GATHER_JOB_CLIENT_BINDING_CHANGED"
    assert recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 0


def test_missing_client_identity_at_input_boundary_denies(tmp_path):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    facts = dict(scene.facts)
    facts.pop("window")
    before = replace(before, facts=facts)
    scene = replace(scene, facts=facts)
    assert dispatch(action_provider, before, scene).code == "GATHER_JOB_CLIENT_BINDING_CHANGED"
    assert recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 0


def test_revoke_after_march_reservation_denies_input_and_keeps_slot(tmp_path):
    action_provider, ledger, recorder = provider(tmp_path)
    reserve = ledger.reserve_dispatch

    def reserve_then_revoke(*args, **kwargs):
        entry = reserve(*args, **kwargs)
        ledger.revoke(job())
        return entry

    ledger.reserve_dispatch = reserve_then_revoke
    before, scene = current_frame()
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == "GATHER_JOB_STOPPED_OR_FULL"
    assert receipt.dispatched is False
    assert receipt.facts["gather_job_dispatch_sequence"] == 1
    assert recorder.actions == []
    assert ledger.progress(job()).revoked is True
    assert ledger.progress(job()).dispatched_marches == 1


def test_scope_action_revoke_during_final_host_check_denies_input(tmp_path):
    scope_action = "CREATE_NEW_TROOP"
    authority = replace(job(), allowed_actions=frozenset({ACTION, scope_action}))
    catalog = GatherCatalogIdentity(CATALOG.digest, authority.allowed_actions)
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(authority, WINDOW)

    class RevokingHostGuard:
        calls = 0

        def check(self, context, before, choice, scene, resolved):
            self.calls += 1
            if self.calls == 2:
                ledger.revoke(authority)
            return InterferenceCheck(True, "HOST_OK")

    host = RevokingHostGuard()
    recorder = Recorder()
    guard = GatherJobInputGuard(host, authority, ledger, catalog, clock=lambda: NOW)
    action_provider = HumanInterfaceActionProvider(SemanticActionSurface(), recorder, guard)
    before, scene = current_frame()
    before = replace(before, allowed_actions=before.allowed_actions + (
        AllowedAction(scope_action, True, ("TROOP_MARCH",)),
    ))
    receipt = action_provider.dispatch(
        CONTEXT, before, ActionChoice(scope_action, "TROOP_MARCH"), scene,
    )
    assert host.calls == 2
    assert receipt.code == "GATHER_JOB_STOPPED_OR_FULL"
    assert receipt.dispatched is False
    assert recorder.actions == []
    assert ledger.progress(authority).revoked is True
    assert ledger.progress(authority).dispatched_marches == 0


@pytest.mark.parametrize("slow_step,elapsed", [
    ("ledger", timedelta(seconds=20)),
    ("ledger", timedelta(minutes=21)),
    ("host", timedelta(seconds=20)),
    ("host", timedelta(minutes=21)),
])
def test_final_work_cannot_outlive_frame_or_job(tmp_path, slow_step, elapsed):
    authority = job()
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(authority, WINDOW)
    current = [NOW]

    class SlowHostGuard:
        calls = 0

        def check(self, context, before, choice, scene, resolved):
            self.calls += 1
            if slow_step == "host" and self.calls == 2:
                current[0] = NOW + elapsed
            return InterferenceCheck(True, "HOST_OK")

    if slow_step == "ledger":
        require_client = ledger.require_client
        calls = [0]

        def slow_client_check(*args, **kwargs):
            calls[0] += 1
            result = require_client(*args, **kwargs)
            if calls[0] == 2:
                current[0] = NOW + elapsed
            return result

        ledger.require_client = slow_client_check
    recorder = Recorder()
    guard = GatherJobInputGuard(
        SlowHostGuard(), authority, ledger, CATALOG, clock=lambda: current[0],
    )
    action_provider = HumanInterfaceActionProvider(SemanticActionSurface(), recorder, guard)
    before, scene = current_frame()
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == "GATHER_JOB_STALE_AFTER_LEDGER"
    assert receipt.dispatched is False
    assert receipt.facts["gather_job_dispatch_sequence"] == 1
    assert recorder.actions == []
    assert ledger.progress(authority).dispatched_marches == 1


@pytest.mark.parametrize("source_timestamp", [None, NOW.timestamp() - 30, NOW.timestamp() + 1, "invalid"])
def test_missing_old_or_invalid_queue_baseline_denies_before_input(tmp_path, source_timestamp):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    baseline = dict(before.facts["completion_baseline"])
    if source_timestamp is None:
        baseline.pop("source_timestamp")
    else:
        baseline["source_timestamp"] = source_timestamp
    facts = dict(before.facts) | {"completion_baseline": baseline}
    before, scene = replace(before, facts=facts), replace(scene, facts=facts)
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == "GATHER_JOB_QUEUE_BASELINE_INVALID"
    assert recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 0


def test_queue_baseline_expiring_during_final_ledger_check_keeps_reservation(tmp_path):
    action_provider, ledger, recorder = provider(tmp_path)
    before, scene = current_frame()
    # Keep the current frame fresh at final check but make its source queue
    # frame cross the age boundary while the ledger operation runs.
    baseline = dict(before.facts["completion_baseline"]) | {
        "source_timestamp": NOW.timestamp() - 9,
    }
    facts = dict(before.facts) | {"completion_baseline": baseline}
    before, scene = replace(before, facts=facts), replace(scene, facts=facts)
    clock = [NOW]
    guard = action_provider.guard
    guard.clock = lambda: clock[0]
    original = ledger.require_client
    calls = [0]

    def slow_client_check(*args, **kwargs):
        calls[0] += 1
        result = original(*args, **kwargs)
        if calls[0] == 2:
            clock[0] = NOW + timedelta(seconds=2)
        return result

    ledger.require_client = slow_client_check
    receipt = dispatch(action_provider, before, scene)
    assert receipt.code == "GATHER_JOB_QUEUE_BASELINE_STALE_AFTER_LEDGER"
    assert receipt.facts["gather_job_dispatch_sequence"] == 1
    assert recorder.actions == []
    assert ledger.progress(job()).dispatched_marches == 1
