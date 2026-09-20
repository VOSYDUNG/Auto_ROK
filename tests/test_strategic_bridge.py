"""The packets reach a consumer - SRS LLM-006, end to end.

Before this, ``MissionScheduler.decision_packets()`` had no caller anywhere.
These tests run the real scheduler against the real mission-layer config, so
they fail if the strategic tier ever quietly becomes a producer again.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from autorok.llm.intent import DecidedBy, IntentKind
from autorok.llm.strategy import StrategicPlanner
from autorok.mission.fleet import (
    OPERATOR_BASELINE_STRONG,
    Account,
    Character,
    Fleet,
    March,
    MarchPurpose,
)
from autorok.mission.ladder import Ladder, Rung
from autorok.mission.order import (
    DeliveryLedger,
    DeliveryPost,
    Order,
    ResourceKind,
)
from harness.mission_knowledge import SQLiteMissionKnowledgeStore
from harness.mission_scheduler import MissionScheduler
from harness.mission_timeline import load_timeline_config
from harness.strategic_bridge import build_snapshot, order_summary, plan_cycle

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NOW = datetime(2026, 9, 20, 7, 0, tzinfo=UTC)

FACTS = {
    "vip": {"claim_available": True, "gifts_available": False},
    "courier_station": {"free_claim_available": False, "items_available": True},
    "farm": {"queue_used": 1, "queue_capacity": 2, "marches": []},
    # Geometry the harness legitimately holds, and which must not survive the
    # trip into a model payload.
    "frame_bbox": {"x": 1},
    "client_window_rect": [0, 0, 1920, 1080],
}


def _fleet(*, busy: bool) -> Fleet:
    idle = Character("char-idle", "acc-0", OPERATOR_BASELINE_STRONG)
    if busy:
        for slot in range(5):
            idle.dispatch(
                March(
                    slot=slot,
                    kind=ResourceKind.FOOD,
                    dispatched_at=NOW - timedelta(minutes=30),
                    expected_home_at=NOW + timedelta(hours=2),
                    purpose=MarchPurpose.GATHER,
                )
            )
    return Fleet([Account("acc-0", [idle])])


def _ledger() -> DeliveryLedger:
    order = Order(
        order_id="ord-1",
        net_required={ResourceKind.FOOD: 1_000_000, ResourceKind.GOLD: 2_000_000},
        issued_at=NOW - timedelta(hours=10),
        horizon=timedelta(days=30),
        tax_rate=0.08,
    )
    ledger = DeliveryLedger(order)
    ledger.post(
        DeliveryPost(
            character_id="char-idle",
            kind=ResourceKind.FOOD,
            gross_amount=500_000,
            posted_at=NOW - timedelta(hours=1),
            evidence_ref="frames/deliver-1.png",
        )
    )
    return ledger


def _scheduler(store):
    return MissionScheduler(load_timeline_config(ROOT / "config" / "mission_layer.yaml"), store)


def test_a_real_scheduler_pass_produces_a_snapshot_the_planner_can_answer():
    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = _scheduler(store)
        signals = scheduler.tick(character_id="char-idle", now=NOW, facts=FACTS, frame_id="f1")
        planner = StrategicPlanner(None)
        intent, snapshot = plan_cycle(
            planner,
            scheduler,
            signals,
            FACTS,
            fleet=_fleet(busy=False),
            ladder=Ladder(),
            now=NOW,
            cycle_id="cycle-1",
            ledger=_ledger(),
        )

    # The packets the scheduler built are carried, not discarded.
    assert snapshot.due_packets
    assert {packet["task_id"] for packet in snapshot.due_packets} == {
        "BUY_COURIER_ITEM",
        "ALLIANCE_CONTRIBUTION",
    }
    # And they became candidates alongside the fleet move.
    kinds = {candidate.kind for candidate in snapshot.candidates}
    assert IntentKind.CLAIM_DAILY in kinds
    assert IntentKind.ENTER_CHARACTER in kinds
    # A march slot outranks a daily chore when the harness decides alone.
    assert intent.kind is IntentKind.ENTER_CHARACTER
    assert intent.decided_by is DecidedBy.HARNESS_FALLBACK


def test_no_geometry_survives_the_trip_from_scene_facts_to_the_payload():
    import json

    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = _scheduler(store)
        signals = scheduler.tick(character_id="char-idle", now=NOW, facts=FACTS, frame_id="f1")
        snapshot = build_snapshot(
            scheduler,
            signals,
            FACTS,
            fleet=_fleet(busy=False),
            ladder=Ladder(),
            now=NOW,
            cycle_id="cycle-1",
        )
    flattened = json.dumps(snapshot.as_payload())
    for forbidden in ("frame_bbox", "client_window_rect", "1920"):
        assert forbidden not in flattened


def test_a_fleet_entirely_in_the_field_still_yields_a_plan():
    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = _scheduler(store)
        signals = scheduler.tick(character_id="char-idle", now=NOW, facts=FACTS, frame_id="f1")
        # OBSERVE_ONLY emits no input at all, so not even the daily chores are
        # offered - and the loop must still produce a decision.
        ladder = Ladder(start=Rung.OBSERVE_ONLY)
        intent, snapshot = plan_cycle(
            StrategicPlanner(None),
            scheduler,
            signals,
            FACTS,
            fleet=_fleet(busy=True),
            ladder=ladder,
            now=NOW,
            cycle_id="cycle-2",
        )
    assert snapshot.candidates == ()
    assert intent.kind is IntentKind.HOLD
    assert intent.reason.strip()


def test_the_ladder_depth_travels_with_the_snapshot():
    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = _scheduler(store)
        signals = scheduler.tick(character_id="char-idle", now=NOW, facts=FACTS, frame_id="f1")
        ladder = Ladder()
        ladder.demote("search returned no node", at=NOW - timedelta(hours=2))
        snapshot = build_snapshot(
            scheduler,
            signals,
            FACTS,
            fleet=_fleet(busy=False),
            ladder=ladder,
            now=NOW,
            cycle_id="cycle-3",
        )
    payload = snapshot.as_payload()
    assert payload["active_goal"] == "DEFAULT_FARM"
    assert payload["seconds_below_top_goal"] == 7200


def test_order_progress_is_published_without_a_guessed_pace_flag():
    summary = order_summary(_ledger(), NOW)
    assert summary["order_id"] == "ord-1"
    assert summary["outstanding_net"]["GOLD"] == 2_000_000
    assert summary["outstanding_net"]["FOOD"] == 1_000_000 - 460_000
    assert summary["complete"] is False
    # Whether the fleet is on pace needs a MEASURED delivery rate, which M5
    # has not produced. The number is published; the judgement is not faked.
    assert "on_pace" not in summary
    assert summary["required_net_per_hour"] > 0
