"""Focused offline evidence for the first native frame startup attestation."""
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
    canonical_startup_attestation_path, validate_canonical_startup_attestation,
    validate_startup_attestation, write_startup_attestation,
)
from scripts.create_gather_job import build_artifact

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _fixture(tmp_path: Path) -> tuple[dict, Path]:
    workspace = tmp_path / "workspace"
    capture_dir = workspace / "runs" / "synthetic"
    capture_dir.mkdir(parents=True)
    job_path = workspace / "job.json"
    job_path.write_text(json.dumps(build_artifact(
        job_id="job-synthetic", task_id="task-1", character_id="governor-a",
        resource_type="FOOD", resource_level=None,
        starts_at=NOW - timedelta(minutes=2), expires_at=NOW + timedelta(minutes=5),
    )), encoding="utf-8")
    frame = np.full((768, 1366), 120, dtype=np.uint8)
    frame_path = capture_dir / "rok-client.png"
    assert cv2.imwrite(str(frame_path), frame)
    identity = {"hwnd": 101, "pid": 202, "title": "Rise of Kingdoms", "exe": "MASS.exe",
                "process_path": r"C:\Games\MASS.exe"}
    snapshot = {**identity, "client_size": [1366, 768],
                "window_rect": [10, 20, 1396, 828],
                "client_screen_rect": [20, 50, 1386, 818]}
    capture = {"schema_version": 1, "status": "captured",
               "backend": {"name": "windows-capture", "target_mode": "window_hwnd"},
               "target": identity, "pre_capture": snapshot, "post_capture": dict(snapshot),
               "frame": {"id": "synthetic-first-frame",
                         "captured_at": (NOW - timedelta(seconds=2)).isoformat(),
                         "width": 1366, "height": 768, "client_bounds": [0, 0, 1366, 768],
                         "image_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest()},
               "capture_mapping": {"method": "capture_frame_is_client",
                                   "source_frame_size": [1366, 768],
                                   "client_crop_in_source": [0, 0, 1366, 768]},
               "png": str(frame_path.resolve()),
               "non_interference": {"foreground_activation": False, "mouse_input": False,
                                    "keyboard_input": False, "desktop_fallback": False}}
    manifest_path = capture_dir / "capture.json"
    manifest_path.write_text(json.dumps(capture), encoding="utf-8")
    kwargs = {"job_artifact": job_path, "manifest_path": manifest_path, "frame_path": frame_path,
              "ledger_root": workspace / "checkpoints" / "gather-jobs", "workspace_root": workspace,
              "mission_flows": ROOT / "config" / "mission_flows.yaml",
              "ui_states": ROOT / "config" / "ui_states.yaml", "resource_type": "FOOD",
              "resource_level": None, "affirmative_character_id": "governor-a", "now": NOW}
    return kwargs, canonical_startup_attestation_path("job-synthetic", workspace)


def _write(kwargs: dict, output: Path) -> dict:
    record = build_startup_attestation(**kwargs)
    write_startup_attestation(output, kwargs["workspace_root"], record)
    return record


def _consumer_kwargs(kwargs: dict) -> dict:
    return {key: kwargs[key] for key in ("resource_type", "resource_level", "workspace_root",
                                         "ledger_root", "mission_flows", "ui_states")}


def test_blank_native_first_frame_attests_with_queue_unmeasured(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = _write(kwargs, output)
    assert record["schema_version"] == 2
    assert record["queue"] == {"status": "unmeasured_before_first_march", "observed": False,
                               "source": "native_first_frame_no_queue_assertion"}
    assert validate_startup_attestation(output, **{k: v for k, v in kwargs.items()
                                                   if k != "affirmative_character_id"}) == record
    with pytest.raises(FileExistsError):
        write_startup_attestation(output, kwargs["workspace_root"], record)


@pytest.mark.parametrize("field", ["affirmative_character_id", "manifest_path", "frame_path"])
def test_wrong_character_or_capture_source_rejected(tmp_path: Path, field: str) -> None:
    kwargs, output = _fixture(tmp_path)
    _write(kwargs, output)
    if field == "affirmative_character_id":
        kwargs[field] = "governor-b"
    else:
        kwargs[field] = kwargs[field].with_name("missing.json")
    with pytest.raises((StartupAttestationError, FileNotFoundError)):
        build_startup_attestation(**kwargs)


def test_v1_and_altered_record_are_rejected(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = _write(kwargs, output)
    record["schema_version"] = 1
    output.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StartupAttestationError, match="schema|v1"):
        validate_startup_attestation(output, **{k: v for k, v in kwargs.items()
                                                if k != "affirmative_character_id"})


@pytest.mark.parametrize("alter", ["frame", "manifest_client", "job", "record"])
def test_attestation_rechecks_immutable_job_capture_and_assertion_sources(
    tmp_path: Path, alter: str,
) -> None:
    kwargs, output = _fixture(tmp_path)
    _write(kwargs, output)
    if alter == "frame":
        kwargs["frame_path"].write_bytes(b"changed frame")
    elif alter == "manifest_client":
        manifest = json.loads(kwargs["manifest_path"].read_text(encoding="utf-8"))
        manifest["post_capture"]["pid"] = 999
        kwargs["manifest_path"].write_text(json.dumps(manifest), encoding="utf-8")
    elif alter == "job":
        artifact = json.loads(kwargs["job_artifact"].read_text(encoding="utf-8"))
        artifact["character_id"] = "other-character"
        kwargs["job_artifact"].write_text(json.dumps(artifact), encoding="utf-8")
    else:
        record = json.loads(output.read_text(encoding="utf-8"))
        record["queue"]["observed"] = True
        output.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StartupAttestationError):
        validate_startup_attestation(output, **{k: v for k, v in kwargs.items()
                                                if k != "affirmative_character_id"})


def test_attestation_cannot_be_relocated_or_reissued_after_first_dispatch(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = _write(kwargs, output)
    copied = output.with_name("copied.json")
    copied.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StartupAttestationError, match="canonical"):
        validate_startup_attestation(copied, **{k: v for k, v in kwargs.items()
                                                if k != "affirmative_character_id"})
    from harness.gather_job_authority import compiled_gather_catalog
    from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
    from harness.mission_loader import compile_mission
    catalog = compiled_gather_catalog(compile_mission(
        kwargs["mission_flows"], kwargs["ui_states"], "GATHER_RESOURCE",
        {"resource_type": "FOOD", "resource_level": None},
    ))
    job = load_gather_job_authority(kwargs["job_artifact"],
                                    canonical_actions=catalog.actions,
                                    expected_catalog_digest=catalog.digest)
    ledger = JsonGatherJobStore(kwargs["ledger_root"])
    ledger.bind_client(job, {"hwnd": 101, "pid": 202,
                             "process_path": r"C:\Games\MASS.exe"})
    ledger.reserve_dispatch(job, run_id="first-run", frame_id="new-troop-frame",
                            action="MARCH_WITH_CURRENT_SELECTION", now=NOW)
    with pytest.raises(StartupAttestationError, match="already dispatched"):
        build_startup_attestation(**kwargs)
    # The original assertion remains checkable during the authorized job.
    assert validate_canonical_startup_attestation(
        kwargs["job_artifact"], job.job_id, **_consumer_kwargs(kwargs),
        now=NOW + timedelta(minutes=1),
    ) == hashlib.sha256(output.read_bytes()).hexdigest()


def test_attestation_rejects_malformed_png_even_when_manifest_hash_matches(tmp_path: Path) -> None:
    kwargs, _ = _fixture(tmp_path)
    malformed = b"\x89PNG\r\n\x1a\nnot-a-decodable-image"
    kwargs["frame_path"].write_bytes(malformed)
    manifest = json.loads(kwargs["manifest_path"].read_text(encoding="utf-8"))
    manifest["frame"]["image_sha256"] = hashlib.sha256(malformed).hexdigest()
    kwargs["manifest_path"].write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StartupAttestationError, match="cannot be decoded"):
        build_startup_attestation(**kwargs)


