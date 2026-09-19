"""Ingest one observation-only live pass into the mission knowledge DB."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.mission_knowledge import SQLiteMissionKnowledgeStore  # noqa: E402
from harness.mission_scheduler import MissionScheduler  # noqa: E402
from harness.mission_timeline import load_timeline_config  # noqa: E402


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ValueError(f"{label} must stay below {root}")
    return resolved


def run(manifest_path: Path, db_path: Path, output_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("manifest schema_version must be 1")
    now = datetime.fromisoformat(str(manifest["ended_at"]).replace("Z", "+00:00"))
    timeline = load_timeline_config(ROOT / "config" / "mission_layer.yaml")
    with SQLiteMissionKnowledgeStore(db_path) as store:
        scheduler = MissionScheduler(timeline, store)
        signals = scheduler.tick(
            character_id=str(manifest["character_id"]),
            now=now,
            facts=manifest.get("facts", {}),
            source="direct_ui_observation",
            evidence_ref=str(manifest_path.relative_to(ROOT)),
        )
        packets = scheduler.decision_packets(signals, manifest.get("facts", {}))
        report = {
            "schema_version": 1,
            "measurement_class": "live_mission_knowledge_ingest",
            "run_id": manifest.get("run_id"),
            "input_emitted_any": manifest.get("input_emitted_any") is True,
            "status": "PASS" if manifest.get("input_emitted_any") is False else "BLOCKED",
            "signals": [
                {
                    "task_id": signal.task_id,
                    "status": signal.status,
                    "next_due_at": signal.next_due_at.isoformat() if signal.next_due_at else None,
                    "reason": signal.reason,
                }
                for signal in signals
            ],
            "decision_packet_task_ids": [packet["task_id"] for packet in packets],
            "knowledge_db": str(db_path),
            "knowledge_counts": store.counts(),
            "unknowns": list(manifest.get("unknowns", [])),
            "policy": manifest.get("policy", {}),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        _inside(args.manifest, ROOT / "workspace" / "evidence", "manifest"),
        _inside(args.database, ROOT / "workspace" / "evidence", "database"),
        _inside(args.output, ROOT / "workspace" / "evidence", "output"),
    )
    print(json.dumps({"status": report["status"], "signals": report["signals"],
                      "decision_packet_task_ids": report["decision_packet_task_ids"],
                      "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
