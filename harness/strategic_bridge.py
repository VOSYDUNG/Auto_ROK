"""Where the decision packets go.

``MissionScheduler.decision_packets()`` had no caller anywhere in the
repository - docs/DESIGN_BRIEF.md R1. This module is the caller. It takes the
packets the scheduler builds, joins them to fleet state and the active rung,
and hands the result to ``StrategicPlanner``.

It lives in ``harness`` rather than ``autorok`` because it is the only piece
that touches both sides: the scheduler is harness, the planner is domain.
Keeping the join here means ``autorok.llm`` still imports nothing from the
harness, so the strategic tier stays testable with no game, no capture and no
Windows.

Nothing here emits input. A ``MissionIntent`` is a statement of what to do
next, and turning one into clicks is M7's job - deliberately a separate step,
so the planning loop can run for hours against a live client while the
operator watches, before it is ever allowed to press anything.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from autorok.llm.intent import (
    MissionIntent,
    StrategicSnapshot,
    fleet_summary,
    propose_candidates,
)
from autorok.llm.strategy import StrategicPlanner
from autorok.mission.fleet import Fleet
from autorok.mission.ladder import Ladder
from autorok.mission.order import DeliveryLedger, shortfall_rate
from harness.mission_scheduler import MissionScheduler
from harness.mission_timeline import TaskSignal


def order_summary(ledger: DeliveryLedger, now: datetime) -> dict[str, Any]:
    """The order as progress, not as a target.

    Deliberately reports no ``on_pace`` flag. Whether the fleet is on pace is
    a comparison against a measured delivery rate, and that rate is an M5
    measurement that does not exist yet. A guessed flag here would be read as
    a fact by everything downstream, which is exactly the failure the project
    keeps having to undo - so the numbers are published and the judgement is
    left to whoever has the data.
    """
    remaining = ledger.order.remaining_seconds(now)
    rate = shortfall_rate(ledger, now)
    summary: dict[str, Any] = {
        "order_id": ledger.order.order_id,
        "remaining_hours": round(remaining / 3600.0, 2),
        "expired": ledger.order.is_expired(now),
        "complete": ledger.is_complete(),
        "outstanding_net": {
            kind.value: amount for kind, amount in ledger.outstanding_net().items()
        },
    }
    if rate not in (0.0, float("inf")):
        summary["required_net_per_hour"] = int(rate * 3600)
    return summary


def build_snapshot(
    scheduler: MissionScheduler,
    signals: Sequence[TaskSignal],
    facts: Mapping[str, Any],
    *,
    fleet: Fleet,
    ladder: Ladder,
    now: datetime,
    cycle_id: str,
    ledger: DeliveryLedger | None = None,
    buff_remaining_seconds: float | None = None,
    deliverable_characters: Sequence[str] = (),
) -> StrategicSnapshot:
    """Join the scheduler's packets to fleet state for one planning cycle."""
    packets = scheduler.decision_packets(tuple(signals), facts)
    candidates = propose_candidates(
        fleet=fleet,
        now=now,
        due_packets=packets,
        buff_remaining_seconds=buff_remaining_seconds,
        deliverable_characters=deliverable_characters,
        rung=ladder.current,
    )
    return StrategicSnapshot(
        cycle_id=cycle_id,
        now=now,
        active_goal=ladder.current,
        candidates=candidates,
        order=order_summary(ledger, now) if ledger is not None else None,
        fleet=fleet_summary(fleet, now),
        buff_remaining_seconds=buff_remaining_seconds,
        due_packets=packets,
        degraded_seconds=int(ladder.time_below_top(now).total_seconds()),
    )


def plan_cycle(
    planner: StrategicPlanner,
    scheduler: MissionScheduler,
    signals: Sequence[TaskSignal],
    facts: Mapping[str, Any],
    **kwargs: Any,
) -> tuple[MissionIntent, StrategicSnapshot]:
    """One planning cycle, end to end.

    Returns the snapshot alongside the intent, because a decision that cannot
    be replayed against what was known at the time is not reviewable - the
    same demand the delivery ledger makes with ``evidence_ref``.
    """
    snapshot = build_snapshot(scheduler, signals, facts, **kwargs)
    return planner.plan(snapshot), snapshot


__all__ = ["build_snapshot", "order_summary", "plan_cycle"]
