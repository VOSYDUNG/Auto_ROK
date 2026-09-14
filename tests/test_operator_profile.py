from operator_layer.profile import DerivedSignal, ObservedFact, OperatorSnapshot, Provenance


def _fact(key: str, value, confidence: float = 0.95) -> ObservedFact:
    return ObservedFact(
        key=key,
        value=value,
        provenance=Provenance(
            source_surface="VISIBLE_PROFILE",
            observed_at="2026-09-14T10:00:00+07:00",
            confidence=confidence,
            frame_id="frame-1",
        ),
    )


def test_snapshot_prefers_higher_confidence_observation() -> None:
    snapshot = OperatorSnapshot()
    snapshot.put_fact(_fact("progression.power", 100, 0.80))
    snapshot.put_fact(_fact("progression.power", 101, 0.98))
    assert snapshot.value("progression.power") == 101


def test_derived_signal_requires_observed_evidence() -> None:
    snapshot = OperatorSnapshot()
    signal = DerivedSignal(
        key="gathering_activity_signal",
        value="high",
        evidence_keys=("economy.resources_gathered",),
        derivation_version="v1",
        confidence=0.80,
    )
    try:
        snapshot.put_derived(signal)
    except ValueError as exc:
        assert "missing evidence" in str(exc)
    else:
        raise AssertionError("derived signal without evidence should be rejected")


def test_alliance_role_is_not_inferred_until_observed() -> None:
    snapshot = OperatorSnapshot()
    snapshot.put_fact(_fact("alliance.member_count", 37))
    assert snapshot.role_is_observed() is False

    snapshot.put_fact(_fact("alliance.operator_rank", "rank_1"))
    assert snapshot.role_is_observed() is True


def test_execution_context_exposes_normalized_values_only() -> None:
    snapshot = OperatorSnapshot()
    snapshot.put_fact(_fact("identity.governor_name", "example"))
    context = snapshot.as_execution_context()
    assert context["facts"]["identity.governor_name"] == "example"
    assert "frame_id" not in context["facts"]
