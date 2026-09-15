from pathlib import Path

import pytest

from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, AllowedAction, MissionContext, ToolFeedback, ToolSnapshot


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-1")
PRECONDITION = "troop/commander selection policy is valid for this mission"


def snapshot(frame, state, *, targets=(), actions=(), facts=None):
    return ToolSnapshot(
        "GATHER_RESOURCE",
        "one-character",
        frame,
        state,
        facts=facts or {},
        allowed_actions=actions,
        target_ids=targets,
    )


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
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": level},
    )


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
    action = AllowedAction("GATHER_RESOURCE_NODE", True, ("RESOURCE_GATHER",))
    tool = FakeMissionTool((snapshot("one", "RESOURCE_POINT_DETAIL", actions=(action,)),))
    result = MissionEngine(compiled(), tool).step(
        CONTEXT, ActionChoice("GATHER_RESOURCE_NODE", "RESOURCE_GATHER")
    )
    assert result.decision is EngineDecision.REOBSERVE
    assert tool.executions == []

    invalid = FakeMissionTool((
        snapshot("one", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),)),
    ))
    result = MissionEngine(compiled(), invalid).step(CONTEXT, ActionChoice("OPEN_SEARCH"))
    assert result.decision is EngineDecision.REJECT_CHOICE
    assert invalid.executions == []


def test_verified_self_loop_can_be_checkpointed_and_restored():
    action = AllowedAction("SELECT_RESOURCE_TYPE", True, ("SEARCH_CATEGORY_WOOD",))
    first_tool = FakeMissionTool((
        snapshot("one", "RESOURCE_SEARCH_PANEL", targets=("SEARCH_CATEGORY_WOOD",), actions=(action,)),
        snapshot("two", "RESOURCE_SEARCH_PANEL"),
    ))
    engine = MissionEngine(compiled(), first_tool)
    choice = ActionChoice("SELECT_RESOURCE_TYPE", "SEARCH_CATEGORY_WOOD")
    assert engine.step(CONTEXT, choice).decision is EngineDecision.CONTINUE
    checkpoint = engine.verified_self_loops
    assert checkpoint == (("run-1", "RESOURCE_SEARCH_PANEL", "SELECT_RESOURCE_TYPE"),)

    second_tool = FakeMissionTool((
        snapshot("three", "RESOURCE_SEARCH_PANEL", targets=("SEARCH_CATEGORY_WOOD",), actions=(action,)),
    ))
    resumed = MissionEngine(compiled(), second_tool)
    resumed.restore_verified_self_loops(checkpoint)
    result = resumed.step(CONTEXT, choice)
    assert result.decision is EngineDecision.REOBSERVE
    assert second_tool.executions == []


def test_declared_gameplay_precondition_blocks_before_actuation():
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    tool = FakeMissionTool((
        snapshot(
            "one",
            "NEW_TROOP_SETUP",
            targets=("TROOP_MARCH",),
            actions=(last,),
            facts={"march_queue_used": 0, "character_id": "hien"},
        ),
    ))
    result = MissionEngine(compiled(), tool).step(
        CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH")
    )
    assert result.decision is EngineDecision.NEEDS_DECISION
    assert PRECONDITION in result.reason
    assert tool.executions == []


def test_typed_completion_requires_fresh_same_character_receipt_queue_increase_and_precondition():
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before = snapshot(
        "one",
        "NEW_TROOP_SETUP",
        targets=("TROOP_MARCH",),
        actions=(last,),
            facts={
                "character_id": "hien",
                "completion_baseline": {"predicate_id": "march_queue_used_increased", "counter_fact": "march_queue_used", "counter_value": 0, "capacity": 5, "source_frame_id": "queue-frame", "source": "visible_ocr_queue_anchor", "character_id": "hien"},
                "precondition_evidence": {PRECONDITION: True},
        },
    )
    after = snapshot(
        "two",
        "MARCH_IN_PROGRESS",
            facts={"march_queue_used": 1, "march_queue_capacity": 5, "march_queue_source": "visible_ocr_march_queue_region", "character_id": "hien"},
    )
    feedback = ToolFeedback(
        True,
        "VERIFIED",
        completed=True,
        facts={
            "receipt": {
                "before_frame_id": "one",
                "after_frame_id": "two",
                "character_id": "hien",
            },
        },
    )
    result = MissionEngine(compiled(), FakeMissionTool((before, after), feedback)).step(
        CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH")
    )
    assert result.decision is EngineDecision.COMPLETE


def test_completion_fails_closed_when_queue_count_missing():
    last = AllowedAction("MARCH_WITH_CURRENT_SELECTION", True, ("TROOP_MARCH",))
    before = snapshot(
        "one",
        "NEW_TROOP_SETUP",
        targets=("TROOP_MARCH",),
        actions=(last,),
        facts={
            "character_id": "hien",
            "precondition_evidence": {PRECONDITION: True},
        },
    )
    after = snapshot(
        "two",
        "MARCH_IN_PROGRESS",
        facts={"march_queue_used": 1, "character_id": "hien"},
    )
    feedback = ToolFeedback(
        True,
        "VERIFIED",
        completed=True,
        facts={"receipt": {"before_frame_id": "one", "after_frame_id": "two", "character_id": "hien"}},
    )
    result = MissionEngine(compiled(), FakeMissionTool((before, after), feedback)).step(
        CONTEXT, ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH")
    )
    assert result.decision is EngineDecision.REOBSERVE


def test_missing_executor_is_explicitly_blocked():
    class ObserveOnly:
        def observe(self, context):
            return snapshot("one", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),))

    result = MissionEngine(compiled(), ObserveOnly()).step(CONTEXT, ActionChoice("TOGGLE_CITY_MAP"))
    assert result.decision is EngineDecision.BLOCKED


def test_step_from_snapshot_does_not_recapture_before_action():
    class Tool:
        def __init__(self):
            self.observe_calls = 0

        def observe(self, context):
            self.observe_calls += 1
            return snapshot("after", "WORLD_MAP_VIEW")

        def execute(self, context, before, choice):
            assert before.frame_id == "before"
            return ToolFeedback(True, "VERIFIED")

    tool = Tool()
    before = snapshot("before", "CITY_VIEW", actions=(AllowedAction("TOGGLE_CITY_MAP"),))
    result = MissionEngine(compiled(), tool).step_from_snapshot(
        CONTEXT, before, ActionChoice("TOGGLE_CITY_MAP")
    )
    assert result.decision is EngineDecision.CONTINUE
    assert tool.observe_calls == 1
