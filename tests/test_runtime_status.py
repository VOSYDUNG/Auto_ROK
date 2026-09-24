"""runtime-status.yaml must not be able to overstate what was proven.

The file is committed so the real state is visible on GitHub. That only helps
if the claims inside it are constrained, so this checks the few things that
would let it drift back into wishful reporting:

  * the status vocabulary is closed - no inventing a level that sounds done;
  * a capability cannot claim it was proven live while its own
    live_proof_after_commit field says false;
  * FIRST DONE cannot outrank its required capabilities or unfinished gates;
  * daily-farm gates stay in their later milestone.

Deliberately specific to this one file. A generic status framework would be a
second authority over completion, and AGENTS.md is the first.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "runtime-status.yaml"

#: The closed vocabulary from AGENTS.md, in ascending order of what it takes
#: to claim. Order matters: the comparisons below rely on it.
STATUS_LEVELS = (
    "UNIMPLEMENTED",
    "IMPLEMENTED",
    "WIRED",
    "LIVE_PROVEN_ONCE",
    "REPEATABLE",
    "STABLE",
)

#: Levels that assert a live occurrence actually happened.
LIVE_LEVELS = {"LIVE_PROVEN_ONCE", "REPEATABLE", "STABLE"}


@pytest.fixture(scope="module")
def status() -> dict:
    assert STATUS_PATH.exists(), "runtime-status.yaml is missing"
    loaded = yaml.safe_load(STATUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "runtime-status.yaml must parse to a mapping"
    return loaded


def test_it_parses_and_declares_its_schema(status):
    assert status["schema_version"] == 1
    assert status["head_basis"]["sha"]
    assert status["head_basis"]["branch"]
    assert status["objective"]["id"]


def test_every_status_belongs_to_the_closed_vocabulary(status):
    offenders = []
    for name, entry in status["capabilities"].items():
        level = entry.get("status")
        if level not in STATUS_LEVELS:
            offenders.append(f"{name}={level!r}")
    assert not offenders, (
        f"unknown status values {offenders}; the vocabulary is closed and "
        f"defined in AGENTS.md: {list(STATUS_LEVELS)}"
    )
    assert status["objective"]["overall_status"] in STATUS_LEVELS


def test_a_capability_cannot_claim_live_proof_it_denies_having(status):
    """The field and the level have to agree.

    This is the specific way the file could lie without anyone noticing: a
    capability raised to LIVE_PROVEN_ONCE while the honest
    live_proof_after_commit: false is left sitting underneath it.
    """
    offenders = []
    for name, entry in status["capabilities"].items():
        if "live_proof_after_commit" not in entry:
            continue
        if entry["status"] in LIVE_LEVELS and entry["live_proof_after_commit"] is False:
            offenders.append(name)
    assert not offenders, (
        f"{offenders} claim a live-proven status while recording "
        "live_proof_after_commit: false. Run the live occurrence, or lower "
        "the status to WIRED."
    )


def test_the_objective_cannot_outrank_the_capabilities_it_needs(status):
    """A milestone is only as proven as its weakest dependency."""
    required = status["objective"]["required_capabilities"]
    assert required
    assert set(required) <= set(status["capabilities"])
    levels = [
        STATUS_LEVELS.index(status["capabilities"][name]["status"])
        for name in required
    ]
    overall = STATUS_LEVELS.index(status["objective"]["overall_status"])
    assert overall <= min(levels), (
        f"objective claims {status['objective']['overall_status']} while its "
        f"weakest capability is {STATUS_LEVELS[min(levels)]}"
    )


def test_first_done_cannot_claim_live_while_a_gate_is_false(status):
    gates = status["acceptance"]
    failing = [name for name, gate in gates.items() if gate.get("passed") is not True]
    if failing:
        assert status["objective"]["overall_status"] not in LIVE_LEVELS, (
            f"objective claims live proof while these FIRST DONE gates are not "
            f"passed: {failing}"
        )


def test_first_done_gates_match_the_current_prd_scope(status):
    expected_first_done = {
        "one_startup_authorized_job_without_per_march_approval",
        "one_visible_client_and_ui_confirmed_character",
        "fresh_game_filled_new_troop_pair_preserved_on_each_march",
        "five_fresh_verified_queue_increments_0_to_5_of_5",
        "immutable_job_close_report",
    }
    assert set(status["acceptance"]) == expected_first_done
    assert all(type(gate.get("passed")) is bool for gate in status["acceptance"].values())

    expected_later = {
        "two_consecutive_unattended_5_of_5_batches",
        "buff_never_reaches_zero",
        "returns_detected_and_refilled",
        "buffed_cycle_between_2h00_and_2h30",
    }
    daily = status["later_milestones"]["daily_farm"]
    assert set(daily["acceptance"]) == expected_later
    assert daily["overall_status"] not in LIVE_LEVELS


def test_first_done_cannot_inherit_operator_assisted_live_proof(status):
    objective = status["objective"]
    capabilities = status["capabilities"]
    assert objective["id"] == "FIRST_DONE_GATHER_FIVE_MARCHES"
    assert capabilities["dispatch_queue_to_5_of_5"]["status"] == "LIVE_PROVEN_ONCE"
    for name in (
        "bounded_gather_job",
        "client_binding",
        "new_troop_formation_fact",
        "startup_ui_character_identity",
        "fresh_0_of_5_queue_baseline",
        "five_transition_job_coordinator",
    ):
        assert name in objective["required_capabilities"]
    if any(
        capabilities[name]["status"] not in LIVE_LEVELS
        for name in objective["required_capabilities"]
    ):
        assert objective["overall_status"] not in LIVE_LEVELS


def test_agents_md_defines_the_same_vocabulary(status):
    """The file and the contract must not drift apart."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for level in STATUS_LEVELS:
        assert level in agents, f"{level} is not defined in AGENTS.md"
