from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

import pytest

from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner, _reversible_navigation_recovery_reason
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-runner")


def compiled(level=6):
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": level},
    )


class FakeTool:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.executions = []

    def observe(self, context):
        return next(self.snapshots)

    def execute(self, context, before, choice):
        self.executions.append(choice)
        return ToolFeedback(
            True,
            "VERIFIED",
            facts={
                "receipt": {
                    "before_frame_id": before.frame_id,
                    "after_frame_id": "legacy",
                    "action_id": choice.action_id,
                    "target_id": choice.target_id,
                    "non_interference_confirmed": True,
                }
            },
        )


def snapshot(frame, state, *, actions=(), targets=(), facts=None, observed_at=None):
    return ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        frame,
        state,
        facts=facts or {},
        allowed_actions=actions,
        target_ids=targets,
        observed_at=observed_at,
    )


def test_runner_auto_executes_single_action_and_persists_checkpoint(tmp_path):
    tool = FakeTool((
        snapshot("f1", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),)),
        snapshot("f2", "WORLD_MAP_VIEW"),
    ))
    runner = MissionRunner(compiled(), tool, JsonMissionStore(tmp_path))
    result = runner.tick(CONTEXT)

    assert result.status is CheckpointStatus.RUNNING
    assert [item.action_id for item in tool.executions] == ["TOGGLE_CITY_MAP"]
    stored = JsonMissionStore(tmp_path).load(CONTEXT)
    assert stored.last_frame_id == "f2"
    assert stored.last_state == "WORLD_MAP_VIEW"
    assert stored.revision == 1


def test_runner_restores_verified_self_loop_then_stops_at_untrained_level_handler(tmp_path):
    store = JsonMissionStore(tmp_path)
    actions = (
        AllowedAction("SELECT_RESOURCE_TYPE", True, ("SEARCH_CATEGORY_WOOD",)),
        AllowedAction("SET_RESOURCE_LEVEL", True, ("SEARCH_LEVEL_CONTROL",), {"resource_level": 6}),
        AllowedAction("SEARCH_RESOURCE_NODE", True, ("SEARCH_EXECUTE",)),
    )
    targets = ("SEARCH_CATEGORY_WOOD", "SEARCH_LEVEL_CONTROL", "SEARCH_EXECUTE")

    first_tool = FakeTool((
        snapshot("f1", "RESOURCE_SEARCH_PANEL", actions=actions, targets=targets),
        snapshot("f2", "RESOURCE_SEARCH_PANEL"),
    ))
    first = MissionRunner(compiled(), first_tool, store).tick(CONTEXT)
    assert first.status is CheckpointStatus.RUNNING
    assert first_tool.executions[0].action_id == "SELECT_RESOURCE_TYPE"
    assert first.checkpoint.verified_self_loops

    second_tool = FakeTool((
        snapshot("f3", "RESOURCE_SEARCH_PANEL", actions=actions, targets=targets),
    ))
    second = MissionRunner(compiled(), second_tool, store).tick(CONTEXT)
    assert second.status is CheckpointStatus.NEEDS_DECISION
    assert second_tool.executions == []
    assert "typed handler" in second.reason
    assert second.checkpoint.revision == 2


def test_runner_without_requested_level_advances_from_type_setup_to_search(tmp_path):
    context = MissionContext("GATHER_RESOURCE", "one-character", "run-no-level")
    store = JsonMissionStore(tmp_path)
    actions = (
        AllowedAction("SELECT_RESOURCE_TYPE", True, ("SEARCH_CATEGORY_WOOD",)),
        AllowedAction("SEARCH_RESOURCE_NODE", True, ("SEARCH_EXECUTE",)),
    )
    targets = ("SEARCH_CATEGORY_WOOD", "SEARCH_EXECUTE")

    first_tool = FakeTool((
        snapshot("f1", "RESOURCE_SEARCH_PANEL", actions=actions, targets=targets),
        snapshot("f2", "RESOURCE_SEARCH_PANEL"),
    ))
    first = MissionRunner(compiled(None), first_tool, store).tick(context)
    assert first.status is CheckpointStatus.RUNNING
    assert first_tool.executions[0].action_id == "SELECT_RESOURCE_TYPE"

    second_tool = FakeTool((
        snapshot("f3", "RESOURCE_SEARCH_PANEL", actions=actions, targets=targets),
        snapshot("f4", "RESOURCE_POINT_DETAIL"),
    ))
    second = MissionRunner(compiled(None), second_tool, store).tick(context)
    assert second.status is CheckpointStatus.RUNNING
    assert second_tool.executions[0].action_id == "SEARCH_RESOURCE_NODE"


