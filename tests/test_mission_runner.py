from pathlib import Path

from harness.mission_loader import compile_mission
from harness.mission_runner import MissionRunner
from harness.mission_runtime import AllowedAction, MissionContext, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-runner")


def compiled():
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": 6},
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


def test_runner_restores_verified_self_loop_and_advances_to_next_setup_step(tmp_path):
    store = JsonMissionStore(tmp_path)
    actions = (
        AllowedAction("SELECT_RESOURCE_TYPE", True, ("SEARCH_CATEGORY_WOOD",)),
        AllowedAction("SET_RESOURCE_LEVEL", True, ("SEARCH_LEVEL_CONTROL",)),
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
        snapshot("f4", "RESOURCE_SEARCH_PANEL"),
    ))
    second = MissionRunner(compiled(), second_tool, store).tick(CONTEXT)
    assert second_tool.executions[0].action_id == "SET_RESOURCE_LEVEL"
    assert second.checkpoint.revision == 2


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
