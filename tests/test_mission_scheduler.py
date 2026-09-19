from datetime import datetime, timedelta, timezone

from harness.mission_knowledge import SQLiteMissionKnowledgeStore
from harness.mission_scheduler import MissionScheduler
from harness.mission_timeline import TaskState, load_timeline_config


UTC = timezone.utc
NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)


def test_tick_persists_facts_occurrences_and_only_escalates_ambiguity():
    timeline = load_timeline_config("config/mission_layer.yaml")
    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = MissionScheduler(timeline, store)
        facts = {
            "vip": {"claim_available": True, "gifts_available": False},
            "courier_station": {"free_claim_available": False, "items_available": True},
            "farm": {"queue_used": 1, "queue_capacity": 2, "marches": []},
            "frame_bbox": {"x": 1},
        }
        signals = scheduler.tick(character_id="c1", now=NOW, facts=facts, frame_id="f1")
        assert any(item.task_id == "CLAIM_VIP" and item.status == "DUE" for item in signals)
        packets = scheduler.decision_packets(signals, facts)
        assert [packet["task_id"] for packet in packets] == ["BUY_COURIER_ITEM", "ALLIANCE_CONTRIBUTION"]
        assert store.counts()["facts"] == 7
        assert store.read_fact("frame_bbox.x") is None
        assert store.counts()["occurrences"] == 6


def test_tick_uses_return_and_cooldown_facts_without_sleep():
    timeline = load_timeline_config("config/mission_layer.yaml")
    with SQLiteMissionKnowledgeStore(":memory:") as store:
        scheduler = MissionScheduler(timeline, store)
        facts = {"farm": {"queue_used": 2, "queue_capacity": 2,
                          "marches": [{"return_at": (NOW + timedelta(minutes=30)).isoformat()}]},
                 "alliance": {"contribution_status": "cooldown",
                              "cooldown_until": (NOW + timedelta(minutes=5)).isoformat()}}
        signals = scheduler.tick(character_id="c1", now=NOW, facts=facts,
                                 states={"ALLIANCE_CONTRIBUTION": TaskState(cooldown_until=NOW + timedelta(minutes=5))})
        by_id = {item.task_id: item for item in signals}
        assert by_id["FARM_RESOURCE"].next_due_at == NOW + timedelta(minutes=30)
        assert by_id["ALLIANCE_CONTRIBUTION"].next_due_at == NOW + timedelta(minutes=5)
