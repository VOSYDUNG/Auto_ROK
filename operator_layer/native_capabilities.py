from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class NativeCapabilityId(str, Enum):
    AUTO_PEACEKEEPING = "AUTO_PEACEKEEPING"
    AUTO_HELP = "AUTO_HELP"
    AUTO_TRANSLATION = "AUTO_TRANSLATION"


@dataclass(frozen=True)
class OfferSnapshot:
    """Time-scoped commercial offer observed through visible UI."""

    offer_id: str
    display_name: str
    observed_price_text: str | None
    validity_text: str | None
    observed_at: str
    source_surface: str
    reward_summary: Mapping[str, object] = field(default_factory=dict)
    advertised_capabilities: tuple[NativeCapabilityId, ...] = ()


@dataclass(frozen=True)
class CapabilityEntitlement:
    """Observed entitlement for the current operator account.

    An advertised capability is not an entitlement. `enabled=True` should only
    be emitted after the current account visibly exposes/activates that feature.
    """

    capability_id: NativeCapabilityId
    enabled: bool
    observed_at: str
    source_surface: str
    confidence: float
    entitlement_source: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass
class NativeCapabilityProfile:
    """Operator/account-level native automation capabilities."""

    offers: dict[str, OfferSnapshot] = field(default_factory=dict)
    entitlements: dict[NativeCapabilityId, CapabilityEntitlement] = field(
        default_factory=dict
    )

    def observe_offer(self, offer: OfferSnapshot) -> None:
        self.offers[offer.offer_id] = offer

    def observe_entitlement(self, entitlement: CapabilityEntitlement) -> None:
        current = self.entitlements.get(entitlement.capability_id)
        if current is None or entitlement.confidence >= current.confidence:
            self.entitlements[entitlement.capability_id] = entitlement

    def advertised(self, capability_id: NativeCapabilityId) -> bool:
        return any(
            capability_id in offer.advertised_capabilities
            for offer in self.offers.values()
        )

    def enabled(self, capability_id: NativeCapabilityId) -> bool:
        entitlement = self.entitlements.get(capability_id)
        return bool(entitlement and entitlement.enabled)

    def enabled_capabilities(self) -> tuple[NativeCapabilityId, ...]:
        return tuple(
            capability_id
            for capability_id, entitlement in self.entitlements.items()
            if entitlement.enabled
        )

    def execution_context(self) -> dict[str, object]:
        """Compact account-native capability context for later runtime merge."""
        return {
            "native_capabilities": {
                capability_id.value: entitlement.enabled
                for capability_id, entitlement in self.entitlements.items()
            },
            "advertised_native_capabilities": sorted(
                {
                    capability_id.value
                    for offer in self.offers.values()
                    for capability_id in offer.advertised_capabilities
                }
            ),
        }
