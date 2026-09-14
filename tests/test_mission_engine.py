from pathlib import Path

import pytest

from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolFeedback, ToolSnapshot


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-1")


def snapshot(frame: str, state: str, *, targets=(), actions=()):
    return ToolSnapshot("GATHER_RESOURCE", "one-character", frame, state, allowed_actions=actions, target_ids=targets)


class FakeMissionTool:
    def __init__(self, snapshots, feedback=ToolFeedback(True, "VERIFIED")):
        self.snapshots = iter(snapshots)
        self.feedback = feedback
        self.executions = []

    def observe(self, context):
        return next(self.snapshots)

    def execute(self, context, before, choice):
        self.executions.append(choice)
        return self.feedback


def compiled(level=6):
    return compile_mission(MISSIONS, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": level})


def test_verified_declared_transition_replays_from_real_compiled_flow():
    first = snapshot("one", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),))
    second = snapshot("two", "WORLD_MAP_VIEW")
    tool = FakeMissionTool((first, second))
    result = MissionEngine(compiled(), tool).step(CONTEXT, ActionChoice("TOGGLE_CITY_MAP"))
    assert result.decision is EngineDecision.CONTINUE
    assert tool.executions == [ActionChoice("TOGGLE_CITY_MAP")]


@pytest.mark.parametrize("state", ["UNKNOWN_STATE", "AMBIGUOUS_STATE"])
def test_unknown_or_ambiguous_state_blocks_execute(state):
    tool = FakeMissionTool((snapshot("one", state),))
    result = MissionEngine(compiled(), tool).step(CONTEXT, ActionChoice("TOGGLE_CITY_MAP"))
    assert result.decision is EngineDecision.REOBSERVE
    assert tool.executions == []


def test_missing_target_or_invalid_choice_blocks_execute():
    missing = snapshot("one", "RESOURCE_POINT_DETAIL", actions=(AllowedAction("GATHER_RESOURCE_NODE", True, ("RESOURCE_GATHER",)),))
    tool = FakeMissionTool((missing,))
    result = MissionEngine(compiled(), tool).step(CONTEXT, ActionChoice("GATHER_RESOURCE_NODE", "RESOURCE_GATHER"))
    assert result.decision is EngineDecision.REOBSERVE
    assert tool.executions == []
    invalid = FakeMissionTool((snapshot("one", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),)),))
    result = MissionEngine(compiled(), invalid).step(CONTEXT, ActionChoice("OPEN_SEARCH"))
    assert result.decision is EngineDecision.REJECT_CHOICE
    assert invalid.executions == []


def test_verified_self_loop_advances_once_and_cannot_reselect():
    action = AllowedAction("SELECT_RESOURCE_TYPE", True, ("SEARCH_CATEGORY_WOOD",))
    tool = FakeMissionTool((
        snapshot("one", "RESOURCE_SEARCH_PANEL", targets=("SEARCH_CATEGORY_WOOD",), actions=(action,)),
        snapshot("two", "RESOURCE_SEARCH_PANEL"),
        snapshot("three", "RESOURCE_SEARCH_PANEL", targets=("SEARCH_CATEGORY_WOOD",), actions=(action,)),
    ))
    engine = MissionEngine(compiled(), tool)
    choice = ActionChoice("SELECT_RESOURCE_TYPE", "SEARCH_CATEGORY_WOOD")
    assert engine.step(CONTEXT, choice).decision is EngineDecision.CONTINUE
    assert engine.step(CONTEXT, choice).decision is EngineDecision.REOBSERVE
    assert tool.executions == [choice]


