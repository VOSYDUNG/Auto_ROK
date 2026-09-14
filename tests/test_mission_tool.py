from dataclasses import replace
from pathlib import Path

from harness.action_surface import SemanticActionSurface
from harness.contracts import BoundingBox, Evidence, Observation
from harness.human_io import KeyboardAction
from harness.mission_engine import EngineDecision, MissionEngine
from harness.mission_loader import compile_mission
from harness.mission_runtime import ActionChoice, MissionContext
from harness.mission_tool import (
    ActionDispatchReceipt,
    BoundedMissionTool,
    HumanInterfaceActionProvider,
    InterferenceCheck,
    ObservationBundle,
)
from harness.scene_graph import SceneGraph, VisualTarget


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"
CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-g03")
PRECONDITION = "troop/commander selection policy is valid for this mission"


def compiled():
    return compile_mission(
        MISSIONS,
        STATES,
        "GATHER_RESOURCE",
        {"resource_type": "WOOD", "resource_level": 6},
    )


def evidence(frame, *labels):
    return tuple(
        Evidence("semantic", label, 1.0, metadata={"frame_id": frame})
        for label in labels
    )


def bundle(frame, state, *, targets=(), facts=None):
    labels = {
        "CITY_VIEW": (
            "city buildings occupy central world canvas",
            "resource counters across top",
            "primary circular navigation/actions at bottom-right",
            "quest/task list at left",
        ),
        "WORLD_MAP_VIEW": (
            "map terrain and world objects occupy central canvas",
            "resource counters across top",
            "bottom-right primary navigation is visible",
        ),
        "NEW_TROOP_SETUP": ("New Troop", "MARCH", "Units", "Total Power"),
        "MARCH_IN_PROGRESS": (
            "used march count is greater than before dispatch",
            "troop/path indicator may be visible on map",
        ),
    }[state]
    observation = Observation(1.0, frame, (1280, 720), evidence(frame, *labels))
    return ObservationBundle(
        observation,
        SceneGraph(frame, None, tuple(targets), facts or {}),
    )


class FakeObservations:
    def __init__(self, *bundles):
        self.items = iter(bundles)

    def observe(self, context):
        return next(self.items)


class FakeActions:
    def __init__(self, receipt, *, facts=None):
        self.receipt = receipt
        self.facts = facts or {}
        self.calls = []

    def dispatch(self, context, before, choice, scene):
        self.calls.append((before.frame_id, choice, scene.frame_id))
        return replace(self.receipt, facts=self.facts)


class Recorder:
    def __init__(self):
        self.actions = []

    def perform(self, action):
        self.actions.append(action)


class Guard:
    def __init__(self, allowed):
        self.allowed = allowed

    def check(self, context, before, choice, scene, resolved):
        return InterferenceCheck(
            self.allowed,
            "ISOLATED" if self.allowed else "INTERFERENCE_BLOCKED",
            {"isolation_scope": "test"},
        )


def test_bounded_tool_compiles_visible_observation_into_current_action_surface():
    tool = BoundedMissionTool(
        compiled(),
        FakeObservations(bundle("f1", "CITY_VIEW")),
        FakeActions(ActionDispatchReceipt("TOGGLE_CITY_MAP", "f1", True, non_interference_confirmed=True)),
    )
    snapshot = tool.observe(CONTEXT)
    assert snapshot.frame_id == "f1"
    assert snapshot.state == "CITY_VIEW"
    assert [item.action_id for item in snapshot.allowed_actions] == ["TOGGLE_CITY_MAP"]


def test_human_action_provider_denies_input_before_actuation_when_guard_fails():
    recorder = Recorder()
    provider = HumanInterfaceActionProvider(
        SemanticActionSurface({"TOGGLE_CITY_MAP": "SPACE"}),
        recorder,
        Guard(False),
    )
    before = BoundedMissionTool(
        compiled(),
        FakeObservations(bundle("f1", "CITY_VIEW")),
        FakeActions(ActionDispatchReceipt("noop", "f1", False)),
    ).observe(CONTEXT)
    receipt = provider.dispatch(
        CONTEXT,
        before,
        ActionChoice("TOGGLE_CITY_MAP"),
        SceneGraph("f1", None),
    )
    assert receipt.dispatched is False
    assert receipt.code == "INTERFERENCE_BLOCKED"
    assert recorder.actions == []


def test_human_action_provider_dispatches_hotkey_only_after_guard_passes():
    recorder = Recorder()
    provider = HumanInterfaceActionProvider(
        SemanticActionSurface({"TOGGLE_CITY_MAP": "SPACE"}),
        recorder,
        Guard(True),
    )
    before = BoundedMissionTool(
        compiled(),
        FakeObservations(bundle("f1", "CITY_VIEW")),
        FakeActions(ActionDispatchReceipt("noop", "f1", False)),
    ).observe(CONTEXT)
    receipt = provider.dispatch(
        CONTEXT,
        before,
        ActionChoice("TOGGLE_CITY_MAP"),
        SceneGraph("f1", None),
    )
    assert receipt.dispatched is True
    assert receipt.non_interference_confirmed is True
    assert recorder.actions == [KeyboardAction(("SPACE",))]


def test_dispatch_receipt_is_promoted_only_after_fresh_expected_observation():
    receipt = ActionDispatchReceipt(
        "TOGGLE_CITY_MAP",
        "f1",
        True,
        non_interference_confirmed=True,
    )
    tool = BoundedMissionTool(
        compiled(),
        FakeObservations(
            bundle("f1", "CITY_VIEW"),
            bundle("f2", "WORLD_MAP_VIEW"),
        ),
        FakeActions(receipt),
    )
    result = MissionEngine(compiled(), tool).step(
        CONTEXT,
        ActionChoice("TOGGLE_CITY_MAP"),
    )
    assert result.decision is EngineDecision.CONTINUE
    assert result.feedback.code == "VERIFIED"
    assert result.feedback.facts["receipt"]["after_frame_id"] == "f2"


def test_final_gather_completion_is_engine_verified_from_pre_action_policy_evidence():
    target = VisualTarget(
        "TROOP_MARCH",
        "f1",
        "MARCH",
        BoundingBox(100, 100, 200, 150),
        1.0,
        "test",
    )
    receipt = ActionDispatchReceipt(
        "MARCH_WITH_CURRENT_SELECTION",
        "f1",
        True,
        "TROOP_MARCH",
        True,
    )
    tool = BoundedMissionTool(
        compiled(),
        FakeObservations(
            bundle(
                "f1",
                "NEW_TROOP_SETUP",
                targets=(target,),
                facts={
                    "march_queue_used": 0,
                    "character_id": "hien",
                    "precondition_evidence": {PRECONDITION: True},
                },
            ),
            bundle(
                "f2",
                "MARCH_IN_PROGRESS",
                facts={"march_queue_used": 1, "character_id": "hien"},
            ),
        ),
        FakeActions(receipt),
    )
    result = MissionEngine(compiled(), tool).step(
        CONTEXT,
        ActionChoice("MARCH_WITH_CURRENT_SELECTION", "TROOP_MARCH"),
    )
    assert result.decision is EngineDecision.COMPLETE
    assert result.feedback.code == "VERIFIED"
    assert result.feedback.completed is False
    assert result.feedback.facts["receipt"]["after_frame_id"] == "f2"
