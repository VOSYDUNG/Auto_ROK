"""Evaluate a manifest of real ROK captures through CPU ROI/OCR/state rules.

This is an evidence report, not a label generator.  It keeps provisional labels
separate from the PRD gate and records every projection failure or unresolved
state instead of treating missing OCR as a correct answer.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_facts import GatherFactObservationProvider  # noqa: E402
from harness.main_view_detector import (  # noqa: E402
    MainViewProfile,
    MainViewVisualObservationProvider,
    classify_signature,
    extract_visual_signature,
)
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.mission_tool import ObservationBundle, ObservationProvider  # noqa: E402
from harness.observation_bridge import ObservationBridgeError, project_observation  # noqa: E402
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec  # noqa: E402
from harness.resource_level_control import ResourceLevelControlObservationProvider, ResourceLevelProfile  # noqa: E402
from harness.state_classifier import StateClassifier  # noqa: E402


class _PersistedProvider:
    def __init__(self, bundle: ObservationBundle) -> None:
        self.bundle = bundle

    def observe(self, context: MissionContext) -> ObservationBundle:
        return self.bundle


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(path: Path, label: str) -> Mapping[str, Any]:
    value = _read_json(path)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _target_specs(path: Path) -> tuple[OcrTargetSpec, ...]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"OCR target config must be a JSON list: {path}")
    specs: list[OcrTargetSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("OCR target entries must be objects")
        target_id, labels = item.get("target_id"), item.get("labels")
        if not isinstance(target_id, str) or not target_id or not isinstance(labels, list) or not labels:
            raise ValueError(f"invalid OCR target entry: {item!r}")
        confidence = item.get("min_confidence", 0.90)
        allow_unscored = item.get("allow_unscored_exact", False)
        if type(confidence) not in (int, float) or type(allow_unscored) is not bool:
            raise ValueError(f"invalid OCR target threshold/authorization: {item!r}")
        specs.append(OcrTargetSpec(target_id, tuple(labels), float(confidence), allow_unscored))
    return tuple(specs)


def _capture_time(capture: Mapping[str, Any]) -> datetime:
    frame = capture.get("frame")
    raw = frame.get("captured_at") if isinstance(frame, Mapping) else None
    if not isinstance(raw, str):
        raise ValueError("capture frame captured_at is required")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("capture frame captured_at needs a timezone")
    return parsed.astimezone(timezone.utc)


def _state_confusion(items: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Return expected -> classified counts without hiding unresolved states."""
    matrix: dict[str, dict[str, int]] = {}
    for item in items:
        expected = item.get("expected_state")
        classified = item.get("classified_state")
        if not isinstance(expected, str):
            expected = "<missing>"
        if not isinstance(classified, str) or not classified:
            classified = "<unresolved>"
        row = matrix.setdefault(expected, {})
        row[classified] = row.get(classified, 0) + 1
    return matrix


