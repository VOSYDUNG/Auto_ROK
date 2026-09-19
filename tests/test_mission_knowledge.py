from datetime import datetime, timedelta, timezone

from harness.mission_knowledge import SQLiteMissionKnowledgeStore
from harness.mission_timeline import detect_capability_change, load_timeline_config


UTC = timezone.utc
NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)


def test_sqlite_knowledge_store_persists_expiring_facts_and_events(tmp_path):
    path = tmp_path / "mission-knowledge.sqlite3"
    tl = load_timeline_config("config/mission_layer.yaml")
    signal = tl.signal("CLAIM_VIP", character_id="c1", now=NOW,
                       facts={"vip": {"claim_available": True}})
    with SQLiteMissionKnowledgeStore(path) as store:
        store.record_fact("vip.claim_available", True, observed_at=NOW,
                          valid_until=NOW + timedelta(minutes=5), source="direct_ui_observation",
                          frame_id="frame-1", evidence_ref="workspace/evidence/frame-1.json")
        store.record_occurrence(signal, updated_at=NOW)
        event_id = store.append_event(signal.occurrence_id, "DUE", {"source": "timeline"}, at=NOW)
        assert event_id == 1
        assert store.read_fact("vip.claim_available", now=NOW)["value"] is True
        assert store.read_fact("vip.claim_available", now=NOW + timedelta(minutes=6)) is None
        assert store.counts() == {"facts": 1, "occurrences": 1, "events": 1, "change_signals": 0}


def test_sqlite_knowledge_store_records_change_feedback(tmp_path):
    with SQLiteMissionKnowledgeStore(tmp_path / "knowledge.sqlite3") as store:
        signal = detect_capability_change({"courier": ["FREE"]}, {"courier": ["PAID"]})[0]
        store.record_signal(signal, observed_at=NOW)
        assert store.counts()["change_signals"] == 1
