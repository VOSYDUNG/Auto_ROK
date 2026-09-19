from pathlib import Path

from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore


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


def snapshot(frame, state, *, actions=(), targets=(), facts=None):
    return ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        frame,
        state,
        facts=facts or {},
        allowed_actions=actions,
        target_ids=targets,
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
        snapshot("before", "NEW_TROOP_SETUP", actions=(last,), targets=("TROOP_MARCH",), facts=before_facts),
        snapshot("settling", "UNKNOWN_STATE"),
    ))
    first = MissionRunner(compiled(), first_tool, store).tick(context)
    assert first.status is CheckpointStatus.REOBSERVE
    assert [item.action_id for item in first_tool.executions] == ["MARCH_WITH_CURRENT_SELECTION"]
    assert first.checkpoint.pending_verification is not None

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
        ),
    ))
    second = MissionRunner(compiled(), second_tool, store).tick(context)
    assert second.status is CheckpointStatus.COMPLETE
    assert second.checkpoint.pending_verification is None
    assert second_tool.executions == []