def test_canonical_hash_continuity_and_job_expiry(tmp_path: Path) -> None:
    kwargs, output = _fixture(tmp_path)
    record = _write(kwargs, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert validate_canonical_startup_attestation(kwargs["job_artifact"], "job-synthetic",
                                                  **_consumer_kwargs(kwargs),
                                                  expected_sha256=digest, now=NOW) == digest
    with pytest.raises(StartupAttestationError, match="digest"):
        validate_canonical_startup_attestation(kwargs["job_artifact"], "job-synthetic",
                                              **_consumer_kwargs(kwargs),
                                              expected_sha256="0" * 64, now=NOW)
    with pytest.raises(StartupAttestationError, match="expired"):
        validate_canonical_startup_attestation(kwargs["job_artifact"], "job-synthetic",
                                              **_consumer_kwargs(kwargs), now=NOW + timedelta(minutes=6))
    from harness.gather_job_authority import compiled_gather_catalog
    from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
    from harness.mission_loader import compile_mission
    catalog = compiled_gather_catalog(compile_mission(
        kwargs["mission_flows"], kwargs["ui_states"], "GATHER_RESOURCE",
        {"resource_type": "FOOD", "resource_level": None},
    ))
    job = load_gather_job_authority(kwargs["job_artifact"],
                                    canonical_actions=catalog.actions,
                                    expected_catalog_digest=catalog.digest)
    JsonGatherJobStore(kwargs["ledger_root"]).revoke(job)
    with pytest.raises(StartupAttestationError, match="revoked"):
        validate_canonical_startup_attestation(kwargs["job_artifact"], "job-synthetic",
                                              **_consumer_kwargs(kwargs), now=NOW)
    assert record["job_id"] == "job-synthetic"
