"""Offline transactional training from an explicitly bound capture."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import train_queue_glyph


ROOT = Path(__file__).resolve().parents[1]


def _paint(frame, pattern, x, y):
    for row, line in enumerate(pattern):
        for column, pixel in enumerate(line):
            if pixel == "#":
                frame[y + row, x + column] = 255


def _setup(tmp_path, *, labels=("2", "/", "5"), size=(1366, 768)):
    raw = json.loads((ROOT / "config" / "queue_indicator_profile.json").read_text(encoding="utf-8"))
    known_two = raw["glyphs"].pop("2")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(raw), encoding="utf-8")
    frame = np.full((size[1], size[0]), 120, dtype=np.uint8)
    x, y = raw["roi"]["x"], raw["roi"]["y"]
    cursor = x + 12
    for label in labels:
        pattern = known_two if label == "2" else raw["glyphs"][label]
        if isinstance(pattern[0], list):
            pattern = pattern[0]
        _paint(frame, pattern, cursor, y + 3)
        cursor += len(pattern[0]) + 2
    image_path = tmp_path / "frame.png"
    assert cv2.imwrite(str(image_path), frame)
    manifest_path = tmp_path / "capture.json"
    identity = {
        "hwnd": 100, "pid": 200, "title": "ROK", "exe": "ROK.exe",
        "process_path": "C:/synthetic/ROK.exe",
    }
    snapshot = {**identity, "client_size": [1366, 768]}
    manifest = {
        "schema_version": 1,
        "status": "captured",
        "target": identity,
        "frame": {
            "id": "synthetic-frame-1",
            "captured_at": "2026-09-25T00:00:00+00:00",
            "width": 1366, "height": 768,
            "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        },
        "pre_capture": snapshot,
        "post_capture": snapshot,
        "png": str(image_path.resolve()),
        "non_interference": {
            "foreground_activation": False, "mouse_input": False,
            "keyboard_input": False, "desktop_fallback": False,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return profile, image_path, manifest_path


def _run(profile, image_path, manifest_path, value="2/5"):
    return train_queue_glyph.main([
        "--profile", str(profile), "--frame", str(image_path),
        "--manifest", str(manifest_path), "--value", value,
    ])


def test_success_commits_only_a_candidate_that_reads_the_operator_value(tmp_path):
    profile, image_path, manifest_path = _setup(tmp_path)
    before = profile.read_bytes()
    assert _run(profile, image_path, manifest_path) == 0
    assert profile.read_bytes() != before
    raw = json.loads(profile.read_bytes())
    assert "2" in raw["glyphs"]
    assert raw["training_sources"]["2/5"]["frame_id"] == "synthetic-frame-1"
    assert raw["training_sources"]["2/5"]["frame_sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert not list(tmp_path.glob(".profile.json.*.tmp"))


@pytest.mark.parametrize("case", [
    "wrong_label", "segmentation", "dimension", "hash", "path",
    "invalid_label", "profile_failure", "flat_manifest", "binding",
    "interference", "naive_time",
])
def test_refusals_preserve_original_profile_bytes(tmp_path, case):
    labels = ("2", "5") if case == "segmentation" else (("1", "/", "5") if case == "wrong_label" else ("2", "/", "5"))
    profile, image_path, manifest_path = _setup(tmp_path, labels=labels, size=(1920, 1080) if case == "dimension" else (1366, 768))
    value = "2/5"
    if case in {"hash", "path", "flat_manifest", "binding", "interference", "naive_time"}:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if case == "hash":
            manifest["frame"]["image_sha256"] = "0" * 64
        elif case == "path":
            manifest["png"] = str(tmp_path / "unrelated.png")
        elif case == "flat_manifest":
            manifest = {
                "frame_id": "synthetic-frame-1",
                "frame_path": image_path.name,
                "frame_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "client_size": [1366, 768],
            }
        elif case == "binding":
            manifest["post_capture"]["pid"] = 999
        elif case == "interference":
            manifest["non_interference"]["mouse_input"] = True
        elif case == "naive_time":
            manifest["frame"]["captured_at"] = "2026-09-25T00:00:00"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    if case == "invalid_label":
        value = "9/15"
    if case == "profile_failure":
        profile.write_text("{bad json", encoding="utf-8")
    before = profile.read_bytes()
    assert _run(profile, image_path, manifest_path, value) != 0
    assert profile.read_bytes() == before
    assert not list(tmp_path.glob(".profile.json.*.tmp"))


def test_atomic_replace_failure_keeps_original_profile(tmp_path, monkeypatch):
    profile, image_path, manifest_path = _setup(tmp_path)
    before = profile.read_bytes()

    def fail_replace(*_args):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(train_queue_glyph.os, "replace", fail_replace)
    assert _run(profile, image_path, manifest_path) != 0
    assert profile.read_bytes() == before
    assert not list(tmp_path.glob(".profile.json.*.tmp"))


def test_existing_lock_refuses_update_without_profile_loss(tmp_path):
    profile, image_path, manifest_path = _setup(tmp_path)
    before = profile.read_bytes()
    lock = profile.with_name(profile.name + ".lock")
    lock.write_text("another writer", encoding="utf-8")
    assert _run(profile, image_path, manifest_path) != 0
    assert profile.read_bytes() == before
    assert lock.read_text(encoding="utf-8") == "another writer"


def test_changed_profile_refuses_update_and_releases_lock(tmp_path):
    profile, _, _ = _setup(tmp_path)
    original = profile.read_bytes()
    profile.write_bytes(b"concurrent change")
    with pytest.raises(ValueError, match="profile changed"):
        train_queue_glyph._atomic_profile_update(profile, original, b"candidate")
    assert profile.read_bytes() == b"concurrent change"
    assert not profile.with_name(profile.name + ".lock").exists()
