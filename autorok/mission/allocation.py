"""Deciding which resource each free march slot should gather.

Two modes, and the second one is the point.

NORMAL mode holds the operator's 1:1:1:2 ratio and searches node levels from
high to low, because higher nodes yield more per march.

SCARCITY mode is the project's first stated graceful-degradation rule.  In a
competitive kingdom a search can simply return nothing.  The operator's rule:
drop the level requirement, relax the resource preference, and just fill the
queue - "có gửi troop đi farm là được".  A march on a poor node beats an idle
slot.

This is the pattern that separates the agent from the legacy script.  The old
Daily_farm had one plan and froze when it failed.  Here a blocked preference
demotes to a weaker goal instead of halting the loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from autorok.mission.order import DEFAULT_RATIO, ResourceKind


class AllocationError(ValueError):
    """Raised when an allocation request violates its contract."""


class AllocationMode(str, Enum):
    NORMAL = "NORMAL"
    SCARCITY = "SCARCITY"


@dataclass(frozen=True)
class SlotAssignment:
    """What one free march slot should go and gather."""

    kind: ResourceKind
    min_node_level: int
    mode: AllocationMode
    reason: str

    def __post_init__(self) -> None:
        if self.min_node_level < 1:
            raise AllocationError("min_node_level must be at least 1")


def _normalise_ratio(ratio: Mapping[ResourceKind, int]) -> dict[ResourceKind, int]:
    if not ratio:
        raise AllocationError("ratio must name at least one resource")
    cleaned: dict[ResourceKind, int] = {}
    for kind, weight in ratio.items():
        if not isinstance(kind, ResourceKind):
            raise AllocationError(f"ratio key {kind!r} is not a ResourceKind")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
            raise AllocationError(f"ratio[{kind}] must be a non-negative int")
        if weight:
            cleaned[kind] = weight
    if not cleaned:
        raise AllocationError("ratio must give at least one resource a positive weight")
    return cleaned


def allocate_by_ratio(
    free_slots: int,
    *,
    ratio: Mapping[ResourceKind, int] = DEFAULT_RATIO,
    in_flight: Mapping[ResourceKind, int] | None = None,
) -> list[ResourceKind]:
    """Assign ``free_slots`` resources so the fleet trends toward ``ratio``.

    ``in_flight`` is what is already being gathered, so a partially drained
    queue is topped up toward the target mix rather than reset to it.  The
    method is largest-remainder against the combined total, which keeps the
    long-run mix on ratio without oscillating.
    """
    if not isinstance(free_slots, int) or isinstance(free_slots, bool):
        raise AllocationError("free_slots must be an int")
    if free_slots < 0:
        raise AllocationError("free_slots must not be negative")
    if free_slots == 0:
        return []

    weights = _normalise_ratio(ratio)
    current = {kind: 0 for kind in weights}
    for kind, count in (in_flight or {}).items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AllocationError(f"in_flight[{kind}] must be a non-negative int")
        if kind in current:
            current[kind] += count

    total_weight = sum(weights.values())
    total_after = sum(current.values()) + free_slots

    # Ideal count each resource should hold once these slots are filled.
    ideal = {kind: total_after * weight / total_weight for kind, weight in weights.items()}
    deficit = {kind: ideal[kind] - current[kind] for kind in weights}

    assignments: list[ResourceKind] = []
    for _ in range(free_slots):
        # Award the slot to whichever resource is furthest below its ideal.
        # Ties break on the higher ratio weight, then on name, so the result
        # is deterministic.
        kind = max(deficit, key=lambda k: (deficit[k], weights[k], k.value))
        assignments.append(kind)
        deficit[kind] -= 1.0
    return assignments


def plan_slots(
    free_slots: int,
    *,
    available_levels: Sequence[int],
    ratio: Mapping[ResourceKind, int] = DEFAULT_RATIO,
    in_flight: Mapping[ResourceKind, int] | None = None,
    preferred_min_level: int = 1,
    scarcity_floor_level: int = 1,
) -> list[SlotAssignment]:
    """Plan every free slot, degrading to SCARCITY when nodes run out.

    ``available_levels`` is what the search surface actually returned for this
    frame - descending node levels the client is offering.  An empty sequence
    means the kingdom is picked clean right now, which is a normal condition
    in a competitive server, not a failure.
    """
    if free_slots < 0:
        raise AllocationError("free_slots must not be negative")
    if preferred_min_level < 1 or scarcity_floor_level < 1:
        raise AllocationError("level floors must be at least 1")
    if scarcity_floor_level > preferred_min_level:
        raise AllocationError(
            "scarcity_floor_level must not exceed preferred_min_level - "
            "degrading must relax the requirement, never tighten it"
        )
    if free_slots == 0:
        return []

    usable = sorted((int(level) for level in available_levels), reverse=True)
    preferred = [level for level in usable if level >= preferred_min_level]

    kinds = allocate_by_ratio(free_slots, ratio=ratio, in_flight=in_flight)

    plan: list[SlotAssignment] = []
    for index, kind in enumerate(kinds):
        if index < len(preferred):
            plan.append(
                SlotAssignment(
                    kind=kind,
                    min_node_level=preferred[index],
                    mode=AllocationMode.NORMAL,
                    reason="preferred node available at or above the target level",
                )
            )
        else:
            # Degrade rather than leave the slot idle.
            plan.append(
                SlotAssignment(
                    kind=kind,
                    min_node_level=scarcity_floor_level,
                    mode=AllocationMode.SCARCITY,
                    reason=(
                        "no node at the preferred level; filling the slot is "
                        "worth more than holding out for the preferred resource"
                    ),
                )
            )
    return plan


def is_degraded(plan: Sequence[SlotAssignment]) -> bool:
    """True when any slot had to fall back.

    Worth surfacing: a persistently degraded plan is evidence about the
    kingdom, and it is exactly the kind of change the local LLM should be
    told about rather than the harness silently absorbing it.
    """
    return any(item.mode is AllocationMode.SCARCITY for item in plan)
