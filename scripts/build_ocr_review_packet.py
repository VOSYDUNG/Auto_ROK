"""Build a read-only packet for independent ROK label review.

The packet is deliberately not a lock update.  A reviewer must inspect the
persisted PNGs independently of the operator record and then record a dated
review in ``config/observation_label_lock.json`` through the project's normal
review process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.rapidocr_fixed_roi import image_sha256


LABELS = ("Barbarians", "Cropland", "Logging Camp", "Stone Deposit", "Gold Deposit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--label-manifest",
        type=Path,
        default=ROOT / "config" / "observation_label_lock.json",
    )
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=ROOT / "config" / "observation_corpus.json",
    )
    parser.add_argument(
        "--rapidocr-report",
        type=Path,
        default=ROOT / "workspace" / "evidence" / "corpus" / "rapidocr-corpus-experiment-20260919-03.json",
    )
    args = parser.parse_args()
    label_manifest = json.loads(args.label_manifest.resolve().read_text(encoding="utf-8"))
    corpus_manifest = json.loads(args.corpus_manifest.resolve().read_text(encoding="utf-8"))
    rapid_report = json.loads(args.rapidocr_report.resolve().read_text(encoding="utf-8"))
    corpus_by_id = {
        item.get("id"): item
        for item in corpus_manifest.get("entries", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    rapid_by_image: dict[str, list[dict[str, Any]]] = {}
    for item in rapid_report.get("results", []):
        if isinstance(item, Mapping) and isinstance(item.get("image"), str):
            rapid_by_image.setdefault(str(Path(item["image"]).resolve()).casefold(), []).append(dict(item))

    entries: list[dict[str, Any]] = []
    for label_entry in label_manifest.get("entries", []):
        if not isinstance(label_entry, Mapping) or label_entry.get("expected_state") != "RESOURCE_SEARCH_PANEL":
            continue
        entry_id = label_entry.get("id")
        corpus_entry = corpus_by_id.get(entry_id)
        if not isinstance(corpus_entry, Mapping):
            continue
        capture_dir = corpus_entry.get("capture_dir")
        if not isinstance(capture_dir, str):
            continue
        image = (ROOT / capture_dir / "rok-client.png").resolve()
        rapid_rows = rapid_by_image.get(str(image).casefold(), [])
        entries.append({
            "id": entry_id,
            "split": corpus_entry.get("split"),
            "expected_state": label_entry.get("expected_state"),
            "image": str(image),
            "image_sha256": label_entry.get("image_sha256"),
            "capture_frame_id": label_entry.get("capture_frame_id"),
            "capture_dir": str((ROOT / capture_dir).resolve()),
            "operator_review_status": label_entry.get("review_status"),
            "label_basis": corpus_entry.get("label_basis"),
            "fixed_category_labels": list(LABELS),
            "rapidocr_observation": [
                {
                    "label": row.get("label"),
                    "text": row.get("text"),
                    "score": row.get("score"),
                    "exact": row.get("exact"),
                    "variant": row.get("variant"),
                }
                for row in rapid_rows
            ],
            "independent_review": {
                "review_status": "pending",
                "reviewer_id": None,
                "reviewed_at": None,
                "state_confirmed": None,
                "labels_confirmed": None,
                "notes": None,
            },
        })

    packet = {
        "schema_version": 1,
        "status": "pending_independent_review",
        "measurement_class": "ocr_label_review_packet",
        "instructions": [
            "Inspect each persisted PNG before reading the OCR result column.",
            "Confirm the visible state and five category labels against the bound frame id/hash.",
            "Use a reviewer identity different from operator-record-20260918.",
            "Do not mark entries locked until all 12 frames have been independently reviewed.",
        ],
        "source_label_manifest": str(args.label_manifest.resolve()),
        "source_corpus_manifest": str(args.corpus_manifest.resolve()),
        "source_rapidocr_report": str(args.rapidocr_report.resolve()),
        "entry_count": len(entries),
        "entries": entries,
        "input_emitted": False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": packet["status"],
        "entry_count": packet["entry_count"],
        "output": str(output),
        "input_emitted": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
