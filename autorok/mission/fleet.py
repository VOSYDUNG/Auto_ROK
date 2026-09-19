"""The farm fleet: accounts, characters, march batches and rotation.

The operator's process, not a UI sequence:

    One character holds five march slots.  All five go out, and the character
    is re-entered only when all five are home.  The five do not return
    together, so the cycle is amortised against the SLOWEST march.  The idle
    tail at the end of a batch is not covered by re-entering early - it is
    covered by rotating to the next character.

Rotation is two-level: characters inside a signed-in account first, then the
account itself once every character is exhausted.  Scale is a runtime input;
nothing here assumes 2x4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Sequence

from autorok.mission.order import ResourceKind


class FleetError(ValueError):
    """Raised when fleet state or a transition violates its contract."""


MARCHES_PER_CHARACTER = 5


class CycleSource(str, Enum):
    """Where a character's cycle estimate came from.

    Keeping this explicit is the point: the operator's baseline lets the
    scheduler run on day one, but it must be visibly distinguishable from a
    value the harness actually measured.
    """

    OPERATOR_BASELINE = "OPERATOR_BASELINE"
    MEASURED = "MEASURED"


@dataclass(frozen=True)
class CycleEstimate:
    """How long one full five-march batch takes for one character."""

    duration: timedelta
    source: CycleSource
    assumes_gather_buff: bool = True
    sample_count: int = 0

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise FleetError("cycle duration must be positive")
        if self.source is CycleSource.MEASURED and self.sample_count < 1:
            raise FleetError("a measured cycle needs at least one sample")


#: Operator's own farming experience, 2026-09-19.  Both figures assume the
#: 50% gathering buff is live - if it lapses the cycle stretches and any
#: schedule built on these numbers is wrong.
OPERATOR_BASELINE_STRONG = CycleEstimate(
    duration=timedelta(hours=2, minutes=15), source=CycleSource.OPERATOR_BASELINE
)
OPERATOR_BASELINE_WEAK = CycleEstimate(
    duration=timedelta(hours=3, minutes=45), source=CycleSource.OPERATOR_BASELINE
)


class MarchPurpose(str, Enum):
    """What a march slot is being used for.

    Gathering and resource transport draw on the SAME five slots - the
    operator: "số xe là 5, tùy queue farm của chúng ta có".  There is no
    separate transport queue, so every delivery run is a farm slot not being
    used to farm.
    """

    GATHER = "GATHER"
    TRANSPORT = "TRANSPORT"


@dataclass(frozen=True)
class March:
    """One occupied march slot - gathering or transporting."""

    slot: int
    kind: ResourceKind | None
    dispatched_at: datetime
    expected_home_at: datetime
    purpose: MarchPurpose = MarchPurpose.GATHER

    def __post_init__(self) -> None:
        if not 0 <= self.slot < MARCHES_PER_CHARACTER:
            raise FleetError(f"slot must be in 0..{MARCHES_PER_CHARACTER - 1}")
        if self.dispatched_at.tzinfo is None or self.expected_home_at.tzinfo is None:
            raise FleetError("march timestamps must be timezone-aware")
        if self.expected_home_at <= self.dispatched_at:
            raise FleetError("expected_home_at must be after dispatched_at")
        if self.purpose is MarchPurpose.GATHER and self.kind is None:
            raise FleetError("a gathering march must name the resource it gathers")
        if self.purpose is MarchPurpose.TRANSPORT and self.kind is not None:
            raise FleetError(
                "a transport run carries a shared load, so it must not name a "
                "single resource - see autorok.mission.transport.TransportLoad"
            )


@dataclass
class Character:
    """One farming governor with five march slots."""

    character_id: str
    account_id: str
    cycle: CycleEstimate
    marches: list[March] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.character_id or not self.account_id:
            raise FleetError("character_id and account_id must be non-empty text")

    @property
    def free_slots(self) -> int:
        return MARCHES_PER_CHARACTER - len(self.marches)

    @property
    def is_queue_full(self) -> bool:
        return self.free_slots == 0

    def slots_used_for(self, purpose: MarchPurpose) -> int:
        """How many of the five slots are committed to one purpose.

        Transport and gathering contend for the same pool, so a delivery
        campaign is visible here as gathering capacity temporarily given up.
        """
        return sum(1 for march in self.marches if march.purpose is purpose)

    def dispatch(self, march: March) -> None:
        if self.is_queue_full:
            raise FleetError(f"{self.character_id} has no free march slot")
        if any(existing.slot == march.slot for existing in self.marches):
            raise FleetError(f"slot {march.slot} of {self.character_id} is occupied")
        self.marches.append(march)

    def batch_home_at(self) -> datetime | None:
        """When the LAST march returns - the figure the cycle amortises against.

        ``None`` when nothing is in the field.
        """
        if not self.marches:
            return None
        return max(march.expected_home_at for march in self.marches)

    def is_eligible(self, now: datetime) -> bool:
        """A character is re-entered only when every march is home."""
        home_at = self.batch_home_at()
        if home_at is None:
            return True
        return now >= home_at

    def collect_returned(self, now: datetime) -> list[March]:
        """Remove and return marches that are home as of ``now``."""
        returned = [march for march in self.marches if march.expected_home_at <= now]
        self.marches = [march for march in self.marches if march.expected_home_at > now]
        return returned

    def idle_tail(self) -> timedelta:
        """How long the earliest slot sits idle waiting for the slowest one.

        This is the measured cost of the batch process, and the quantity the
        rotation is meant to absorb.
        """
        if len(self.marches) < 2:
            return timedelta(0)
        arrivals = [march.expected_home_at for march in self.marches]
        return max(arrivals) - min(arrivals)


@dataclass
class Account:
    """A signed-in account holding several farming characters."""

    account_id: str
    characters: list[Character] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.account_id:
            raise FleetError("account_id must be non-empty text")
        for character in self.characters:
            if character.account_id != self.account_id:
                raise FleetError(
                    f"{character.character_id} belongs to {character.account_id}, "
                    f"not {self.account_id}"
                )

    def eligible(self, now: datetime) -> list[Character]:
        return [character for character in self.characters if character.is_eligible(now)]


class Fleet:
    """Every account and character the operator runs.

    Rotation order is two-level and deliberately exhausts the current account's
    characters before moving on, because switching character inside an account
    is cheap while switching account is not.
    """

    def __init__(self, accounts: Sequence[Account]) -> None:
        if not accounts:
            raise FleetError("a fleet needs at least one account")
        seen: set[str] = set()
        for account in accounts:
            if account.account_id in seen:
                raise FleetError(f"duplicate account {account.account_id}")
            seen.add(account.account_id)
        self._accounts = list(accounts)

    @property
    def accounts(self) -> tuple[Account, ...]:
        return tuple(self._accounts)

    @property
    def characters(self) -> tuple[Character, ...]:
        return tuple(c for account in self._accounts for c in account.characters)

    @property
    def total_slots(self) -> int:
        return len(self.characters) * MARCHES_PER_CHARACTER

    def occupied_slots(self) -> int:
        return sum(len(character.marches) for character in self.characters)

    def queue_occupancy(self) -> float:
        """Fraction of the fleet's march slots currently in the field.

        This is the fleet-level reading of "keep the queue full".  A single
        character necessarily dips as its batch drains; the fleet is what
        should stay saturated.
        """
        total = self.total_slots
        return self.occupied_slots() / total if total else 0.0

    def next_character(self, now: datetime, *, current_account_id: str | None = None) -> Character | None:
        """The next character to enter, preferring the account already open.

        Returns ``None`` when nothing is eligible yet - which is a normal
        waiting state, not an error.
        """
        ordered = self._accounts
        if current_account_id is not None:
            ordered = sorted(
                self._accounts, key=lambda a: a.account_id != current_account_id
            )
        for account in ordered:
            eligible = account.eligible(now)
            if eligible:
                # Prefer whichever eligible character has the most free slots,
                # so a partially drained queue is topped up before a full one.
                return max(eligible, key=lambda c: c.free_slots)
        return None

    def next_eligible_at(self) -> datetime | None:
        """When the first character becomes re-enterable.

        ``None`` means one is eligible right now, or the fleet is idle.
        """
        pending = [
            character.batch_home_at()
            for character in self.characters
            if character.batch_home_at() is not None
        ]
        return min(pending) if pending else None
