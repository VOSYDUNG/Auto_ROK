from pathlib import Path

from harness.mission_loader import compile_mission


ROOT = Path(__file__).parents[1]
MISSIONS = ROOT / "config" / "mission_flows.yaml"
STATES = ROOT / "config" / "ui_states.yaml"


def test_alliance_claim_compiles_explicit_city_and_world_entries():
    compiled = compile_mission(MISSIONS, STATES, "CLAIM_ALLIANCE_TERRITORY_RSS")
    assert compiled.flow.flow_id == "CLAIM_ALLIANCE_TERRITORY_RSS"

    city = compiled.flow.transition_for("CITY_VIEW", "OPEN_ALLIANCE")
    world = compiled.flow.transition_for("WORLD_MAP_VIEW", "OPEN_ALLIANCE")
    assert city is not None and city.expect_states == ("ALLIANCE_HOME",)
    assert world is not None and world.expect_states == ("ALLIANCE_HOME",)


def test_alliance_claim_uses_only_declared_semantic_targets():
    compiled = compile_mission(MISSIONS, STATES, "CLAIM_ALLIANCE_TERRITORY_RSS")

    territory = compiled.flow.transition_for("ALLIANCE_HOME", "OPEN_ALLIANCE_TERRITORY")
    claim = compiled.flow.transition_for("ALLIANCE_TERRITORY", "CLAIM_ALLIANCE_TERRITORY_RSS")

    assert territory is not None
    assert territory.requires_target is True
    assert territory.target_ids == ("ALLIANCE_TERRITORY_ENTRY",)
    assert territory.expect_states == ("ALLIANCE_TERRITORY",)

    assert claim is not None
    assert claim.requires_target is True
    assert claim.target_ids == ("TERRITORY_RSS_CLAIM",)
    assert claim.expect_states == ("ALLIANCE_TERRITORY",)
    assert claim.completion_edge is False


def test_post_claim_completion_remains_explicitly_untrained():
    compiled = compile_mission(MISSIONS, STATES, "CLAIM_ALLIANCE_TERRITORY_RSS")
    assert compiled.completion is None
    assert compiled.flow.completion_states == ()
    assert compiled.flow.completion_families == ()
