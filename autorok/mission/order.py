"""Resource orders and the fleet-level delivery ledger.

An order is what the operator issues from front-line information: a quota of
resources that must be RECEIVED, by a deadline.  The quoted figures are net of
tax, so the fleet must deliver gross amounts that exceed them.

There is deliberately no per-delivery ceiling.  The game permits transferring
everything, so the governing bound is the order itself, measured in aggregate
across every farming character.  That makes the ledger - not any single action
check - the thing that keeps delivery correct.  See
``knowledge/farming_workflow_2026-09-19.yaml``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import ceil
from typing import Iterable, Mapping


class OrderError(ValueError):
    """Raised when an order or a delivery posting violates its contract."""


class ResourceKind(str, Enum):
    FOOD = "FOOD"
    WOOD = "WOOD"
    STONE = "STONE"
    GOLD = "GOLD"


#: Default gathering weights.  Gold carries double weight because orders ask
#: for materially more of it; confirmed by the operator on 2026-09-19.
DEFAULT_RATIO: Mapping[ResourceKind, int] = {
    ResourceKind.FOOD: 1,
    ResourceKind.WOOD: 1,
    ResourceKind.STONE: 1,
    ResourceKind.GOLD: 2,
}


def _check_amounts(amounts: Mapping[ResourceKind, int], *, label: str) -> dict[ResourceKind, int]:
    if not amounts:
        raise OrderError(f"{label} must name at least one resource")
    checked: dict[ResourceKind, int] = {}
    for kind, value in amounts.items():
        if not isinstance(kind, ResourceKind):
            raise OrderError(f"{label} key {kind!r} is not a ResourceKind")
        if not isinstance(value, int) or isinstance(value, bool):
            raise OrderError(f"{label}[{kind.value}] must be an int, got {type(value).__name__}")
        if value < 0:
            raise OrderError(f"{label}[{kind.value}] must not be negative")
        checked[kind] = value
    return checked


@dataclass(frozen=True)
class Order:
    """A net-of-tax resource quota with a deadline.

    ``net_required`` is what must land with the recipient.  ``gross_required``
    is what the fleet must actually send, grossed up for tax.
    """

    order_id: str
    net_required: Mapping[ResourceKind, int]
    issued_at: datetime
    horizon: timedelta
    tax_rate: float = 0.0
    recipient: str | None = None

    def __post_init__(self) -> None:
        if not self.order_id or not isinstance(self.order_id, str):
            raise OrderError("order_id must be non-empty text")
        if self.issued_at.tzinfo is None:
            raise OrderError("issued_at must be timezone-aware")
        if self.horizon <= timedelta(0):
            raise OrderError("horizon must be positive")
        if not 0.0 <= self.tax_rate < 1.0:
            raise OrderError("tax_rate must be in [0, 1)")
        object.__setattr__(
            self, "net_required", _check_amounts(self.net_required, label="net_required")
        )

    @property
    def deadline(self) -> datetime:
        return self.issued_at + self.horizon

    @property
    def gross_required(self) -> dict[ResourceKind, int]:
        """Amounts to send so that ``net_required`` survives the tax.

        Rounded up: delivering a unit short misses the order, delivering a
        unit long does not.
        """
        keep = 1.0 - self.tax_rate
        return {kind: ceil(net / keep) for kind, net in self.net_required.items()}

    def remaining_seconds(self, now: datetime) -> float:
        if now.tzinfo is None:
            raise OrderError("now must be timezone-aware")
        return (self.deadline - now).total_seconds()

    def is_expired(self, now: datetime) -> bool:
        return self.remaining_seconds(now) <= 0.0


@dataclass(frozen=True)
class DeliveryPost:
    """One recorded transfer, bound to the character that made it."""

    character_id: str
    kind: ResourceKind
    gross_amount: int
    posted_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.character_id:
            raise OrderError("character_id must be non-empty text")
        if not isinstance(self.gross_amount, int) or isinstance(self.gross_amount, bool):
            raise OrderError("gross_amount must be an int")
        if self.gross_amount <= 0:
            raise OrderError("gross_amount must be positive")
        if self.posted_at.tzinfo is None:
            raise OrderError("posted_at must be timezone-aware")
        if not self.evidence_ref:
            raise OrderError(
                "evidence_ref must be non-empty - a delivery with no evidence "
                "is not a delivery"
            )


class DeliveryLedger:
    """Append-only record of what the whole fleet has delivered on one order.

    The ledger is the safety mechanism.  Because the game imposes no transfer
    limit, nothing else prevents over-delivery; only an accurate aggregate does.
    """

    def __init__(self, order: Order) -> None:
        self._order = order
        self._posts: list[DeliveryPost] = []

    @property
    def order(self) -> Order:
        return self._order

    @property
    def posts(self) -> tuple[DeliveryPost, ...]:
        return tuple(self._posts)

    def post(self, delivery: DeliveryPost) -> None:
        """Record one verified transfer.

        The caller must already have verified the transfer against the visible
        post-transfer stock; a dispatch receipt alone is not proof.
        """
        if not isinstance(delivery, DeliveryPost):
            raise OrderError("post() takes a DeliveryPost")
        if delivery.kind not in self._order.net_required:
            raise OrderError(
                f"{delivery.kind.value} is not part of order {self._order.order_id}"
            )
        self._posts.append(delivery)

    def delivered_gross(self) -> dict[ResourceKind, int]:
        totals = {kind: 0 for kind in self._order.net_required}
        for post in self._posts:
            totals[post.kind] += post.gross_amount
        return totals

    def delivered_net(self) -> dict[ResourceKind, int]:
        """What the recipient actually keeps, after tax."""
        keep = 1.0 - self._order.tax_rate
        return {kind: int(total * keep) for kind, total in self.delivered_gross().items()}

    def outstanding_net(self) -> dict[ResourceKind, int]:
        """Net still owed per resource.  Zero once a resource is satisfied."""
        received = self.delivered_net()
        return {
            kind: max(0, required - received[kind])
            for kind, required in self._order.net_required.items()
        }

    def outstanding_gross(self) -> dict[ResourceKind, int]:
        """Gross still to send, grossed up for tax."""
        keep = 1.0 - self._order.tax_rate
        return {
            kind: ceil(net / keep) if net > 0 else 0
            for kind, net in self.outstanding_net().items()
        }

    def is_complete(self) -> bool:
        return all(value == 0 for value in self.outstanding_net().values())

    def contribution_by_character(self) -> dict[str, dict[ResourceKind, int]]:
        """Who delivered what - the fleet view the operator asked for."""
        per: dict[str, dict[ResourceKind, int]] = {}
        for post in self._posts:
            per.setdefault(post.character_id, {})
            per[post.character_id][post.kind] = (
                per[post.character_id].get(post.kind, 0) + post.gross_amount
            )
        return per


def shortfall_rate(ledger: DeliveryLedger, now: datetime) -> float:
    """How much net is still owed, per remaining second.

    Used to decide whether the fleet is on pace.  ``inf`` means the deadline
    has passed with work outstanding; ``0.0`` means the order is complete.
    """
    outstanding = sum(ledger.outstanding_net().values())
    if outstanding == 0:
        return 0.0
    remaining = ledger.order.remaining_seconds(now)
    if remaining <= 0:
        return float("inf")
    return outstanding / remaining
