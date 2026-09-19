"""Run the five offline/data-driven mission-layer acceptance cases.

This command never opens ROK and never emits keyboard/mouse input.  It creates
an evidence JSON containing deterministic reset, event-window, farm-timing,
queue/cooldown, and change-feedback results.  Live action remains a separate
occurrence-bound gate.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.mission_knowledge import SQLiteMissionKnowledgeStore
from harness.mission_timeline import (
    TaskState,
    bounded_llm_packet,
    compute_farm_plan,
    detect_capability_change,
    load_timeline_config,
    next_reset,
    reset_boundary,
)


NOW = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)


def _case(name: str, check):
    try:
        detail = check()
        return {"id": name, "status": "PASS", "detail": detail}
    except Exception as exc:  # evidence must expose the exact failed gate
        return {"id": name, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"}


def run(output: Path) -> dict:
    timeline = load_timeline_config(ROOT / "config" / "mission_layer.yaml")

    def reset_case():
        before = reset_boundary(NOW - timedelta(minutes=1))
        after = reset_boundary(datetime(2026, 9, 19, tzinfo=timezone.utc))
        following = next_reset(after)
        assert before == datetime(2026, 9, 19, tzinfo=timezone.utc)
        assert after == before
        assert following == datetime(2026, 9, 20, tzinfo=timezone.utc)
        return {"reset_utc": after.isoformat(), "display_local": "07:00 Asia/Ho_Chi_Minh"}

    def courier_case():
        signal = timeline.signal("COURIER_STATION_CHECK", character_id="char-direct-01", now=NOW,
                                 facts={"courier_station": {"free_claim_available": True,
                                                            "items_available": True,
                                                            "window_expires_at": (NOW + timedelta(hours=2)).isoformat()}})
        assert signal.status == "DUE"
        inspected = timeline.signal("COURIER_STATION_CHECK", character_id="char-direct-01", now=NOW,
                               facts={"courier_station": {"free_claim_available": False,
                                                          "items_available": True,
                                                          "window_expires_at": (NOW + timedelta(hours=2)).isoformat()}})
        purchase = timeline.signal("BUY_COURIER_ITEM", character_id="char-direct-01", now=NOW,
                                   facts={"courier_station": {"free_claim_available": False,
                                                              "items_available": True,
                                                              "window_expires_at": (NOW + timedelta(hours=2)).isoformat()}})
        assert inspected.status == "DUE"
        assert purchase.status == "NEEDS_DECISION"
        return {"free_claim": signal.status, "paid_items": purchase.status,
                "inspection": inspected.status, "auto_spend": False}

    def farm_case():
        plan = compute_farm_plan(NOW, nominal_gather_seconds=8 * 3600,
                                 travel_out_seconds=600, travel_back_seconds=900,
                                 node_depletion_at=NOW + timedelta(hours=5),
                                 buff_expires_at=NOW + timedelta(hours=6))
        assert plan.mining_duration_seconds == 5 * 3600
        assert plan.return_at == NOW + timedelta(hours=5, seconds=900)
        return {"limiting_factor": plan.limiting_factor,
                "mining_seconds": plan.mining_duration_seconds,
                "return_at": plan.return_at.isoformat(),
                "travel_excluded_from_mining": True}

    def queue_case():
        waiting = timeline.signal("FARM_RESOURCE", character_id="char-direct-01", now=NOW,
                                  facts={"farm": {"queue_used": 2, "queue_capacity": 2,
                                                   "marches": [{"return_at": (NOW + timedelta(minutes=40)).isoformat()}]}})
        assert waiting.status == "WAITING"
        cooldown = timeline.signal("ALLIANCE_CONTRIBUTION", character_id="char-direct-01", now=NOW,
                                   state=TaskState(cooldown_until=NOW + timedelta(minutes=10)),
                                   facts={"alliance": {"contribution_status": "cooldown",
                                                       "cooldown_until": (NOW + timedelta(minutes=10)).isoformat()}})
        assert cooldown.status == "WAITING"
        return {"farm_next_due": waiting.next_due_at.isoformat(),
                "alliance_next_due": cooldown.next_due_at.isoformat(),
                "sleep_hardcoded": False}

    def feedback_case():
        changed = detect_capability_change({"courier": ["Courier Station", "FREE"]},
                                           {"courier": ["Courier Station"]})[0]
        assert changed.retraining_required is True
        signal = timeline.signal("BUY_COURIER_ITEM", character_id="char-direct-01", now=NOW,
                                 facts={"courier_station": {"free_claim_available": False,
                                                            "items_available": True}})
        packet = bounded_llm_packet(signal, timeline.tasks[signal.task_id], {
            "courier_station": {"items_available": True, "bbox": {"x": 1}}
        })
        assert packet["status"] == "NEEDS_DECISION"
        assert "bbox" not in json.dumps(packet)
        with tempfile.TemporaryDirectory() as folder:
            with SQLiteMissionKnowledgeStore(Path(folder) / "knowledge.sqlite3") as store:
                store.record_fact("courier.items_available", True, observed_at=NOW,
                                  source="direct_ui_observation")
                store.record_occurrence(signal, updated_at=NOW)
                store.record_signal(changed, observed_at=NOW)
                counts = store.counts()
        assert counts == {"facts": 1, "occurrences": 1, "events": 0, "change_signals": 1}
        return {"signal": changed.status, "retraining_required": True,
                "llm_packet_is_bounded": True, "knowledge_db_counts": counts}

    cases = [
        _case("daily_reset_idempotence", reset_case),
        _case("courier_event_window", courier_case),
        _case("farm_buff_and_mining_math", farm_case),
        _case("queue_and_alliance_cooldown", queue_case),
        _case("change_feedback_and_knowledge_store", feedback_case),
    ]
    report = {
        "schema_version": 1,
        "measurement_class": "mission_layer_offline_acceptance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_emitted_any": False,
        "local_llm_mode": "always_on_observer_harness_escalation_only",
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "BLOCKED",
        "passed": sum(item["status"] == "PASS" for item in cases),
        "required": 5,
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("workspace/evidence/mission_layer/acceptance-latest.json"))
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({"status": report["status"], "passed": report["passed"],
                      "required": report["required"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
