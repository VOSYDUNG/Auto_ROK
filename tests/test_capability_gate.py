from harness.capability_gate import (
    CapabilityGate,
    CapabilityRule,
    ExposureMode,
    FactRequirement,
)


def test_unknown_capability_is_not_exposed():
    gate = CapabilityGate([])
    result = gate.evaluate("UNKNOWN", {})
    assert result.exposed is False


def test_required_role_must_be_present():
    gate = CapabilityGate(
        [
            CapabilityRule(
                action_id="ALLIANCE_CONSTRUCTION",
                required_facts=(
                    FactRequirement(
                        key="alliance_role",
                        one_of=("alliance_leader", "alliance_officer"),
                    ),
                ),
            )
        ]
    )

    denied = gate.evaluate("ALLIANCE_CONSTRUCTION", {"alliance_role": "member"})
    allowed = gate.evaluate(
        "ALLIANCE_CONSTRUCTION", {"alliance_role": "alliance_officer"}
    )

    assert denied.exposed is False
    assert allowed.exposed is True
    assert allowed.requires_human_approval is False


def test_forbidden_fact_blocks_action():
    gate = CapabilityGate(
        [
            CapabilityRule(
                action_id="TELEPORT",
                forbidden_facts=(
                    FactRequirement(key="fighting_rallied_army", equals=True),
                ),
            )
        ]
    )

    result = gate.evaluate("TELEPORT", {"fighting_rallied_army": True})
    assert result.exposed is False


def test_human_approval_mode_is_explicit():
    gate = CapabilityGate(
        [
            CapabilityRule(
                action_id="RESOURCE_ASSISTANCE",
                mode=ExposureMode.HUMAN_APPROVAL,
            )
        ]
    )

    result = gate.evaluate("RESOURCE_ASSISTANCE", {})
    assert result.exposed is True
    assert result.requires_human_approval is True