def _split_state_metrics(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    projected = [item for item in items if item.get("status") in {"ok", "visual_only"}]
    exact = [item for item in projected if item.get("state_match") is True]
    return {
        "total": len(items),
        "projected": len(projected),
        "exact_matches": len(exact),
        "accuracy_over_projected": len(exact) / len(projected) if projected else None,
        "confusion": _state_confusion(projected),
    }


def _runs_path(value: str) -> Path:
    path = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    runs = (ROOT / "workspace" / "runs").resolve()
    if not path.is_relative_to(runs):
        raise ValueError(f"capture_dir must stay under workspace/runs: {value}")
    return path


def _run_entry(
    entry: Mapping[str, Any],
    *,
    target_specs: tuple[OcrTargetSpec, ...],
    main_view_profile: MainViewProfile,
    resource_level_profile: ResourceLevelProfile,
) -> dict[str, Any]:
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError("corpus entry id is required")
    run_dir = _runs_path(str(entry.get("capture_dir", "")))
    capture_path = run_dir / "capture.json"
    ocr_name = entry.get("ocr_file", "ocr.json")
    if ocr_name is not None and (not isinstance(ocr_name, str) or Path(ocr_name).name != ocr_name):
        raise ValueError(f"corpus entry {entry_id} has invalid ocr_file")
    ocr_path = run_dir / ocr_name if isinstance(ocr_name, str) else None
    image_path = run_dir / "rok-client.png"
    expected = entry.get("expected_state")
    result: dict[str, Any] = {
        "id": entry_id,
        "split": entry.get("split"),
        "expected_state": expected,
        "label_basis": entry.get("label_basis"),
        "source": {
            "capture": str(capture_path),
            "ocr": str(ocr_path) if ocr_path is not None else None,
            "image": str(image_path),
        },
        "status": "error",
    }
    try:
        capture = _mapping(capture_path, "capture")
        if ocr_path is None:
            match = classify_signature(extract_visual_signature(image_path), main_view_profile)
            result.update({
                "status": "visual_only",
                "projection_status": "NOT_RUN",
                "frame_id": None,
                "classified_state": match.state_id,
                "state_match": match.state_id == expected,
                "grounded_target_ids": [],
                "ocr_grounding_decisions": [],
                "main_view_detector": {
                    "status": "matched" if match.state_id else "unresolved",
                    "state_id": match.state_id,
                    "best_distance": match.best_distance,
                    "second_distance": match.second_distance,
                    "reason": match.reason,
                    "source": "trained_visual_signature",
                    "processing_device": "cpu",
                },
                "input_emitted": False,
            })
            return result
        ocr = _mapping(ocr_path, "OCR")
        projected = project_observation(
            capture,
            ocr,
            image_path,
            (),
            now=_capture_time(capture),
            max_age_seconds=5.0,
        )
        if projected.observation is None or projected.scene is None:
            raise ValueError("projection returned no observation/scene")
        facts = dict(projected.scene.facts)
        facts["image_path"] = str(image_path)
        facts["image_path_source"] = "historical_frame_replay"
        bundle = ObservationBundle(projected.observation, replace(projected.scene, facts=facts))
        provider: ObservationProvider = _PersistedProvider(bundle)
        provider = OcrSemanticObservationProvider(provider, target_specs)
        provider = MainViewVisualObservationProvider(provider, main_view_profile)
        provider = ResourceLevelControlObservationProvider(provider, resource_level_profile)
        provider = GatherFactObservationProvider(provider, character_id="corpus-observer")
        bundle = provider.observe(MissionContext("GATHER_RESOURCE", "corpus", entry_id))
        classification = StateClassifier().classify(bundle.observation, bundle.scene)
        main_view = bundle.scene.facts.get("main_view_detector")
        decisions = bundle.scene.facts.get("ocr_grounding_decisions")
        grounded = [target.target_id for target in bundle.scene.targets]
        grounding_sources = {
            "compiled_ui_layout": sum(
                1 for target in bundle.scene.targets
                if target.metadata.get("grounding_authority") == "compiled_ui_layout"
            ),
            "ocr_backend": sum(
                1 for target in bundle.scene.targets
                if target.metadata.get("grounding_authority") != "compiled_ui_layout"
            ),
        }
        result.update({
            "status": "ok",
            "projection_status": projected.status,
            "frame_id": bundle.scene.frame_id,
            "classified_state": classification.state_id,
            "state_match": classification.state_id == expected,
            "grounded_target_ids": grounded,
            "ocr_grounding_decisions": list(decisions) if isinstance(decisions, (list, tuple)) else [],
            "grounding_sources": grounding_sources,
            "main_view_detector": dict(main_view) if isinstance(main_view, Mapping) else None,
            "input_emitted": False,
        })
    except (OSError, KeyError, TypeError, ValueError, ObservationBridgeError) as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["input_emitted"] = False
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(ROOT / "config" / "observation_corpus.json"))
    parser.add_argument("--ocr-targets", default=str(ROOT / "config" / "gather_ocr_targets.json"))
    parser.add_argument("--main-view-profile", default=str(ROOT / "config" / "main_view_profiles.json"))
    parser.add_argument("--resource-level-profile", default=str(ROOT / "config" / "resource_level_profile.json"))
    parser.add_argument(
        "--evidence-root",
        default=str(ROOT / "workspace" / "evidence" / "corpus"),
    )
    parser.add_argument("--report-id", default="cpu-observation-corpus-20260918-01")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    manifest = _mapping(manifest_path, "corpus manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("corpus manifest entries must be a non-empty list")
    target_specs = _target_specs(Path(args.ocr_targets).resolve())
    main_view_profile = MainViewProfile.load(Path(args.main_view_profile).resolve())
    resource_level_profile = ResourceLevelProfile.load(Path(args.resource_level_profile).resolve())
    results = [
        _run_entry(entry, target_specs=target_specs, main_view_profile=main_view_profile, resource_level_profile=resource_level_profile)
        for entry in entries
        if isinstance(entry, Mapping)
    ]
    labelled = [item for item in results if item.get("split") == "labelled"]
    holdout = [item for item in results if item.get("split") == "holdout"]
    successful = [item for item in results if item.get("status") in {"ok", "visual_only"}]
    ocr_complete = [item for item in successful if item.get("status") == "ok"]
    state_matches = [item for item in successful if item.get("state_match") is True]
    main_items = [
        item for item in successful
        if item.get("expected_state") in {"CITY_VIEW", "WORLD_MAP_VIEW"}
    ]
    main_matches = [item for item in main_items if item.get("state_match") is True]
    search_items = [item for item in successful if item.get("expected_state") == "RESOURCE_SEARCH_PANEL"]
    search_suppressed = [
        item for item in search_items
        if isinstance(item.get("main_view_detector"), Mapping)
        and item["main_view_detector"].get("status") == "suppressed"
    ]
    target_grounding = []
    for item in search_items:
        target_grounding.extend(
            decision for decision in item.get("ocr_grounding_decisions", [])
            if isinstance(decision, Mapping)
        )
    grounding_source_totals: dict[str, int] = {}
    for item in search_items:
        sources = item.get("grounding_sources")
        if isinstance(sources, Mapping):
            for key, value in sources.items():
                if isinstance(key, str) and type(value) is int:
                    grounding_source_totals[key] = grounding_source_totals.get(key, 0) + value
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_id": args.report_id,
        "status": "screening_only",
        "measurement_class": manifest.get("measurement_class"),
        "label_status": manifest.get("status"),
        "acceptance": {
            "prd_r1a": "not_ready",
            "reason": "labels are provisional and CER/WER/manual lock plus broader state coverage are still required",
            "labelled_target": 20,
            "holdout_target": 5,
        },
        "counts": {
            "manifest_entries": len(results),
            "labelled": len(labelled),
            "holdout": len(holdout),
            "projection_ok": len(successful),
            "ocr_complete": len(ocr_complete),
            "visual_only": sum(1 for item in successful if item.get("status") == "visual_only"),
            "state_exact_matches": len(state_matches),
        },
        "metrics": {
            "state_accuracy_over_projected": len(state_matches) / len(successful) if successful else None,
            "main_view_accuracy_over_projected": len(main_matches) / len(main_items) if main_items else None,
            "search_foreground_suppression_rate": len(search_suppressed) / len(search_items) if search_items else None,
            "state_confusion": _state_confusion(successful),
            "split_state_metrics": {
                "labelled": _split_state_metrics(labelled),
                "holdout": _split_state_metrics(holdout),
            },
            "search_target_grounding": {
                "grounded": sum(1 for decision in target_grounding if decision.get("status") == "GROUNDED"),
                "requested": len(target_grounding),
                "grounding_source_totals": grounding_source_totals,
            },
        },
        "input_emitted_any": any(bool(item.get("input_emitted")) for item in results),
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    root = Path(args.evidence_root).resolve()
    if not root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    root.mkdir(parents=True, exist_ok=True)
    output_path = root / f"{args.report_id}.json"
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    printed = dict(report)
    printed["evidence_path"] = str(output_path)
    print(json.dumps(printed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
