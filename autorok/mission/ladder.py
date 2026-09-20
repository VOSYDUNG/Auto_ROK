"""The degradation ladder: fail closed on an action, never stop the loop.

The operator's rule: "tôi tác động nó thay đổi các quyết định thôi chứ không
làm nó dừng vận hành" - operator input changes what the agent decides, it does
not stop it running.

That sits against a harness built to halt on any uncertainty. The two are
reconciled by separating the levels:

    action level   fail closed. Cannot ground it, cannot get approval, do not
                   press it.
    loop level     never stop. A blocked action demotes to a weaker goal.

The legacy Mouse_key.py had neither property - it could not verify an action
and it could not degrade - so every exception froze the whole lifecycle.

A rung is always active. There is no "no goal" state, and no way to construct
one: the floor is OBSERVE_ONLY, which still watches and still records.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Iterator, Sequence


class LadderError(ValueError):
    """Raised when a transition would break the ladder's contract."""


class Rung(IntEnum):
    """Goals from strongest to weakest.

    Ordered on purpose: demotion is a step of exactly one, and "how far down
    are we" is a subtraction rather than a lookup table.
    """

    ORDER_WORK = 0
    DEFAULT_FARM = 1
    SCARCITY_FILL = 2
    DAILY_CITIZEN = 3
    OBSERVE_ONLY = 4

    @property
    def emits_input(self) -> bool:
        """Whether this goal may press anything at all."""
        return self is not Rung.OBSERVE_ONLY


#: What each rung is for, in one line, so a log entry explains itself.
PURPOSE: dict[Rung, str] = {
    Rung.ORDER_WORK: "work the quota the operator issued",
    Rung.DEFAULT_FARM: "farm the 1:1:1:2 ratio, high node levels first",
    Rung.SCARCITY_FILL: "drop level and type preference, just fill the queue",
    Rung.DAILY_CITIZEN: "VIP, gifts, courier station, alliance donation",
    Rung.OBSERVE_ONLY: "watch and record; emit no input",
}


@dataclass(frozen=True)
class Transition:
    """One move on the ladder, with the reason that caused it."""

    previous: Rung
    current: Rung
    reason: str
    at: datetime

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise LadderError(
                "a transition without a reason cannot be reviewed later, and a "
                "ladder nobody can review is just a silent failure"
            )
        if self.at.tzinfo is None:
            raise LadderError("transition timestamps must be timezone-aware")

    @property
    def is_demotion(self) -> bool:
        return self.current > self.previous


class Ladder:
    """The active goal, and how it got there."""

    def __init__(self, start: Rung = Rung.ORDER_WORK) -> None:
        if not isinstance(start, Rung):
            raise LadderError("start must be a Rung")
        self._current = start
        self._history: list[Transition] = []

    @property
    def current(self) -> Rung:
        """Never None. There is always a goal."""
        return self._current

    @property
    def history(self) -> tuple[Transition, ...]:
        return tuple(self._history)

    @property
    def at_floor(self) -> bool:
        return self._current is Rung.OBSERVE_ONLY

    @property
    def depth(self) -> int:
        """How many rungs below the top."""
        return int(self._current) - int(Rung.ORDER_WORK)

    def demote(self, reason: str, *, at: datetime) -> Transition:
        """Step down exactly one rung.

        One rung, never several. Skipping would hide which goal was tried and
        why it failed, and that chain is the only record of what the kingdom
        was doing at the time.

        At the floor this records the attempt and stays put: OBSERVE_ONLY is
        still a goal, so refusing here would create the "no goal" state the
        whole design forbids.
        """
        previous = self._current
        target = previous if previous is Rung.OBSERVE_ONLY else Rung(int(previous) + 1)
        transition = Transition(previous=previous, current=target, reason=reason, at=at)
        self._current = target
        self._history.append(transition)
        return transition

    def promote(self, reason: str, *, at: datetime) -> Transition:
        """Step back up one rung once the blocker clears.

        Also one rung at a time. Jumping straight back to ORDER_WORK after a
        long scarcity would assume the whole chain of blockers cleared at once.
        """
        previous = self._current
        target = previous if previous is Rung.ORDER_WORK else Rung(int(previous) - 1)
        transition = Transition(previous=previous, current=target, reason=reason, at=at)
        self._current = target
        self._history.append(transition)
        return transition

    def reset(self, reason: str, *, at: datetime) -> Transition:
        """Return to the top, for a new occurrence rather than a recovery."""
        previous = self._current
        transition = Transition(
            previous=previous, current=Rung.ORDER_WORK, reason=reason, at=at
        )
        self._current = Rung.ORDER_WORK
        self._history.append(transition)
        return transition

    def time_below_top(self, now: datetime) -> timedelta:
        """How long the agent has been off ORDER_WORK.

        A long stretch down the ladder is evidence about the kingdom, not a
        harness fault, and it is what the local LLM should be told about
        rather than the harness absorbing it silently.
        """
        if self._current is Rung.ORDER_WORK:
            return timedelta(0)
        for transition in reversed(self._history):
            if transition.previous is Rung.ORDER_WORK and transition.is_demotion:
                return now - transition.at
        return timedelta(0)

    def demotions_since(self, since: datetime) -> tuple[Transition, ...]:
        return tuple(
            item for item in self._history if item.is_demotion and item.at >= since
        )

    def __iter__(self) -> Iterator[Transition]:
        return iter(self._history)


def is_persistently_degraded(
    ladder: Ladder,
    now: datetime,
    *,
    threshold: timedelta = timedelta(hours=1),
) -> bool:
    """Whether the degradation has lasted long enough to be worth reporting.

    A single scarce search is ordinary. An hour of it says something about the
    kingdom, and that is a fact for the decision edge rather than noise for
    the log.
    """
    return ladder.time_below_top(now) >= threshold


def summarise(ladder: Ladder, now: datetime) -> dict[str, object]:
    """A packet-sized view of the ladder, safe to hand to a model."""
    return {
        "rung": ladder.current.name,
        "purpose": PURPOSE[ladder.current],
        "depth": ladder.depth,
        "emits_input": ladder.current.emits_input,
        "seconds_below_top": int(ladder.time_below_top(now).total_seconds()),
        "last_reason": ladder.history[-1].reason if ladder.history else None,
    }


__all__ = [
    "PURPOSE",
    "Ladder",
    "LadderError",
    "Rung",
    "Transition",
    "is_persistently_degraded",
    "summarise",
]