def test_completed_flag_without_typed_completion_or_receipt_does_not_complete():
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    tool = FakeMissionTool((
        snapshot("one", "NEW_TROOP_SETUP", targets=("TROOP_MARCH",), actions=(last,)),
        snapshot("two", "MARCH_IN_PROGRESS"),
    ), ToolFeedback(True, "VERIFIED", completed=True))
    result = MissionEngine(compiled(), tool).step(CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH"))
    assert result.decision is EngineDecision.REOBSERVE
    assert result.decision is not EngineDecision.COMPLETE


def test_typed_completion_requires_fresh_same_character_receipt_and_queue_increase():
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before = snapshot("one", "NEW_TROOP_SETUP", targets=("TROOP_MARCH",), actions=(last,))
    before = ToolSnapshot(**{**before.__dict__, "facts": {"march_queue_used": 0, "character_id": "hien"}})
    after = snapshot("two", "MARCH_IN_PROGRESS")
    after = ToolSnapshot(**{**after.__dict__, "facts": {"march_queue_used": 1, "character_id": "hien"}})
    feedback = ToolFeedback(True, "VERIFIED", completed=True, facts={
        "troop_selection_policy_valid": True,
        "precondition_evidence": {"troop/commander selection policy is valid for this mission": True},
        "receipt": {"before_frame_id": "one", "after_frame_id": "two", "character_id": "hien"},
    })
    result = MissionEngine(compiled(), FakeMissionTool((before, after), feedback)).step(
        CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH")
    )
    assert result.decision is EngineDecision.COMPLETE


@pytest.mark.parametrize("before_facts, feedback_facts", [
    ({"character_id": "hien"}, {"troop_selection_policy_valid": True, "receipt": {"before_frame_id": "one", "after_frame_id": "two", "character_id": "hien"}}),
    ({"march_queue_used": 0, "character_id": "hien"}, {"receipt": {"before_frame_id": "one", "after_frame_id": "two", "character_id": "hien"}}),
])
def test_typed_completion_fails_closed_when_count_or_policy_evidence_is_missing(before_facts, feedback_facts):
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before = ToolSnapshot("GATHER_RESOURCE", "one-character", "one", "NEW_TROOP_SETUP", facts=before_facts, allowed_actions=(last,), target_ids=("TROOP_MARCH",))
    after = ToolSnapshot("GATHER_RESOURCE", "one-character", "two", "MARCH_IN_PROGRESS", facts={"march_queue_used": 1, "character_id": "hien"})
    feedback = ToolFeedback(True, "VERIFIED", completed=True, facts=feedback_facts)
    result = MissionEngine(compiled(), FakeMissionTool((before, after), feedback)).step(CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH"))
    assert result.decision is EngineDecision.REOBSERVE


def test_missing_executor_is_explicitly_blocked():
    class ObserveOnly:
        def observe(self, context):
            return snapshot("one", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),))

    result = MissionEngine(compiled(), ObserveOnly()).step(CONTEXT, ActionChoice("TOGGLE_CITY_MAP"))
    assert result.decision is EngineDecision.BLOCKED


def test_compiler_classifier_adapter_engine_replay_waits_for_wp04():
    adapter = pytest.importorskip("harness.state_adapter")
    from harness.contracts import Evidence, Observation
    from harness.scene_graph import SceneGraph
    from harness.state_classifier import StateClassifier

    observation = Observation(1.0, "one", (1280, 720), (
        Evidence("semantic", "city buildings occupy central world canvas", 1.0, metadata={"frame_id": "one"}),
        Evidence("semantic", "resource counters across top", 1.0, metadata={"frame_id": "one"}),
        Evidence("semantic", "primary circular navigation/actions at bottom-right", 1.0, metadata={"frame_id": "one"}),
        Evidence("semantic", "quest/task list at left", 1.0, metadata={"frame_id": "one"}),
    ))
    flow = compiled().flow
    classified = StateClassifier().classify(observation, SceneGraph("one", None))
    before = adapter.to_tool_snapshot(CONTEXT, classified, SceneGraph("one", None), flow)
    assert before.state == "CITY_VIEW"
    after = snapshot("two", "WORLD_MAP_VIEW")
    tool = FakeMissionTool((before, after))
    result = MissionEngine(compiled(), tool).step(CONTEXT, ActionChoice("TOGGLE_CITY_MAP"))
    assert result.decision is EngineDecision.CONTINUE
