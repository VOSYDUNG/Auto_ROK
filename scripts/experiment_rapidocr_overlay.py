"""Build an offline RapidOCR overlay and rerun the existing OCR contract.

The canonical Windows.Media.Ocr JSON files are never overwritten.  For each
persisted RESOURCE_SEARCH_PANEL capture in the label manifest, this script
copies the existing OCR elements, removes only the bounded bottom category
row, inserts RapidOCR fixed-ROI elements, and writes a derived OCR file plus a
derived corpus manifest.  The derived manifest can be passed to
``evaluate_ocr_quality.py`` for an apples-to-apples R1a screen.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.rapidocr_fixed_roi import RapidOcrFixedRoiBackend, RapidOcrFixedRoiError


OVERLAY_NAME = "ocr-rapidocr-fixed-roi-experiment-20260919.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=ROOT / "config" / "observation_corpus.json",
    )
    parser.add_argument(
        "--label-manifest",
        type=Path,
        default=ROOT / "config" / "observation_label_lock.json",
    )
    parser.add_argument("--output-manifest", type=Path, required=True)
    return parser.parse_args()


def _repo_path(value: str) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _is_category_row(item: Mapping[str, Any]) -> bool:
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    try:
        x, y, width, height = (int(value) for value in bbox)
    except (TypeError, ValueError):
        return False
    return 320 <= x <= 1040 and 720 <= y <= 768


def _overlay_ocr(original: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    elements = [
        copy.deepcopy(item)
        for item in original.get("elements", [])
        if isinstance(item, Mapping) and not _is_category_row(item)
    ]
    next_index = len(elements)
    for word_index, item in enumerate(report.get("results", [])):
        if not isinstance(item, Mapping):
            continue
        rect = item.get("rect")
        text = item.get("text")
        if not isinstance(rect, list) or len(rect) != 4 or not isinstance(text, str):
            continue
        elements.append(
            {
                "bbox": rect,
                "word_index": word_index,
                "confidence": item.get("score"),
                "confidence_known": item.get("confidence_known") is True,
                "text": text,
                "line_index": 4,
                "ocr_element_index": next_index,
                "acquisition": "rapidocr_fixed_roi",
                "grounding_authority": "ocr_backend",
                "frame_id": item.get("frame_id"),
                "image_sha256": item.get("image_sha256"),
            }
        )
        next_index += 1
    overlay = copy.deepcopy(dict(original))
    overlay["elements"] = elements
    overlay["text"] = " ".join(str(item.get("text", "")) for item in elements).strip()
    overlay["backend"] = {
        "name": "Windows.Media.Ocr+RapidOCR.fixed_roi",
        "version": "windows-media-ocr+rapidocr_onnxruntime-1.4.4",
        "mode": "experiment_only_overlay",
        "device": "cpu",
        "providers": ["CPUExecutionProvider"],
        "detector": "disabled_fixed_roi",
    }
    overlay["input_emitted"] = False
    overlay["rapidocr_overlay"] = {
        "status": "experiment_only",
        "source_image": report.get("image"),
        "image_sha256": report.get("image_sha256"),
        "frame_id": report.get("frame_id"),
        "roi_profile_id": report.get("roi_profile_id"),
        "capture_binding_verified": report.get("capture_binding_verified") is True,
    }
    return overlay


def main() -> int:
    args = _parse_args()
    corpus_path = args.corpus_manifest.resolve()
    label_path = args.label_manifest.resolve()
    output_manifest = args.output_manifest.resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    labels = json.loads(label_path.read_text(encoding="utf-8"))
    corpus_entries = corpus.get("entries", [])
    label_entries = labels.get("entries", [])
    corpus_by_id = {
        item.get("id"): item
        for item in corpus_entries
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    backend = RapidOcrFixedRoiBackend()
    derived = copy.deepcopy(corpus)
    derived_entries = derived.get("entries", [])
    overlay_count = 0
    bindings: list[dict[str, Any]] = []
    for label_entry in label_entries:
        if not isinstance(label_entry, Mapping) or label_entry.get("expected_state") != "RESOURCE_SEARCH_PANEL":
            continue
        entry_id = label_entry.get("id")
        corpus_entry = corpus_by_id.get(entry_id)
        if not isinstance(corpus_entry, Mapping):
            raise SystemExit(f"label entry is absent from corpus: {entry_id}")
        capture_dir = corpus_entry.get("capture_dir")
        if not isinstance(capture_dir, str):
            raise SystemExit(f"capture_dir is missing: {entry_id}")
        run_dir = _repo_path(capture_dir)
        capture = json.loads((run_dir / "capture.json").read_text(encoding="utf-8"))
        image = run_dir / "rok-client.png"
        frame = capture.get("frame", {})
        try:
            report = backend.recognize_image(
                image,
                frame_id=frame["id"],
                expected_sha256=frame["image_sha256"],
            )
            original_name = corpus_entry.get("ocr_file", "ocr.json")
            original = json.loads((run_dir / original_name).read_text(encoding="utf-8"))
        except (OSError, KeyError, json.JSONDecodeError, RapidOcrFixedRoiError) as exc:
            raise SystemExit(f"could not build overlay for {entry_id}: {exc}") from exc
        overlay_path = run_dir / OVERLAY_NAME
        overlay_path.write_text(
            json.dumps(_overlay_ocr(original, {**report, "capture_binding_verified": True}), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for derived_entry in derived_entries:
            if isinstance(derived_entry, Mapping) and derived_entry.get("id") == entry_id:
                derived_entry["ocr_file"] = OVERLAY_NAME
                break
        overlay_count += 1
        bindings.append(
            {
                "id": entry_id,
                "overlay": str(overlay_path),
                "frame_id": report.get("frame_id"),
                "image_sha256": report.get("image_sha256"),
                "capture_binding_verified": True,
                "input_emitted": False,
            }
        )

    derived["status"] = "experiment_only_overlay"
    derived["rapidocr_overlay"] = {
        "status": "experiment_only",
        "overlay_count": overlay_count,
        "backend": "rapidocr_fixed_roi",
        "device": "cpu",
        "providers": ["CPUExecutionProvider"],
        "input_emitted": False,
        "bindings": bindings,
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(derived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "experiment_only_overlay",
        "overlay_count": overlay_count,
        "output_manifest": str(output_manifest),
        "input_emitted": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