def test_runner_blocks_final_march_for_missing_gameplay_precondition(tmp_path):
    tool = FakeTool((
        snapshot(
            "f1",
            "NEW_TROOP_SETUP",
            actions=(AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",)),),
            targets=("TROOP_MARCH",),
            facts={"march_queue_used": 0, "character_id": "hien"},
        ),
    ))
    result = MissionRunner(compiled(), tool, JsonMissionStore(tmp_path)).tick(CONTEXT)
    assert result.status is CheckpointStatus.NEEDS_DECISION
    assert tool.executions == []
    assert "precondition evidence missing" in result.reason


def test_runner_persists_gather_completion_baseline_from_queue_observation(tmp_path):
    context = MissionContext("GATHER_RESOURCE", "one-character", "run-baseline")
    tool = FakeTool((
        snapshot(
            "f1",
            "TROOP_DISPATCH_DRAWER",
            actions=(AllowedAction("CREATE_NEW_TROOP", True, ("NEW_TROOP",)),),
            targets=("NEW_TROOP",),
            facts={
                "march_queue_used": 0,
                "march_queue_capacity": 5,
                "march_queue_source": "visible_ocr_queue_anchor",
                "character_id": "char-a",
            },
            observed_at=100.0,
        ),
        snapshot("f2", "NEW_TROOP_SETUP"),
    ))

    result = MissionRunner(compiled(), tool, JsonMissionStore(tmp_path)).tick(context)

    assert result.status is CheckpointStatus.RUNNING
    stored = JsonMissionStore(tmp_path).load(context)
    assert stored is not None
    assert stored.completion_baseline == {
        "predicate_id": "march_queue_used_increased",
        "counter_fact": "march_queue_used",
        "counter_value": 0,
        "capacity": 5,
        "source_frame_id": "f1",
        "source_timestamp": 100.0,
        "source": "visible_ocr_queue_anchor",
        "character_id": "char-a",
    }


def test_runner_resumes_delayed_completion_without_second_dispatch(tmp_path):
    context = MissionContext("GATHER_RESOURCE", "one-character", "run-delayed")
    store = JsonMissionStore(tmp_path)
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before_facts = {
        "character_id": "char-a",
        "completion_baseline": {
            "predicate_id": "march_queue_used_increased",
            "counter_fact": "march_queue_used",
            "counter_value": 0,
            "capacity": 5,
            "source_frame_id": "queue-frame",
            "source_timestamp": 100.0,
            "source": "visible_ocr_queue_anchor",
            "character_id": "char-a",
        },
        "precondition_evidence": {
            "troop/commander selection policy is valid for this mission": True,
        },
    }

    class DelayedTool(FakeTool):
        def execute(self, context, before, choice):
            self.executions.append(choice)
            return ToolFeedback(
                True,
                "DISPATCHED",
                facts={
                    "receipt": {
                        "before_frame_id": before.frame_id,
                        "action_id": choice.action_id,
                        "target_id": choice.target_id,
                        "bounded_arguments": {},
                        "non_interference_confirmed": True,
                        "character_id": "char-a",
                    },
                },
            )

    first_tool = DelayedTool((
        snapshot("before", "NEW_TROOP_SETUP", actions=(last,), targets=("TROOP_MARCH",), facts=before_facts, observed_at=101.0),
        snapshot("settling", "UNKNOWN_STATE"),
    ))
    first = MissionRunner(compiled(), first_tool, store).tick(context)
    assert first.status is CheckpointStatus.REOBSERVE
    assert [item.action_id for item in first_tool.executions] == ["MARCH_WITH_CURRENT_SELECTION"]
    assert first.checkpoint.pending_verification is not None
    assert first.checkpoint.pending_verification["before_snapshot"]["observed_at"] == 101.0

    second_tool = DelayedTool((
        snapshot(
            "after",
            "MARCH_IN_PROGRESS",
            facts={
                "march_queue_used": 1,
                "march_queue_capacity": 5,
                "march_queue_source": "visible_ocr_march_queue_region",
                "character_id": "char-a",
            },
            observed_at=102.0,
        ),
    ))
    second = MissionRunner(compiled(), second_tool, store).tick(context)
    assert second.status is CheckpointStatus.COMPLETE
    assert second.checkpoint.pending_verification is None
    assert second_tool.executions == []
    assert second.engine_result.snapshot.observed_at == 101.0
    assert second.checkpoint.verified_transition["before_snapshot"]["observed_at"] == 101.0


def _stale_create_pending(context):
    return {
        "schema_version": 1,
        "action": {"action_id": "CREATE_NEW_TROOP", "target_id": "NEW_TROOP", "arguments": {}},
        "before_snapshot": {
            "mission_id": context.mission_id, "task_id": context.task_id,
            "frame_id": "drawer-old", "state": "TROOP_DISPATCH_DRAWER",
            "facts": {"character_id": "char-a", "client_bounds": [0, 0, 1366, 768],
                      "window": {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}},
            "observed_at": 10.0,
        },
        "feedback": {
            "success": True, "code": "DISPATCHED", "state": None,
            "facts": {"receipt": {"before_frame_id": "drawer-old",
                                    "action_id": "CREATE_NEW_TROOP",
                                    "target_id": "NEW_TROOP", "bounded_arguments": {}, "after_frame_id": "settling-old",
                                    "character_id": "char-a", "non_interference_confirmed": True}},
            "completed": False, "reobserve_required": True,
        },
        "last_observed_frame_id": "settling-old",
    }


def _seed_pending(store, context, pending):
    return store.save(MissionCheckpoint(
        mission_id=context.mission_id, task_id=context.task_id, run_id=context.run_id,
        attempt=context.attempt, parameters=dict(compiled().parameters),
        status=CheckpointStatus.REOBSERVE, revision=0, last_frame_id="settling-old",
        last_state="UNKNOWN_STATE", last_decision="reobserve",
        pending_verification=pending,
    ), expected_revision=0)


def test_runner_retires_stale_create_navigation_without_actuation(tmp_path):
    context = MissionContext("GATHER_RESOURCE", "one-character", "run-reconcile")
    store = JsonMissionStore(tmp_path)
    _seed_pending(store, context, _stale_create_pending(context))
    tool = FakeTool((snapshot("fresh-map", "WORLD_MAP_VIEW", observed_at=11.0,
                               facts={"character_id": "char-a", "client_bounds": [0, 0, 1366, 768],
                                      "window": {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}}),))

    result = MissionRunner(compiled(), tool, store).tick(context)

    assert result.status is CheckpointStatus.REOBSERVE
    assert tool.executions == []
    assert result.checkpoint.pending_verification is None
    assert "receipt preserved" in (result.reason or "")
    next_tool = FakeTool((
        snapshot("next-map", "WORLD_MAP_VIEW", observed_at=12.0,
                 actions=(AllowedAction("OPEN_SEARCH"),)),
        snapshot("search", "RESOURCE_SEARCH_PANEL", observed_at=13.0),
    ))
    resumed = MissionRunner(compiled(), next_tool, store).tick(context)
    assert resumed.status is CheckpointStatus.RUNNING
    assert [item.action_id for item in next_tool.executions] == ["OPEN_SEARCH"]


@pytest.mark.parametrize("change", [
    {"action_id": "MARCH_WITH_CURRENT_SELECTION", "target_id": "TROOP_MARCH"},
    {"state": "UNKNOWN_STATE"},
    {"character_id": "other"},
    {"client_bounds": [0, 0, 1280, 720]},
    {"window_hwnd": 9999},
    {"window_pid": 9999},
    {"window_path": r"C:\Other\MASS.exe"},
    {"after_mission": "CITY_VIEW"},
    {"after_task": "other-task"},
    {"after_time_none": True},
    {"after_time_nan": True},
    {"after_time_equal": True},
    {"replay_last_frame": True},
    {"missing_frame": True},
    {"noninterference": False},
    {"bounded_args": {"x": 1}},
    {"malformed": True},
])
def test_runner_does_not_retire_unsafe_pending_navigation(change):
    context = MissionContext("GATHER_RESOURCE", "one-character", "run-negative")
    pending = _stale_create_pending(context)
    after = snapshot("fresh-map", "WORLD_MAP_VIEW",
                     observed_at=11.0,
                     facts={"character_id": "char-a", "client_bounds": [0, 0, 1366, 768],
                            "window": {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}})
    if change.get("malformed"):
        pending["feedback"] = {"success": True, "code": "DISPATCHED", "facts": {}}
    else:
        if "action_id" in change:
            pending["action"]["action_id"] = change["action_id"]
            pending["action"]["target_id"] = change["target_id"]
        if "state" in change:
            pending["before_snapshot"]["state"] = change["state"]
        if "character_id" in change:
            after = replace(after, facts={"character_id": change["character_id"],
                                           "client_bounds": [0, 0, 1366, 768]})
        if "client_bounds" in change:
            after = replace(after, facts={"character_id": "char-a",
                                           "client_bounds": change["client_bounds"]})
        if any(key in change for key in ("window_hwnd", "window_pid", "window_path")):
            window = dict(after.facts["window"])
            window.update({"hwnd": change.get("window_hwnd", window["hwnd"]),
                           "pid": change.get("window_pid", window["pid"]),
                           "process_path": change.get("window_path", window["process_path"])})
            after = replace(after, facts=dict(after.facts) | {"window": window})
        if "after_mission" in change:
            after = replace(after, mission_id=change["after_mission"])
        if "after_task" in change:
            after = replace(after, task_id=change["after_task"])
        if change.get("after_time_none"):
            after = replace(after, observed_at=None)
        if change.get("after_time_nan"):
            after = replace(after, observed_at=float("nan"))
        if change.get("after_time_equal"):
            after = replace(after, observed_at=10.0)
        if change.get("replay_last_frame"):
            after = replace(after, frame_id=pending["last_observed_frame_id"])
        if change.get("missing_frame"):
            after = replace(after, frame_id=None)
        if "noninterference" in change:
            pending["feedback"]["facts"]["receipt"]["non_interference_confirmed"] = change["noninterference"]
        if "bounded_args" in change:
            pending["feedback"]["facts"]["receipt"]["bounded_arguments"] = change["bounded_args"]
    assert _reversible_navigation_recovery_reason(context, pending, after) is None


@pytest.mark.skipif(
    not (ROOT / "workspace/agents/f6v-navigation-recovery/root/job07-pending-checkpoint.json").exists()
    or not (ROOT / "workspace/runs/f6u-after-dismiss-20260927-01/capture.json").exists(),
    reason="stored job07 pending and post-dismiss capture unavailable",
)
def test_job07_pending_and_post_dismiss_capture_reconcile_offline():
    checkpoint = json.loads((ROOT / "workspace/agents/f6v-navigation-recovery/root/job07-pending-checkpoint.json").read_text())
    pending = checkpoint["checkpoint"]["pending_verification"]
    capture = json.loads((ROOT / "workspace/runs/f6u-after-dismiss-20260927-01/capture.json").read_text())
    frame = capture["frame"]
    window = capture["target"]
    context = MissionContext("GATHER_RESOURCE", checkpoint["checkpoint"]["task_id"],
                             "gather-9777df6dd29fd857b44c-march-4")
    after = snapshot(
        frame["id"], "WORLD_MAP_VIEW",
        observed_at=datetime.fromisoformat(frame["captured_at"]).timestamp(),
        facts={"character_id": "one-character", "client_bounds": frame["client_bounds"],
               "window": window},
    )
    after = replace(after, task_id=context.task_id)
    reason = _reversible_navigation_recovery_reason(context, pending, after)
    assert reason is not None
    assert '"after_frame_id": "rok-20260927T084547279608Z-2f6295878cf6"' in reason
