from operator_layer.native_capabilities import (
    CapabilityEntitlement,
    NativeCapabilityId,
    NativeCapabilityProfile,
    OfferSnapshot,
)


def test_advertised_capability_is_not_treated_as_enabled():
    profile = NativeCapabilityProfile()
    profile.observe_offer(
        OfferSnapshot(
            offer_id="gem_supply_30d",
            display_name="30-Day Gem Supply",
            observed_price_text="USD 4.99",
            validity_text="Validity: 30 Days",
            observed_at="2026-09-14T11:00:00+07:00",
            source_surface="STORE_GEM_SUPPLY",
            advertised_capabilities=(NativeCapabilityId.AUTO_PEACEKEEPING,),
        )
    )

    assert profile.advertised(NativeCapabilityId.AUTO_PEACEKEEPING) is True
    assert profile.enabled(NativeCapabilityId.AUTO_PEACEKEEPING) is False


def test_visible_entitlement_enables_native_capability():
    profile = NativeCapabilityProfile()
    profile.observe_entitlement(
        CapabilityEntitlement(
            capability_id=NativeCapabilityId.AUTO_HELP,
            enabled=True,
            observed_at="2026-09-14T11:05:00+07:00",
            source_surface="VISIBLE_FEATURE_CONTROL",
            confidence=0.99,
            entitlement_source="30-Day Gem Supply",
        )
    )

    assert profile.enabled(NativeCapabilityId.AUTO_HELP) is True
    assert NativeCapabilityId.AUTO_HELP in profile.enabled_capabilities()


def test_execution_context_separates_advertised_from_enabled():
    profile = NativeCapabilityProfile()
    profile.observe_offer(
        OfferSnapshot(
            offer_id="gem_supply_30d",
            display_name="30-Day Gem Supply",
            observed_price_text="USD 4.99",
            validity_text="Validity: 30 Days",
            observed_at="2026-09-14T11:00:00+07:00",
            source_surface="STORE_GEM_SUPPLY",
            advertised_capabilities=(
                NativeCapabilityId.AUTO_PEACEKEEPING,
                NativeCapabilityId.AUTO_HELP,
                NativeCapabilityId.AUTO_TRANSLATION,
            ),
        )
    )
    profile.observe_entitlement(
        CapabilityEntitlement(
            capability_id=NativeCapabilityId.AUTO_PEACEKEEPING,
            enabled=True,
            observed_at="2026-09-14T11:10:00+07:00",
            source_surface="VISIBLE_FEATURE_CONTROL",
            confidence=0.98,
        )
    )

    context = profile.execution_context()

    assert context["native_capabilities"]["AUTO_PEACEKEEPING"] is True
    assert "AUTO_HELP" in context["advertised_native_capabilities"]
    assert "AUTO_HELP" not in context["native_capabilities"]
