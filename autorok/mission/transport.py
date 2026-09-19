"""Transport capacity and tax for resource assistance.

Read off the live client on 2026-09-20 from the Resource Assistance panel and
the Trading Post info panel.  The one fact that must not be lost:

    Transportation Capacity is measured in what ARRIVES, not what is sent.

The panel showed capacity 10,000,000/10,000,000 - full - with the food slider
at 10,869,565 and a tax line of -869,565.  10,869,565 minus 869,565 is exactly
10,000,000, and 10,000,000 divided by 0.92 is exactly 10,869,565.

Getting this backwards understates every delivery plan by 8%, and the error is
only visible after the resources have already left the account.

The capacity is a single pool shared by all four resources, not a per-resource
allowance: filling it with food alone left nothing for wood, stone or gold.

Two further facts from the operator on 2026-09-20, both of which changed the
model rather than filling it in:

  * Transport runs occupy the SAME five march slots as gathering - "số xe là 5,
    tùy queue farm của chúng ta có".  There is no second queue.  Every delivery
    run is a farm slot temporarily not farming.
  * The 31 minutes on the observed panel is ONE WAY, and it was a deliberately
    distant test.  A nearby recipient costs at most about 10 seconds each way.

Those two together make teleporting close the highest-leverage action in the
whole delivery job: the same 175 runs per character take about 29 minutes near
and about 90 hours far, on two slots.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Mapping

from autorok.mission.order import ResourceKind


class TransportError(ValueError):
    """Raised when a transport plan violates its contract."""


@dataclass(frozen=True)
class TradingPost:
    """One character's Trading Post, as read from its info panel.

    The tax is held as whole percent because that is how the client states it,
    and because the client's arithmetic is integral - see ``net_from_gross``.
    """

    level: int
    net_capacity: int
    tax_percent: int
    march_speed_bonus_percent: int = 0

    def __post_init__(self) -> None:
        if self.level < 1:
            raise TransportError("trading post level must be at least 1")
        if self.net_capacity <= 0:
            raise TransportError("net_capacity must be positive")
        if not isinstance(self.tax_percent, int) or isinstance(self.tax_percent, bool):
            raise TransportError("tax_percent must be a whole percent")
        if not 0 <= self.tax_percent < 100:
            raise TransportError("tax_percent must be in [0, 100)")

    @property
    def tax_rate(self) -> float:
        """Convenience view. Never use this for money arithmetic."""
        return self.tax_percent / 100

    @property
    def gross_for_full_load(self) -> int:
        """What leaves the sender to deliver one full capacity."""
        return self.gross_for_net(self.net_capacity)

    def tax_on(self, gross: int) -> int:
        """The deduction the client shows for a given send.

        Derived from the observed panel rather than assumed: a slider of
        10,869,565 showed -869,565, and 10,869,565 * 8 // 100 is exactly
        869,565.  The float form ``gross * 0.92`` gives 9,999,999.8 for the
        same input and would be off by one.
        """
        if gross < 0:
            raise TransportError("gross must not be negative")
        return gross * self.tax_percent // 100

    def net_from_gross(self, gross: int) -> int:
        """What arrives when ``gross`` is deducted from the sender."""
        return gross - self.tax_on(gross)

    def gross_for_net(self, net: int) -> int:
        """The smallest amount that must leave the sender so ``net`` arrives.

        Solved exactly rather than by a float division, then walked down,
        because the integer tax means the naive ceiling can overshoot by one.
        """
        if net < 0:
            raise TransportError("net must not be negative")
        if net == 0:
            return 0
        gross = ceil(net * 100 / (100 - self.tax_percent))
        while self.net_from_gross(gross) < net:
            gross += 1
        while gross > 0 and self.net_from_gross(gross - 1) >= net:
            gross -= 1
        return gross

    def runs_for_net(self, net: int) -> int:
        """How many transport runs deliver ``net``.

        Capacity is already a net figure, so this divides by it directly.  A
        common mistake is to gross the target up first and then divide by
        capacity, which inflates the run count by about 8%.
        """
        if net < 0:
            raise TransportError("net must not be negative")
        return ceil(net / self.net_capacity)


#: The operator's current build, read from the client on 2026-09-20.
LEVEL_25 = TradingPost(
    level=25,
    net_capacity=10_000_000,
    tax_percent=8,
    march_speed_bonus_percent=100,
)


@dataclass(frozen=True)
class TransportLoad:
    """One planned run: how much of each resource to put on it.

    All four resources draw on the same capacity pool.
    """

    amounts: Mapping[ResourceKind, int]
    post: TradingPost

    def __post_init__(self) -> None:
        for kind, value in self.amounts.items():
            if not isinstance(kind, ResourceKind):
                raise TransportError(f"{kind!r} is not a ResourceKind")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TransportError(f"amount for {kind} must be a non-negative int")
        if self.net_total > self.post.net_capacity:
            raise TransportError(
                f"load of {self.net_total} exceeds the shared capacity pool of "
                f"{self.post.net_capacity}"
            )

    @property
    def net_total(self) -> int:
        """Delivered total across every resource - one shared pool."""
        return sum(self.amounts.values())

    @property
    def gross_total(self) -> int:
        """Deducted from the sender to deliver this load."""
        return self.post.gross_for_net(self.net_total)

    @property
    def is_full(self) -> bool:
        return self.net_total == self.post.net_capacity


#: Observed one-way travel times.  Distance dominates everything else in the
#: delivery plan, so the plan is built around getting close first.
NEAR_ONE_WAY_SECONDS = 10
OBSERVED_FAR_ONE_WAY_SECONDS = 31 * 60


def travel_seconds(one_way_seconds: int, *, round_trip: bool = True) -> int:
    """Slot occupancy for one transport run."""
    if one_way_seconds <= 0:
        raise TransportError("one_way_seconds must be positive")
    return one_way_seconds * (2 if round_trip else 1)


def campaign_seconds(
    runs: int,
    *,
    one_way_seconds: int = NEAR_ONE_WAY_SECONDS,
    slots: int = 1,
) -> float:
    """How long ``runs`` take when ``slots`` of the five are given to transport.

    This is the number that decides whether a delivery is a coffee break or a
    multi-day campaign, and it is driven almost entirely by distance.
    """
    if runs < 0:
        raise TransportError("runs must not be negative")
    if not 1 <= slots <= 5:
        raise TransportError("slots must be between 1 and 5 - the shared march pool")
    if runs == 0:
        return 0.0
    return runs * travel_seconds(one_way_seconds) / slots


def plan_runs(
    outstanding_net: Mapping[ResourceKind, int],
    post: TradingPost = LEVEL_25,
) -> list[TransportLoad]:
    """Fill runs from what the order still owes.

    Resources are packed in descending order of outstanding amount, so the
    largest debts clear first and partial runs land at the end rather than
    scattered through the campaign.
    """
    remaining = {
        kind: int(value)
        for kind, value in outstanding_net.items()
        if int(value) > 0
    }
    for kind, value in remaining.items():
        if value < 0:
            raise TransportError(f"outstanding for {kind} must not be negative")

    runs: list[TransportLoad] = []
    while remaining:
        load: dict[ResourceKind, int] = {}
        free = post.net_capacity
        for kind in sorted(remaining, key=lambda k: (-remaining[k], k.value)):
            if free == 0:
                break
            take = min(free, remaining[kind])
            load[kind] = take
            free -= take
        runs.append(TransportLoad(amounts=load, post=post))
        for kind, taken in load.items():
            remaining[kind] -= taken
            if remaining[kind] == 0:
                del remaining[kind]
    return runs
