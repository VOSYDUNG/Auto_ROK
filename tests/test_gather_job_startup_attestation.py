"""Synthetic native-frame evidence for offline startup attestation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from harness.gather_job_startup_attestation import (
    StartupAttestationError, build_startup_attestation,
    canonical_startup_attestation_path,
    validate_startup_attestation, write_startup_attestation,
)
from scripts.create_gather_job import build_artifact


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _paint(frame: np.ndarray, pattern: list[str], x: int, y: int) -> None:
    for row, line in enumerate(pattern):
        for col, pixel in enumerate(line):
            if pixel == "#":
                frame[y + row, x + col] = 255


def _fixture(tmp_path: Path, *, queue: str = "0/5", cropped: bool = False) -> tuple[dict, Path]:
    workspace = tmp_path / "workspace"
    capture_dir = workspace / "runs" / "synthetic"
    capture_dir.mkdir(parents=True)
    job_path = workspace / "job.json"
    job = build_artifact(
        job_id="job-synthetic", task_id="task-1", character_id="governor-a",
        resource_type="FOOD", resource_level=None,
        starts_at=NOW - timedelta(minutes=2), expires_at=NOW + timedelta(minutes=5),
    )
    job_path.write_text(json.dumps(job), encoding="utf-8")
    raw_profile = json.loads((ROOT / "config" / "queue_indicator_profile.json").read_text(encoding="utf-8"))
    raw_profile["glyphs"]["0"] = raw_profile["glyphs"].pop("2")
    profile_path = workspace / "synthetic-profile.json"
    profile_path.write_text(json.dumps(raw_profile), encoding="utf-8")
    frame = np.full((768, 1366), 120, dtype=np.uint8)
    cursor = raw_profile["roi"]["x"] + 12
    top = raw_profile["roi"]["y"] + 3
    for label in queue:
        pattern = raw_profile["glyphs"][label]
        if isinstance(pattern[0], list):
            pattern = pattern[0]
        _paint(frame, pattern, cursor, top)
        cursor += len(pattern[0]) + 2
    frame_path = capture_dir / "rok-client.png"
    assert cv2.imwrite(str(frame_path), frame)
    identity = {
        "hwnd": 101, "pid": 202, "title": "Rise of Kingdoms", "exe": "MASS.exe",
        "process_path": r"C:\Games\MASS.exe",
    }
    snapshot = {
        **identity, "client_size": [1366, 768],
        "window_rect": [10, 20, 1396, 828],
        "client_screen_rect": [20, 50, 1386, 818],
    }
    capture = {
        "schema_version": 1, "status": "captured",
        "backend": {"name": "windows-capture", "target_mode": "window_hwnd"},
        "target": identity,
        "pre_capture": snapshot,
        "post_capture": dict(snapshot),
        "frame": {
            "id": "synthetic-first-frame", "captured_at": (NOW - timedelta(seconds=2)).isoformat(),
            "width": 1366, "height": 768,
            "client_bounds": [0, 0, 1366, 768],
            "image_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
        },
        "capture_mapping": {
            "method": "window_rect_to_client" if cropped else "capture_frame_is_client",
            "source_frame_size": [1386, 808] if cropped else [1366, 768],
            "client_crop_in_source": [10, 30, 1366, 768] if cropped else [0, 0, 1366, 768],
        },
        "png": str(frame_path.resolve()),
        "non_interference": {
            "foreground_activation": False, "mouse_input": False,
            "keyboard_input": False, "desktop_fallback": False,
        },
    }
    manifest_path = capture_dir / "capture.json"
    manifest_path.write_text(json.dumps(capture), encoding="utf-8")
    kwargs = {
        "job_artifact": job_path, "manifest_path": manifest_path,
        "frame_path": frame_path, "profile_path": profile_path,
        "ledger_root": workspace / "checkpoints" / "gather-jobs",
        "workspace_root": workspace,
        "mission_flows": ROOT / "config" / "mission_flows.yaml",
        "ui_states": ROOT / "config" / "ui_states.yaml",
        "resource_type": "FOOD", "resource_level": None,
        "affirmative_character_id": "governor-a", "now": NOW,
    }
    return kwargs, canonical_startup_attestation_path("job-synthetic", workspace)


def _mutate_json(path: Path, change) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("cropped", [False, True])
def test_synthetic_native_capture_creates_one_record_and_validates(
    tmp_path: Path, cropped: bool,
) -> None:
    kwargs, output = _fixture(tmp_path, cropped=cropped)
    record = build_startup_attestation(**kwargs)
    assert record["queue"]["used"] == 0
    assert record["queue"]["capacity"] == 5
    assert record["operator_assertion"]["evidence_class"] == "operator_assertion_not_ui_identity"
    assert record["capture"]["client_binding"]["pid"] == 202
    assert record["job_artifact_sha256"] == hashlib.sha256(kwargs["job_artifact"].read_bytes()).hexdigest()
    write_startup_attestation(output, kwargs["workspace_root"], record)
    validation = {k: v for k, v in kwargs.items() if k != "affirmative_character_id"}
    assert validate_startup_attestation(output, **validation) == record
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_startup_attestation(output, kwargs["workspace_root"], record)
    assert output.read_bytes() == before


def test_second_output_path_and_copied_record_are_invalid(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = build_startup_attestation(**kwargs)
    write_startup_attestation(output, kwargs["workspace_root"], record)
    foreign_path = kwargs["workspace_root"] / "attestations" / "different.json"
    with pytest.raises(StartupAttestationError):
        write_startup_attestation(foreign_path, kwargs["workspace_root"], record)
    assert not foreign_path.exists()
    foreign_path.write_bytes(output.read_bytes())
    validation = {k: v for k, v in kwargs.items() if k != "affirmative_character_id"}
    with pytest.raises(StartupAttestationError):
        validate_startup_attestation(foreign_path, **validation)
    assert validate_startup_attestation(output, **validation) == record


def test_operational_cli_rejects_profile_and_output_overrides() -> None:
    from scripts.attest_gather_job import main
    common = [
        "--job-artifact", "job.json", "--resource-type", "FOOD",
        "--manifest", "capture.json", "--frame", "frame.png",
        "--affirm-character-id", "governor-a",
    ]
    for override in (["--profile", "synthetic.json"], ["--output", "other.json"]):
        with pytest.raises(SystemExit) as exit_info:
            main([*common, *override])
        assert exit_info.value.code == 2


@pytest.mark.parametrize("case", [
    "no_assertion", "wrong_assertion", "stale", "before_job", "expired", "revoked",
    "nonzero_queue", "unknown_glyph", "ambiguous_glyph", "foreign_window",
    "changed_client", "changed_hash", "wrong_png", "interference", "wrong_catalog",
    "outside_output", "flat_manifest", "cropped_frame", "wrong_crop_geometry",
    "changed_window_geometry",
])
def test_refuses_unsourced_or_invalid_startup_without_output(tmp_path: Path, case: str) -> None:
    kwargs, output = _fixture(
        tmp_path, queue="1/5" if case == "nonzero_queue" else "0/5",
        cropped=case == "wrong_crop_geometry",
    )
    if case == "no_assertion":
        kwargs["affirmative_character_id"] = ""
    elif case == "wrong_assertion":
        kwargs["affirmative_character_id"] = "governor-b"
    elif case == "stale":
        _mutate_json(kwargs["manifest_path"], lambda v: v["frame"].update(
            captured_at=(NOW - timedelta(seconds=31)).isoformat()))
    elif case == "before_job":
        _mutate_json(kwargs["manifest_path"], lambda v: v["frame"].update(
            captured_at=(NOW - timedelta(minutes=3)).isoformat()))
    elif case == "expired":
        kwargs["now"] = NOW + timedelta(minutes=6)
    elif case == "revoked":
        from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
        from harness.gather_job_authority import compiled_gather_catalog
        from harness.mission_loader import compile_mission
        catalog = compiled_gather_catalog(compile_mission(
            kwargs["mission_flows"], kwargs["ui_states"], "GATHER_RESOURCE",
            {"resource_type": "FOOD", "resource_level": None},
        ))
        job = load_gather_job_authority(kwargs["job_artifact"],
                                        canonical_actions=catalog.actions,
                                        expected_catalog_digest=catalog.digest)
        JsonGatherJobStore(kwargs["ledger_root"]).revoke(job)
    elif case == "unknown_glyph":
        _mutate_json(kwargs["profile_path"], lambda v: v["glyphs"].pop("0"))
    elif case == "ambiguous_glyph":
        _mutate_json(kwargs["profile_path"], lambda v: v["glyphs"].update(
            {"2": v["glyphs"]["0"]}))
    elif case == "foreign_window":
        _mutate_json(kwargs["manifest_path"], lambda v: [part.update(
            title="Other Game") for part in (v["target"], v["pre_capture"], v["post_capture"])])
    elif case == "changed_client":
        _mutate_json(kwargs["manifest_path"], lambda v: v["post_capture"].update(pid=999))
    elif case == "changed_hash":
        _mutate_json(kwargs["manifest_path"], lambda v: v["frame"].update(image_sha256="0" * 64))
    elif case == "wrong_png":
        _mutate_json(kwargs["manifest_path"], lambda v: v.update(png=str(tmp_path / "other.png")))
    elif case == "interference":
        _mutate_json(kwargs["manifest_path"], lambda v: v["non_interference"].update(mouse_input=True))
    elif case == "wrong_catalog":
        kwargs["resource_type"] = "WOOD"
    elif case == "outside_output":
        output = tmp_path / "outside.json"
    elif case == "flat_manifest":
        kwargs["manifest_path"].write_text('{"status":"captured"}', encoding="utf-8")
    elif case == "cropped_frame":
        _mutate_json(kwargs["manifest_path"], lambda v: v["capture_mapping"].update(
            method="cropped_from_desktop"))
    elif case == "wrong_crop_geometry":
        _mutate_json(kwargs["manifest_path"], lambda v: v["capture_mapping"].update(
            client_crop_in_source=[11, 30, 1366, 768]))
    elif case == "changed_window_geometry":
        _mutate_json(kwargs["manifest_path"], lambda v: v["post_capture"].update(
            window_rect=[11, 20, 1397, 828]))
    if case == "outside_output":
        record = build_startup_attestation(**kwargs)
        with pytest.raises(StartupAttestationError):
            write_startup_attestation(output, kwargs["workspace_root"], record)
    else:
        with pytest.raises((ValueError, RuntimeError)):
            record = build_startup_attestation(**kwargs)
            write_startup_attestation(output, kwargs["workspace_root"], record)
    assert not output.exists()


def test_validator_rejects_changed_job_and_record(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = build_startup_attestation(**kwargs)
    write_startup_attestation(output, kwargs["workspace_root"], record)
    validation = {k: v for k, v in kwargs.items() if k != "affirmative_character_id"}
    _mutate_json(output, lambda v: v["capture"].update(frame_id="substituted"))
    with pytest.raises(StartupAttestationError):
        validate_startup_attestation(output, **validation)
    output.write_text(json.dumps(record), encoding="utf-8")
    kwargs["job_artifact"].write_bytes(kwargs["job_artifact"].read_bytes() + b" ")
    with pytest.raises(StartupAttestationError):
        validate_startup_attestation(output, **validation)


def test_untrained_profile_copy_cannot_attest_synthetic_zero(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    _mutate_json(kwargs["profile_path"], lambda v: v["glyphs"].pop("0"))
    with pytest.raises(StartupAttestationError):
        write_startup_attestation(
            output, kwargs["workspace_root"], build_startup_attestation(**kwargs),
        )
    assert not output.exists()
