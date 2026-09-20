from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from datetime import datetime, timedelta, timezone

from harness.mission_timeline import (
    TaskState,
    bounded_llm_packet,
    compute_farm_plan,
    detect_capability_change,
    load_timeline_config,
    next_reset,
    reset_boundary,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)


def timeline():
    return load_timeline_config(ROOT / "config" / "mission_layer.yaml")


def test_reset_is_one_utc_boundary_and_vietnam_display_is_seven_am():
    before = datetime(2026, 9, 18, 23, 59, tzinfo=UTC)
    after = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
    assert reset_boundary(before) == datetime(2026, 9, 18, tzinfo=UTC)
    assert reset_boundary(after) == datetime(2026, 9, 19, tzinfo=UTC)
    assert next_reset(after) == datetime(2026, 9, 20, tzinfo=UTC)
    assert after.astimezone(timezone(timedelta(hours=7))).hour == 7


def test_daily_vip_is_due_once_then_idempotently_complete():
    tl = timeline()
    facts = {"vip": {"claim_available": True}}
    due = tl.signal("CLAIM_VIP", character_id="c1", now=NOW, facts=facts)
    assert due.status == "DUE"
    done = tl.signal("CLAIM_VIP", character_id="c1", now=NOW,
                     state=TaskState(last_success_at=NOW), facts=facts)
    assert done.status == "COMPLETE"
    unavailable = tl.signal("CLAIM_VIP", character_id="c1", now=NOW,
                            facts={"vip": {"claim_available": False}})
    assert unavailable.status == "COMPLETE"
    assert "unavailable" in unavailable.reason


def test_courier_station_event_window_never_auto_buys():
    tl = timeline()
    free = tl.signal("COURIER_STATION_CHECK", character_id="c1", now=NOW, facts={
        "courier_station": {
            "free_claim_available": True,
            "items_available": True,
            "window_expires_at": (NOW + timedelta(hours=2)).isoformat(),
        }
    })
    assert free.status == "DUE"
    paid = tl.signal("COURIER_STATION_CHECK", character_id="c1", now=NOW, facts={
        "courier_station": {
            "free_claim_available": False,
            "items_available": True,
            "window_expires_at": (NOW + timedelta(hours=2)).isoformat(),
        }
    })
    assert paid.status == "DUE"
    purchase = tl.signal("BUY_COURIER_ITEM", character_id="c1", now=NOW, facts={
        "courier_station": {
            "free_claim_available": False,
            "items_available": True,
            "window_expires_at": (NOW + timedelta(hours=2)).isoformat(),
        }
    })
    assert purchase.status == "NEEDS_DECISION"
    unknown = tl.signal("COURIER_STATION_CHECK", character_id="c1", now=NOW, facts={})
    assert unknown.status == "UNKNOWN_STATE"


def test_farm_plan_separates_mining_from_travel_and_uses_limits():
    plan = compute_farm_plan(
        NOW,
        nominal_gather_seconds=8 * 3600,
        travel_out_seconds=600,
        travel_back_seconds=900,
        node_depletion_at=NOW + timedelta(hours=5),
        buff_expires_at=NOW + timedelta(hours=6),
        next_dispatch_at=NOW + timedelta(hours=5, minutes=30, seconds=900),
    )
    assert plan.limiting_factor == "node_depletion"
    assert plan.mining_duration_seconds == 5 * 3600
    assert plan.return_at == NOW + timedelta(hours=5, seconds=900)
    assert plan.travel_out_seconds == 600
    assert plan.queue_gap_seconds == 1800


def test_farm_queue_and_alliance_contribution_are_fact_driven():
    tl = timeline()
    unknown = tl.signal("ALLIANCE_CONTRIBUTION", character_id="c1", now=NOW, facts={})
    assert unknown.status == "UNKNOWN_STATE"
    waiting = tl.signal("FARM_RESOURCE", character_id="c1", now=NOW, facts={
        "farm": {"queue_used": 2, "queue_capacity": 2,
                 "marches": [{"return_at": (NOW + timedelta(minutes=40)).isoformat()}]}
    })
    assert waiting.status == "WAITING"
    assert waiting.next_due_at == NOW + timedelta(minutes=40)
    ready = tl.signal("FARM_RESOURCE", character_id="c1", now=NOW,
                      facts={"farm": {"queue_used": 1, "queue_capacity": 2, "marches": []}})
    assert ready.status == "DUE"
    cooldown = tl.signal("ALLIANCE_CONTRIBUTION", character_id="c1", now=NOW,
                         state=TaskState(cooldown_until=NOW + timedelta(minutes=10)),
                         facts={"alliance": {"contribution_status": "cooldown",
                                              "cooldown_until": (NOW + timedelta(minutes=10)).isoformat()}})
    assert cooldown.status == "WAITING"
    due = tl.signal("ALLIANCE_CONTRIBUTION", character_id="c1", now=NOW,
                    state=TaskState(completed_count=3), facts={"alliance": {"contribution_status": "ready"}})
    assert due.status == "DUE"
    capped = tl.signal("ALLIANCE_CONTRIBUTION", character_id="c1", now=NOW,
                       state=TaskState(completed_count=20), facts={"alliance": {"contribution_status": "ready"}})
    assert capped.status == "COMPLETE"


def test_changed_surface_generates_retraining_signal_and_bounded_packet():
    signals = detect_capability_change(
        {"courier": ["Courier Station", "FREE"], "alliance": ["Contribution"]},
        {"courier": ["Courier Station"], "alliance": ["Contribution"], "new": ["Unknown"]},
    )
    assert signals[0].status == "NEEDS_DECISION"
    assert signals[0].retraining_required is True
    signal = timeline().signal("BUY_COURIER_ITEM", character_id="c1", now=NOW,
                                facts={"courier_station": {"free_claim_available": False,
                                                           "items_available": True}})
    packet = bounded_llm_packet(signal, timeline().tasks[signal.task_id], {
        "courier_station": {"items_available": True, "bbox": {"x": 1}, "screen_coord": [3, 4]},
    })
    assert packet["status"] == "NEEDS_DECISION"
    assert "bbox" not in str(packet)
    assert "screen_coord" not in str(packet)
