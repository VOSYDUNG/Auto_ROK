"""What the strategic tier is allowed to decide, and what it is shown.

``MissionScheduler.decision_packets()` has been building packets and throwing
them away - docs/DESIGN_BRIEF.md R1. Nothing in the repository consumed them,
so the tier where a model is actually worth its latency had never once run.

This module is the missing half of that contract. It defines the candidate
set, the answer shape, and the snapshot the model is shown - all of it built
by the harness, none of it invented by the model.

The shape mirrors the tactical tier on purpose, because the safety property is
the same one: a model names an identifier, and the identifier is resolved back
to an object the harness already created. It cannot describe an action; it can
only point at one of ours.

The difference is time. Tactically a decision is worth seconds; here the fleet
is waiting hours for marches to come home, so a twenty-second answer costs
nothing. That is the whole reason this tier is where the model belongs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from autorok.llm.boundary import strip_forbidden
from autorok.mission.fleet import Fleet
from autorok.mission.ladder import Rung


class IntentError(ValueError):
    """Raised when an intent or a candidate violates its contract."""


class IntentKind(str, Enum):
    """The strategic moves the harness knows how to carry out.

    Closed on purpose. A kind the harness cannot execute is not a decision,
    it is a wish, and offering one as a candidate would let the model steer
    the fleet somewhere the harness cannot follow.
    """

    ENTER_CHARACTER = "ENTER_CHARACTER"
    CLAIM_DAILY = "CLAIM_DAILY"
    TOP_UP_BUFF = "TOP_UP_BUFF"
    DELIVER_ORDER = "DELIVER_ORDER"
    HOLD = "HOLD"


#: Order the harness falls back on when it must choose without the model.
#:
#: HYPOTHESIS, awaiting the M5 measurements - docs/BUILD_PLAN.md states it and
#: states that data may refute it: a march slot is PERISHABLE. An hour with an
#: empty slot is an hour of gathering that can never be recovered, whereas a
#: VIP chest is still there an hour later. So sending marches outranks daily
#: chores, and the buff comes second because both cycle baselines assume it.
FALLBACK_PRIORITY: tuple[IntentKind, ...] = (
    IntentKind.ENTER_CHARACTER,
    IntentKind.TOP_UP_BUFF,
    IntentKind.DELIVER_ORDER,
    IntentKind.CLAIM_DAILY,
    IntentKind.HOLD,
)

#: Below this much buff left, topping up becomes a candidate. Both operator
#: baselines (2h15 and 3h45) assume the 50% gathering buff is live, so letting
#: it lapse does not merely slow one march - it invalidates every cycle
#: estimate the day's schedule was built from.
BUFF_LOW_SECONDS = 15 * 60


class DecidedBy(str, Enum):
    """Who chose - kept on every intent so a session can be read back.

    Without this, a run where the model was down all night is indistinguishable
    from one where it chose every step, and ``local_llm_entries_per_100_ticks``
    becomes unmeasurable.
    """

    MODEL = "MODEL"
    HARNESS_ONLY_OPTION = "HARNESS_ONLY_OPTION"
    HARNESS_FALLBACK = "HARNESS_FALLBACK"


@dataclass(frozen=True)
class IntentCandidate:
    """One strategic move the harness has already checked it can perform."""

    intent_id: str
    kind: IntentKind
    character_id: str | None = None
    task_id: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.intent_id or not self.intent_id.strip():
            raise IntentError("intent_id must be non-empty text")
        if not isinstance(self.kind, IntentKind):
            raise IntentError("kind must be an IntentKind")
        if self.kind is IntentKind.ENTER_CHARACTER and not self.character_id:
            raise IntentError("ENTER_CHARACTER must name the character to enter")
        if self.kind is IntentKind.CLAIM_DAILY and not self.task_id:
            raise IntentError("CLAIM_DAILY must name the task to claim")

    def as_payload(self) -> dict[str, Any]:
        """The candidate as the model sees it - identifiers, never geometry."""
        payload: dict[str, Any] = {"intent_id": self.intent_id, "kind": self.kind.value}
        if self.character_id:
            payload["character_id"] = self.character_id
        if self.task_id:
            payload["task_id"] = self.task_id
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True)
class MissionIntent:
    """The decision, bound to a candidate the harness built."""

    candidate: IntentCandidate
    reason: str
    decided_by: DecidedBy

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, IntentCandidate):
            raise IntentError("a MissionIntent must carry a real IntentCandidate")
        if not self.reason or not self.reason.strip():
            raise IntentError(
                "an intent without a reason cannot be reviewed later; the "
                "ladder makes the same demand of a demotion"
            )

    @property
    def intent_id(self) -> str:
        return self.candidate.intent_id

    @property
    def kind(self) -> IntentKind:
        return self.candidate.kind

    def summarise(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "kind": self.kind.value,
            "character_id": self.candidate.character_id,
            "task_id": self.candidate.task_id,
            "reason": self.reason,
            "decided_by": self.decided_by.value,
        }


def unique_candidates(candidates: Iterable[IntentCandidate]) -> tuple[IntentCandidate, ...]:
    """Reject a duplicate ``intent_id`` before it ever reaches the model.

    Two candidates under one identifier would make the model's answer
    ambiguous, and ``exactly_one`` would then refuse a perfectly reasonable
    reply. Catching it here names the real culprit - the builder.
    """
    result: list[IntentCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.intent_id in seen:
            raise IntentError(
                f"duplicate intent_id {candidate.intent_id!r}; a candidate set "
                "with two identical keys cannot be resolved"
            )
        seen.add(candidate.intent_id)
        result.append(candidate)
    return tuple(result)


#: Signal statuses the strategic tier is allowed to be asked about. The other
#: statuses are ones the deterministic timeline has already settled.
DECIDABLE_STATUSES = frozenset({"NEEDS_DECISION", "UNKNOWN_STATE"})


def propose_candidates(
    *,
    fleet: Fleet,
    now: datetime,
    due_packets: Sequence[Mapping[str, Any]] = (),
    buff_remaining_seconds: float | None = None,
    deliverable_characters: Sequence[str] = (),
    rung: Rung = Rung.ORDER_WORK,
) -> tuple[IntentCandidate, ...]:
    """Everything the harness could do right now, from fleet state.

    Deterministic and side-effect free. The model never adds to this list; it
    only picks from it, which is what makes the answer safe to execute.

    An empty result is normal, not a failure: every character is in the field
    and the right move is to wait. The caller turns that into an explicit HOLD
    rather than calling a model to be told nothing can be done.
    """
    if now.tzinfo is None:
        raise IntentError("now must be timezone-aware")

    candidates: list[IntentCandidate] = []

    if rung.emits_input:
        for character in fleet.characters:
            if not character.is_eligible(now) or character.free_slots <= 0:
                continue
            candidates.append(
                IntentCandidate(
                    intent_id=f"ENTER:{character.character_id}",
                    kind=IntentKind.ENTER_CHARACTER,
                    character_id=character.character_id,
                    note=f"{character.free_slots} free march slots",
                )
            )

        if buff_remaining_seconds is not None and buff_remaining_seconds <= BUFF_LOW_SECONDS:
            candidates.append(
                IntentCandidate(
                    intent_id="TOP_UP_BUFF",
                    kind=IntentKind.TOP_UP_BUFF,
                    note=f"{int(buff_remaining_seconds)}s of gathering buff left",
                )
            )

        if rung is Rung.ORDER_WORK:
            # Delivery is only ever a candidate while an operator order is the
            # active goal. Below that rung the fleet has already told us it is
            # struggling to farm, and a transport run spends a farm slot.
            for character_id in deliverable_characters:
                candidates.append(
                    IntentCandidate(
                        intent_id=f"DELIVER:{character_id}",
                        kind=IntentKind.DELIVER_ORDER,
                        character_id=character_id,
                        note="stock available to send toward the order",
                    )
                )

        for packet in due_packets:
            if packet.get("status") not in DECIDABLE_STATUSES:
                continue
            task_id = packet.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            character_id = packet.get("character_id")
            suffix = f":{character_id}" if character_id else ""
            candidates.append(
                IntentCandidate(
                    intent_id=f"DAILY:{task_id}{suffix}",
                    kind=IntentKind.CLAIM_DAILY,
                    character_id=character_id if isinstance(character_id, str) else None,
                    task_id=task_id,
                    note=str(packet.get("reason") or ""),
                )
            )

    return unique_candidates(candidates)


def fallback_choice(candidates: Sequence[IntentCandidate]) -> IntentCandidate | None:
    """The move to make when the model is unavailable or abstains.

    Deterministic, and ordered by FALLBACK_PRIORITY. The loop-level rule is
    that it never stops, so "the model is down" cannot be allowed to mean "no
    decision" - it means the harness decides by itself and says so.
    """
    for kind in FALLBACK_PRIORITY:
        matching = [item for item in candidates if item.kind is kind]
        if matching:
            # Stable within a kind, so two identical fleet states produce the
            # same plan and a session stays replayable.
            return sorted(matching, key=lambda item: item.intent_id)[0]
    return None


@dataclass(frozen=True)
class StrategicSnapshot:
    """Everything the model is shown for one planning cycle.

    Built from fleet state and already-filtered packets. ``as_payload`` runs
    the boundary denylist over the finished structure as a last line - the
    first line is that nothing geometric is put in here to begin with.
    """

    cycle_id: str
    now: datetime
    active_goal: Rung
    candidates: tuple[IntentCandidate, ...]
    order: Mapping[str, Any] | None = None
    fleet: Mapping[str, Any] = field(default_factory=dict)
    buff_remaining_seconds: float | None = None
    due_packets: tuple[Mapping[str, Any], ...] = ()
    degraded_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.cycle_id:
            raise IntentError("cycle_id must be non-empty text")
        if self.now.tzinfo is None:
            raise IntentError("now must be timezone-aware")
        unique_candidates(self.candidates)

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "cycle_id": self.cycle_id,
            "observed_at": self.now.isoformat(),
            "active_goal": self.active_goal.name,
            "seconds_below_top_goal": self.degraded_seconds,
            "fleet": dict(self.fleet),
            "candidates": [item.as_payload() for item in self.candidates],
        }
        if self.order is not None:
            payload["order"] = dict(self.order)
        if self.buff_remaining_seconds is not None:
            payload["buff"] = {
                "gather_speed_remaining_seconds": int(self.buff_remaining_seconds)
            }
        if self.due_packets:
            payload["due_tasks"] = [dict(packet) for packet in self.due_packets]
        return strip_forbidden(payload)


def fleet_summary(fleet: Fleet, now: datetime) -> dict[str, Any]:
    """The fleet as a handful of numbers, with no character geometry.

    ``queue_occupancy`` is fleet-level deliberately. One character necessarily
    dips as its batch drains; the thing that should stay saturated is the
    fleet, and that is the number a strategic decision turns on.
    """
    eligible = [
        character.character_id
        for character in fleet.characters
        if character.is_eligible(now)
    ]
    summary: dict[str, Any] = {
        "queue_occupancy": round(fleet.queue_occupancy(), 4),
        "occupied_slots": fleet.occupied_slots(),
        "total_slots": fleet.total_slots,
        "eligible_characters": eligible,
    }
    # Zero when somebody is available now. ``Fleet.next_eligible_at`` answers a
    # different question - when the next BATCH lands - and it ignores idle
    # characters entirely, so reporting it here would tell the model to wait
    # two hours while a character sits ready.
    next_at = fleet.next_eligible_at()
    if eligible or next_at is None or next_at <= now:
        summary["next_eligible_in_seconds"] = 0
    else:
        summary["next_eligible_in_seconds"] = int((next_at - now).total_seconds())
    return summary


__all__ = [
    "BUFF_LOW_SECONDS",
    "DECIDABLE_STATUSES",
    "FALLBACK_PRIORITY",
    "DecidedBy",
    "IntentCandidate",
    "IntentError",
    "IntentKind",
    "MissionIntent",
    "StrategicSnapshot",
    "fallback_choice",
    "fleet_summary",
    "propose_candidates",
    "unique_candidates",
]
