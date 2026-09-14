from pathlib import Path

import pytest

from harness.mission_loader import MissionCompileError, compile_mission


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"


def test_gather_resource_compiles_to_runtime_graph():
    compiled = compile_mission(MISSIONS, STATES, "GATHER_RESOURCE", {
        "resource_type": "WOOD", "resource_level": 6,
    })
    assert compiled.flow.flow_id == "GATHER_RESOURCE"
    assert compiled.flow.outgoing("RESOURCE_SEARCH_PANEL")[0].target_ids == ("SEARCH_CATEGORY_WOOD",)
    assert compiled.flow.allowed_actions("RESOURCE_SEARCH_PANEL")[0].action_id == "SELECT_RESOURCE_TYPE"


def test_null_optional_level_transition_is_omitted():
    compiled = compile_mission(MISSIONS, STATES, "GATHER_RESOURCE", {
        "resource_type": "WOOD", "resource_level": None,
    })
    assert all(edge.action_id != "SET_RESOURCE_LEVEL" for edge in compiled.flow.transitions)


def test_unknown_state_and_target_fail_closed(tmp_path):
    bad_state = tmp_path / "missions.yaml"
    bad_state.write_text(MISSIONS.read_text(encoding="utf-8").replace("from: RESOURCE_SEARCH_PANEL", "from: UNKNOWN_STATE", 1), encoding="utf-8")
    with pytest.raises(MissionCompileError, match="unknown state"):
        compile_mission(bad_state, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": 1})
    bad_target = tmp_path / "target.yaml"
    bad_target.write_text(MISSIONS.read_text(encoding="utf-8").replace("target: SEARCH_EXECUTE", "target: UNKNOWN_TARGET"), encoding="utf-8")
    with pytest.raises(MissionCompileError, match="unknown target"):
        compile_mission(bad_target, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": 1})


def test_invalid_parameter_mapping_fails(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(MISSIONS.read_text(encoding="utf-8").replace("          FOOD: SEARCH_CATEGORY_FOOD", "          resource_level: SEARCH_CATEGORY_FOOD", 1), encoding="utf-8")
    with pytest.raises(MissionCompileError):
        compile_mission(bad, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": 1})


def test_completion_criterion_is_typed_and_preserves_supporting_evidence():
    compiled = compile_mission(MISSIONS, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": 1})
    assert compiled.completion.predicate_id == "march_queue_used_increased"
    assert compiled.completion.canonical_counter_fact == "march_queue_used"
    assert "active troop/march indicator appears" in compiled.completion.supporting_evidence


def test_unknown_completion_text_fails_closed(tmp_path):
    bad = tmp_path / "bad-completion.yaml"
    bad.write_text(MISSIONS.read_text(encoding="utf-8").replace("march queue used count increased relative to pre-dispatch observation", "invented completion rule"), encoding="utf-8")
    with pytest.raises(MissionCompileError, match="unsupported completion"):
        compile_mission(bad, STATES, "GATHER_RESOURCE", {"resource_type": "WOOD", "resource_level": 1})
