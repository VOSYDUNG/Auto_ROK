from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
MATRIX = ROOT / "docs" / "GAME_STATE_MISSION_MATRIX.md"
MISSIONS = ROOT / "config" / "mission_flows.yaml"
UI_STATES = ROOT / "config" / "ui_states.yaml"
GRAPH = ROOT / "config" / "engineering_graph.yaml"


def test_matrix_names_every_declared_mission_and_explicitly_bounds_unknowns():
    matrix = MATRIX.read_text(encoding="utf-8")
    missions = yaml.safe_load(MISSIONS.read_text(encoding="utf-8"))
    for flow in missions["flows"]:
        assert f"`{flow['id']}`" in matrix

    assert "`UNKNOWN_STATE`" in matrix
    assert "`NEEDS_DECISION`" in matrix
    assert "Local LLM is a bounded chooser only" in matrix
    assert "not a claim that every Rise of Kingdoms screen" in matrix


def test_matrix_names_every_operator_trained_ui_state():
    matrix = MATRIX.read_text(encoding="utf-8")
    ui_states = yaml.safe_load(UI_STATES.read_text(encoding="utf-8"))
    for state in ui_states["states"]:
        assert f"`{state['id']}`" in matrix


def test_matrix_covers_every_declared_non_active_branch():
    matrix = MATRIX.read_text(encoding="utf-8")
    graph = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))
    dimensions = graph["coverage"]["other_mission_branches"]
    for branch_id in dimensions:
        assert f"`{branch_id}`" in matrix


def test_matrix_is_registered_as_a_graph_node_with_acceptance_evidence():
    graph = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))
    node = next(item for item in graph["nodes"] if item["id"] == "game_state_mission_matrix")
    assert node["path"] == "docs/GAME_STATE_MISSION_MATRIX.md"
    assert node["status"] == "implemented"
    assert "config/mission_flows.yaml" in node["evidence"]
    assert "docs/GAME_STATE_MISSION_MATRIX.md" in node["evidence"]
