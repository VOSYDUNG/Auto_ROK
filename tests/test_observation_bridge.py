from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.observation_bridge import CandidateSpec, ObservationBridgeError, project_observation


NOW = datetime(2026, 9, 14, 3, 0, 5, tzinfo=timezone.utc)


def evidence(tmp_path: Path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"synthetic-png-fixture")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    capture = {
        "schema_version": 1, "status": "captured",
        "backend": {"name": "fixture-capture", "version": "1"},
        "target": {"title": "Rise of Kingdoms", "exe": "MASS.exe", "hwnd": 123, "pid": 456},
        "frame": {"id": "frame-001", "captured_at": "2026-09-14T03:00:00Z", "width": 800, "height": 600,
                  "client_bounds": [0, 0, 800, 600], "dpi_scale": 1.25, "image_sha256": digest},
    }
    ocr = {
        "schema_version": 1, "frame_id": "frame-001", "image_sha256": digest,
        "coordinate_space": "ocr_crop_pixels", "output_coordinate_space": "client_pixels",
        "client_bounds": [0, 0, 800, 600], "dpi_scale": 1.25,
        "backend": {"name": "fixture-ocr", "version": "1"}, "crop": [100, 50, 400, 300],
        "scale_x": 2.0, "scale_y": 2.0, "text": "Claim",
        "elements": [{"text": "Claim", "bbox": [20, 30, 100, 40], "confidence": 0.97}],
    }
    return image, capture, ocr


def test_projects_current_ocr_into_existing_contracts(tmp_path: Path) -> None:
    image, capture, ocr = evidence(tmp_path)
    result = project_observation(capture, ocr, image, (CandidateSpec("CLAIM_BUTTON", ("Claim",), 0.9),), now=NOW)

    assert result.status == "READY"
    assert result.observation.frame_id == result.scene.frame_id == "frame-001"
    target = result.scene.require_target("CLAIM_BUTTON", 0.9)
    assert (target.bbox.x1, target.bbox.y1, target.bbox.x2, target.bbox.y2) == (110, 65, 160, 85)
    assert target.metadata["image_sha256"] == capture["frame"]["image_sha256"]
    assert target.metadata["calibrated_anchor"] is False
    assert result.scene.facts["capture_backend"]["name"] == "fixture-capture"


@pytest.mark.parametrize("mutation,message", [
    (lambda capture, ocr: capture["target"].update(exe="other.exe"), "identity"),
    (lambda capture, ocr: ocr.update(client_bounds=[0, 0, 801, 600]), "bounds"),
    (lambda capture, ocr: ocr.update(dpi_scale=1.0), "DPI"),
    (lambda capture, ocr: ocr.update(frame_id="different"), "frame id/hash"),
])
def test_rejects_cross_frame_or_cross_window_evidence(tmp_path: Path, mutation, message: str) -> None:
    image, capture, ocr = evidence(tmp_path)
    mutation(capture, ocr)
    with pytest.raises(ObservationBridgeError, match=message):
        project_observation(capture, ocr, image, now=NOW)


def test_rejects_stale_future_unordered_and_missing_image(tmp_path: Path) -> None:
    image, capture, ocr = evidence(tmp_path)
    with pytest.raises(ObservationBridgeError, match="stale"):
        project_observation(capture, ocr, image, now=datetime(2026, 9, 14, 3, 1, tzinfo=timezone.utc))
    with pytest.raises(ObservationBridgeError, match="future"):
        project_observation(capture, ocr, image, now=datetime(2026, 9, 14, 2, 59, tzinfo=timezone.utc))
    with pytest.raises(ObservationBridgeError, match="unordered"):
        project_observation(capture, ocr, image, now=NOW, previous_timestamp=NOW.timestamp())
    image.unlink()
    with pytest.raises(ObservationBridgeError, match="missing"):
        project_observation(capture, ocr, image, now=NOW)


def test_rejects_bad_bbox_and_hash(tmp_path: Path) -> None:
    image, capture, ocr = evidence(tmp_path)
    ocr["elements"][0]["bbox"] = [750, 30, 100, 40]
    with pytest.raises(ObservationBridgeError, match="exceeds OCR crop"):
        project_observation(capture, ocr, image, now=NOW)
    _, capture, ocr = evidence(tmp_path)
    capture["frame"]["image_sha256"] = "0" * 64
    ocr["image_sha256"] = "0" * 64
    with pytest.raises(ObservationBridgeError, match="persisted frame image hash"):
        project_observation(capture, ocr, image, now=NOW)


def test_missing_ambiguous_and_null_confidence_require_decision(tmp_path: Path) -> None:
    image, capture, ocr = evidence(tmp_path)
    ocr["elements"].append({"text": "Claim", "bbox": [150, 30, 80, 40], "confidence": 0.95})
    ambiguous = project_observation(capture, ocr, image, (CandidateSpec("CLAIM", ("Claim",), 0.9),), now=NOW)
    assert ambiguous.status == "NEEDS_DECISION"
    assert ambiguous.decisions[0]["reason"] == "candidate_ambiguous"
    assert ambiguous.scene.targets == ()

    ocr["elements"] = [{"text": "Claim", "bbox": [20, 30, 100, 40], "confidence": None}]
    missing = project_observation(capture, ocr, image, (CandidateSpec("CLAIM", ("Claim",)),), now=NOW)
    assert missing.status == "NEEDS_DECISION"
    assert missing.decisions[0]["reason"] == "candidate_missing"
    assert missing.observation.evidence[0].metadata["coordinate_space"] == "client_pixels"
    assert missing.observation.evidence[0].metadata["raw_confidence"] is None
    assert missing.observation.evidence[0].metadata["confidence_known"] is False


def test_cli_emits_json_without_importing_legacy_or_actuator(tmp_path: Path) -> None:
    import scripts.observe_rok_window as cli
    image, capture, ocr = evidence(tmp_path)
    fixture_dir = Path(__file__).resolve().parents[1] / "workspace" / "runs" / ".pytest-observation-fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    try:
        local_image = fixture_dir / "frame.png"
        local_image.write_bytes(image.read_bytes())
        (fixture_dir / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
        (fixture_dir / "ocr.json").write_text(json.dumps(ocr), encoding="utf-8")
        output = fixture_dir / "result.json"
        code = cli.main(["--capture", str(fixture_dir / "capture.json"), "--ocr", str(fixture_dir / "ocr.json"),
                         "--image", str(local_image), "--output", str(output), "--now", NOW.isoformat()])
        assert code == 0
        assert json.loads(output.read_text())["status"] == "READY"
        probe = subprocess.run(
            [sys.executable, "-c", "import sys,scripts.observe_rok_window; "
             "print('main' in sys.modules, 'harness.anticipatory_motor' in sys.modules)"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
        )
        assert probe.stdout.strip() == "False False"
    finally:
        for item in fixture_dir.iterdir():
            item.unlink()
        fixture_dir.rmdir()


def test_cli_rejects_source_output_without_overwrite() -> None:
    import scripts.observe_rok_window as cli
    source = Path(__file__).resolve().parents[1] / "harness" / "human_io.py"
    sentinel = source.read_bytes()
    code = cli.main(["--capture", str(source), "--ocr", str(source),
                     "--image", str(source), "--output", str(source)])
    assert code == 2
    assert source.read_bytes() == sentinel
