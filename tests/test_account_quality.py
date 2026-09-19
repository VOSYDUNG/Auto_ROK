import pytest

from operator_layer.account_quality import (
    AccountQualityVector,
    QualityDimension,
    validate_evidence,
)


def test_quality_vector_keeps_dimensions_separate():
    vector = AccountQualityVector()
    vector.put(
        QualityDimension(
            dimension="combat_history",
            value={"kill_points": 2_200_000_000},
            evidence_keys=("combat.kill_points",),
            confidence=0.95,
            method_version="v1",
        )
    )
    vector.put(
        QualityDimension(
            dimension="migration_mobility",
            value={"passport_pages": 36, "alliance_credits": 13_800_000},
            evidence_keys=(
                "reserves_and_liquidity.migration.passport_pages",
                "reserves_and_liquidity.migration.alliance_credits",
            ),
            confidence=0.90,
            method_version="v1",
        )
    )

    assert vector.require("combat_history").value["kill_points"] == 2_200_000_000
    assert "equipment_readiness" in vector.missing_dimensions()
    assert "combat.kill_points" in vector.evidence_keys()


def test_quality_dimension_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        QualityDimension(
            dimension="opaque_total_score",
            value=99,
            evidence_keys=("progression.power",),
            confidence=0.8,
            method_version="v1",
        )


def test_validate_evidence_rejects_missing_fact():
    vector = AccountQualityVector()
    vector.put(
        QualityDimension(
            dimension="armament_readiness",
            value={"usable_set_count": 6},
            evidence_keys=("armament_readiness.usable_set_count",),
            confidence=0.9,
            method_version="v1",
        )
    )

    with pytest.raises(ValueError):
        validate_evidence(vector, available_fact_keys=[])


def test_validate_evidence_accepts_present_facts():
    vector = AccountQualityVector()
    vector.put(
        QualityDimension(
            dimension="reserve_optionality",
            value={"gold_heads": 290},
            evidence_keys=("reserves_and_liquidity.legendary_sculptures_gold_heads",),
            confidence=0.95,
            method_version="v1",
        )
    )

    validate_evidence(
        vector,
        available_fact_keys=[
            "reserves_and_liquidity.legendary_sculptures_gold_heads"
        ],
    )
