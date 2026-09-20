"""runtime-status.yaml must not be able to overstate what was proven.

The file is committed so the real state is visible on GitHub. That only helps
if the claims inside it are constrained, so this checks the few things that
would let it drift back into wishful reporting:

  * the status vocabulary is closed - no inventing a level that sounds done;
  * a capability cannot claim it was proven live while its own
    live_proof_after_commit field says false;
  * M7.1 cannot call itself STABLE while an acceptance gate is false.

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
    levels = [
        STATUS_LEVELS.index(entry["status"])
        for entry in status["capabilities"].values()
    ]
    overall = STATUS_LEVELS.index(status["objective"]["overall_status"])
    assert overall <= min(levels), (
        f"objective claims {status['objective']['overall_status']} while its "
        f"weakest capability is {STATUS_LEVELS[min(levels)]}"
    )


def test_m7_1_cannot_claim_stable_while_a_gate_is_false(status):
    gates = status["acceptance"]
    failing = [name for name, gate in gates.items() if gate.get("passed") is not True]
    if failing:
        assert status["objective"]["overall_status"] != "STABLE", (
            f"objective claims STABLE while these acceptance gates are not "
            f"passed: {failing}"
        )


def test_the_four_prd_acceptance_gates_are_all_present(status):
    """PRD section 3.4 condition 2, so a gate cannot be quietly dropped."""
    expected = {
        "two_consecutive_unattended_5_of_5_batches",
        "buff_never_reaches_zero",
        "returns_detected_and_refilled",
        "buffed_cycle_between_2h00_and_2h30",
    }
    assert expected <= set(status["acceptance"]), (
        f"missing acceptance gates: {expected - set(status['acceptance'])}"
    )


def test_agents_md_defines_the_same_vocabulary(status):
    """The file and the contract must not drift apart."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for level in STATUS_LEVELS:
        assert level in agents, f"{level} is not defined in AGENTS.md"
