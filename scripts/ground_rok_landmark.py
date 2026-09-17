"""Calibrate one local template or ground it on a fresh passive ROK frame."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.observation_bridge import project_observation  # noqa: E402
from harness.scene_graph import SceneGraph  # noqa: E402
from harness.template_anchors import (  # noqa: E402
    TemplateAnchorError, calibrate_template, load_anchor_spec, resolve_template, write_json,
)
from harness.windows_capture_backend import WindowsCaptureError, capture_rok_client  # noqa: E402


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _inside_runs(value: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "runs").resolve()
    if path == root or not path.is_relative_to(root):
        raise TemplateAnchorError("artifact path must be below workspace/runs")
    return path


def _bbox(value: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise TemplateAnchorError("bbox must be x,y,width,height integers") from exc
    if len(parts) != 4:
        raise TemplateAnchorError("bbox must be x,y,width,height integers")
    return parts


def calibrate(args) -> int:
    reference_dir = _inside_runs(args.reference_run)
    output_dir = _inside_runs(args.output_dir)
    config_path = (ROOT / "config" / "ui_landmarks.json").resolve()
    config = _json(config_path)
    spec = load_anchor_spec(config, args.anchor_id)
    calibration = calibrate_template(reference_dir / "rok-client.png", _json(reference_dir / "capture.json"),
                                     spec, _bbox(args.bbox), output_dir / "template.png",
                                     hashlib.sha256(config_path.read_bytes()).hexdigest())
    write_json(output_dir / "calibration.json", calibration)
    print(json.dumps({"status": "CALIBRATED", "calibration": str(output_dir / "calibration.json"),
                      "template": str(output_dir / "template.png"),
                      "template_sha256": calibration["template_sha256"]}))
    return 0


def observe(args) -> int:
    run_dir = _inside_runs(args.run_dir)
    calibration = _json(_inside_runs(args.calibration))
    config_path = (ROOT / "config" / "ui_landmarks.json").resolve()
    config = _json(config_path)
    spec = load_anchor_spec(config, calibration.get("anchor_id"))
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    run_dir.mkdir(parents=True, exist_ok=True)
    image, capture_path, ocr_path = run_dir / "rok-client.png", run_dir / "capture.json", run_dir / "ocr.json"
    started = time.perf_counter()
    capture_started = time.perf_counter()
    capture = capture_rok_client(image, timeout_seconds=args.timeout_seconds)
    capture_seconds = time.perf_counter() - capture_started
    write_json(capture_path, capture)
    ocr_started = time.perf_counter()
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "windows_ocr.ps1"), "-Image", str(image), "-CaptureMeta", str(capture_path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if completed.returncode:
        raise TemplateAnchorError(completed.stderr.strip() or f"Windows OCR exited {completed.returncode}")
    ocr = json.loads(completed.stdout)
    ocr_seconds = time.perf_counter() - ocr_started
    write_json(ocr_path, ocr)
    projected = project_observation(capture, ocr, image, now=datetime.now(timezone.utc), max_age_seconds=30)
    status, target, match = resolve_template(image, capture, calibration, spec, config_sha256,
                                             now=datetime.now(timezone.utc),
                                             max_age_seconds=30)
    targets = () if target is None else (target,)
    scene = SceneGraph(projected.scene.frame_id, projected.scene.state_hint, targets,
                       {**projected.scene.facts, "anchor_match": match})
    write_json(run_dir / "scene.json", asdict(scene))
    candidate = {"schema_version": 1, "status": status, "frame_id": capture["frame"]["id"],
                 "image_sha256": capture["frame"]["image_sha256"], "match": match,
                 "target": None if target is None else asdict(target)}
    write_json(run_dir / "candidates.json", candidate)
    import cv2
    annotated = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if target is not None:
        cv2.rectangle(annotated, (target.bbox.x1, target.bbox.y1), (target.bbox.x2, target.bbox.y2), (0, 0, 255), 3)
        cv2.putText(annotated, target.target_id, (max(0, target.bbox.x1 - 180), max(20, target.bbox.y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    if not cv2.imwrite(str(run_dir / "annotated.png"), annotated):
        raise TemplateAnchorError("cannot write annotated image")
    total_seconds = time.perf_counter() - started
    write_json(run_dir / "run.json", {"schema_version": 1, "status": status, "stage": "complete",
               "frame_id": capture["frame"]["id"], "image_sha256": capture["frame"]["image_sha256"],
               "timing_seconds": {"capture": capture_seconds, "ocr": ocr_seconds, "total": total_seconds},
               "ocr_elements": len(ocr["elements"]), "semantic_targets": len(targets), "cost": None})
    print(json.dumps({"status": status, "frame_id": capture["frame"]["id"],
                      "match_score": match["match_score"], "runner_up_margin": match["runner_up_margin"],
                      "targets": len(targets), "run_dir": str(run_dir)}))
    return 0 if status == "RESOLVED" else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("calibrate")
    make.add_argument("--reference-run", required=True)
    make.add_argument("--output-dir", required=True)
    make.add_argument("--anchor-id", default="WORLD_MAP_BUTTON")
    make.add_argument("--bbox", required=True)
    make.set_defaults(handler=calibrate)
    run = sub.add_parser("observe")
    run.add_argument("--calibration", required=True)
    run.add_argument("--run-dir", required=True)
    run.add_argument("--timeout-seconds", type=float, default=10.0)
    run.set_defaults(handler=observe)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TemplateAnchorError,
            WindowsCaptureError, ValueError) as exc:
        print(f"ground-rok-landmark: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
