"""Offline, one-time evidence record for a GATHER job's starting character.

The character identity is an explicit operator assertion about the captured
client, not a name inferred from pixels. This record grants no input authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
from typing import Any

import cv2
import numpy as np

from harness.gather_job_authority import compiled_gather_catalog
from harness.gather_job_store import GatherClientBinding, JsonGatherJobStore, load_gather_job_authority
from harness.mission_loader import compile_mission
from harness.queue_indicator import QueueIndicatorProfile, QueueIndicatorReader, QueueReadStatus


class StartupAttestationError(ValueError):
    """Startup evidence is missing, stale, conflicting, or outside job scope."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StartupAttestationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise StartupAttestationError("capture time is missing")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StartupAttestationError("capture time is invalid") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise StartupAttestationError("capture time needs a timezone")
    return instant


def _within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise StartupAttestationError("attestation paths must be under workspace")
    return resolved


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_startup_attestation_path(job_id: str, workspace_root: Path) -> Path:
    """The sole valid artifact location for a job, using its full ID digest."""
    if not isinstance(job_id, str) or not job_id.strip():
        raise StartupAttestationError("attestation needs a nonempty job ID")
    digest = _sha(job_id.encode("utf-8"))
    return workspace_root.resolve() / "attestations" / f"gather-job-{digest}.json"


def _rect(snapshot: dict[str, Any], key: str) -> tuple[int, int, int, int]:
    value = snapshot.get(key)
    if (not isinstance(value, list) or len(value) != 4
            or any(type(part) is not int for part in value)
            or value[2] <= value[0] or value[3] <= value[1]):
        raise StartupAttestationError(f"capture {key} is invalid")
    return tuple(value)


def build_startup_attestation(
    *, job_artifact: Path, manifest_path: Path, frame_path: Path,
    profile_path: Path, ledger_root: Path, workspace_root: Path,
    mission_flows: Path, ui_states: Path, resource_type: str,
    resource_level: int | None, affirmative_character_id: str,
    now: datetime | None = None, max_age_seconds: float = 30.0,
    require_unused_job: bool = True,
) -> dict[str, Any]:
    """Verify source artifacts and prepare a record without writing anything."""
    instant = now if now is not None else datetime.now(timezone.utc)
    if (not isinstance(instant, datetime) or instant.tzinfo is None
            or instant.utcoffset() is None or max_age_seconds <= 0):
        raise StartupAttestationError("invalid attestation time or age limit")
    if resource_type not in {"FOOD", "WOOD", "STONE", "GOLD"} or (
        resource_level is not None and type(resource_level) is not int
    ):
        raise StartupAttestationError("invalid GATHER resource parameters")
    job_artifact = _within(job_artifact, workspace_root)
    manifest_path = _within(manifest_path, workspace_root)
    frame_path = _within(frame_path, workspace_root)
    if manifest_path.name != "capture.json" or frame_path.parent != manifest_path.parent:
        raise StartupAttestationError("native capture.json and PNG must share a directory")
    if frame_path.suffix.lower() != ".png":
        raise StartupAttestationError("capture frame must be PNG")
    compiled = compile_mission(mission_flows, ui_states, "GATHER_RESOURCE", {
        "resource_type": resource_type, "resource_level": resource_level,
    })
    catalog = compiled_gather_catalog(compiled)
    job_bytes = job_artifact.read_bytes()
    job = load_gather_job_authority(
        job_artifact, canonical_actions=catalog.actions,
        expected_catalog_digest=catalog.digest,
    )
    if affirmative_character_id != job.character_id:
        raise StartupAttestationError("operator character assertion differs from job")
    if not job.starts_at <= instant < job.expires_at:
        raise StartupAttestationError("job is not active at attestation")
    store = JsonGatherJobStore(ledger_root)
    progress = store.progress(job)
    if progress.revoked or (require_unused_job and (
        progress.dispatched_marches != 0 or progress.verified_marches != 0
    )):
        raise StartupAttestationError("job is revoked or has already dispatched")

    manifest_bytes = manifest_path.read_bytes()
    manifest = _json(manifest_path)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "captured"
            or not isinstance(manifest.get("backend"), dict)
            or manifest["backend"].get("name") != "windows-capture"
            or manifest["backend"].get("target_mode") != "window_hwnd"):
        raise StartupAttestationError("capture is not a native window capture")
    target, before, after = (
        manifest.get("target"), manifest.get("pre_capture"), manifest.get("post_capture")
    )
    if not all(isinstance(item, dict) for item in (target, before, after)):
        raise StartupAttestationError("capture lacks target and pre/post client snapshots")
    identity = ("hwnd", "pid", "title", "exe", "process_path")
    if any(target.get(key) is None or target.get(key) != before.get(key)
           or target.get(key) != after.get(key) for key in identity):
        raise StartupAttestationError("capture client changed across snapshots")
    if target["title"] != "Rise of Kingdoms" or target["exe"] != "MASS.exe" or (
        ntpath.basename(target["process_path"]).casefold() != "mass.exe"
    ):
        raise StartupAttestationError("capture is not the expected ROK client")
    binding = GatherClientBinding.from_window(target)
    previous_binding = store.client_binding(job)
    if previous_binding is not None and previous_binding != binding:
        raise StartupAttestationError("job ledger is bound to another client")
    frame = manifest.get("frame")
    if not isinstance(frame, dict):
        raise StartupAttestationError("capture frame metadata is missing")
    frame_id, frame_sha = frame.get("id"), frame.get("image_sha256")
    if (not isinstance(frame_id, str) or not frame_id.strip()
            or not isinstance(frame_sha, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", frame_sha) is None):
        raise StartupAttestationError("capture frame ID or hash is invalid")
    captured_at = _instant(frame.get("captured_at"))
    if (not job.starts_at <= captured_at < job.expires_at
            or not 0 <= (instant - captured_at).total_seconds() <= max_age_seconds):
        raise StartupAttestationError("capture is stale, future, or outside job window")
    profile_bytes = profile_path.read_bytes()
    profile = QueueIndicatorProfile.from_mapping(_json(profile_path))
    size = list(profile.client_size)
    if ([frame.get("width"), frame.get("height")] != size
            or frame.get("client_bounds") != [0, 0, *size]
            or before.get("client_size") != size or after.get("client_size") != size):
        raise StartupAttestationError("capture client dimensions differ from profile")
    window = _rect(before, "window_rect")
    client = _rect(before, "client_screen_rect")
    if (_rect(after, "window_rect") != window
            or _rect(after, "client_screen_rect") != client
            or (client[2] - client[0], client[3] - client[1]) != profile.client_size
            or client[0] < window[0] or client[1] < window[1]
            or client[2] > window[2] or client[3] > window[3]):
        raise StartupAttestationError("capture window/client geometry changed or is inconsistent")
    mapping = manifest.get("capture_mapping")
    if not isinstance(mapping, dict):
        raise StartupAttestationError("capture mapping is missing")
    method = mapping.get("method")
    if method == "capture_frame_is_client":
        expected_source = size
        expected_crop = [0, 0, *size]
    elif method == "window_rect_to_client":
        expected_source = [window[2] - window[0], window[3] - window[1]]
        expected_crop = [client[0] - window[0], client[1] - window[1], *size]
    else:
        raise StartupAttestationError("capture mapping method is not native")
    if (mapping.get("source_frame_size") != expected_source
            or mapping.get("client_crop_in_source") != expected_crop):
        raise StartupAttestationError("capture mapping differs from stable client geometry")
    png = manifest.get("png")
    if not isinstance(png, str) or not png or Path(png).resolve() != frame_path:
        raise StartupAttestationError("PNG path differs from native capture manifest")
    flags = ("foreground_activation", "mouse_input", "keyboard_input", "desktop_fallback")
    non_interference = manifest.get("non_interference")
    if not isinstance(non_interference, dict) or any(
        non_interference.get(flag) is not False for flag in flags
    ):
        raise StartupAttestationError("capture non-interference flags are missing")
    frame_bytes = frame_path.read_bytes()
    if not frame_bytes.startswith(b"\x89PNG\r\n\x1a\n") or _sha(frame_bytes) != frame_sha.lower():
        raise StartupAttestationError("capture PNG hash differs from manifest")
    image = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise StartupAttestationError("capture PNG cannot be decoded")
    reading = QueueIndicatorReader(profile).read(image)
    if reading.status is not QueueReadStatus.READ or (reading.used, reading.capacity) != (0, 5):
        raise StartupAttestationError(f"startup march queue is not sourced 0/5: {reading.status.value}")
    # The operator assertion is deliberately distinct from observed UI facts.
    return {
        "schema_version": 1, "status": "startup_attested_offline",
        "authority": "operator_assertion_only_no_input_authority",
        "job_id": job.job_id, "task_id": job.task_id,
        "character_id": job.character_id, "catalog_digest": job.catalog_digest,
        "job_artifact": str(job_artifact), "job_artifact_sha256": _sha(job_bytes),
        "operator_assertion": {
            "character_id": affirmative_character_id,
            "meaning": "operator_affirms_currently_open_character",
            "affirmed_at": instant.isoformat(),
            "evidence_class": "operator_assertion_not_ui_identity",
        },
        "capture": {
            "manifest_path": str(manifest_path), "manifest_sha256": _sha(manifest_bytes),
            "frame_path": str(frame_path), "frame_id": frame_id,
            "frame_sha256": _sha(frame_bytes), "captured_at": captured_at.isoformat(),
            "client_binding": binding.to_json(),
        },
        "queue": {
            "used": 0, "capacity": 5, "source": "QueueIndicatorReader/native_frame_roi",
            "profile_path": str(profile_path.resolve()),
            "profile_sha256": _sha(profile_bytes),
            "roi": list(profile.roi),
        },
    }


def write_startup_attestation(path: Path, workspace_root: Path, record: dict[str, Any]) -> Path:
    """Exclusive, durable output; never replace an earlier assertion."""
    destination = _within(path, workspace_root)
    if destination != canonical_startup_attestation_path(record.get("job_id"), workspace_root):
        raise StartupAttestationError("attestation output is not the canonical job path")
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with destination.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def validate_startup_attestation(
    path: Path, *, job_artifact: Path, manifest_path: Path, frame_path: Path,
    profile_path: Path, ledger_root: Path, workspace_root: Path,
    mission_flows: Path, ui_states: Path, resource_type: str,
    resource_level: int | None, now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> dict[str, Any]:
    """Recheck immutable sources and current revocation before a future consumer."""
    actual = _json(_within(path, workspace_root))
    if not isinstance(actual, dict) or actual.get("schema_version") != 1:
        raise StartupAttestationError("attestation schema is invalid")
    if _within(path, workspace_root) != canonical_startup_attestation_path(actual.get("job_id"), workspace_root):
        raise StartupAttestationError("attestation is outside its canonical job path")
    assertion = actual.get("operator_assertion")
    if not isinstance(assertion, dict) or assertion.get("meaning") != "operator_affirms_currently_open_character":
        raise StartupAttestationError("operator assertion is missing")
    affirmed_at = _instant(assertion.get("affirmed_at"))
    expected = build_startup_attestation(
        job_artifact=job_artifact, manifest_path=manifest_path, frame_path=frame_path,
        profile_path=profile_path, ledger_root=ledger_root, workspace_root=workspace_root,
        mission_flows=mission_flows, ui_states=ui_states, resource_type=resource_type,
        resource_level=resource_level, affirmative_character_id=assertion.get("character_id"),
        now=affirmed_at, max_age_seconds=max_age_seconds, require_unused_job=False,
    )
    if actual != expected:
        raise StartupAttestationError("attestation no longer matches source evidence")
    current = now if now is not None else datetime.now(timezone.utc)
    job = load_gather_job_authority(
        job_artifact,
        canonical_actions=compiled_gather_catalog(compile_mission(
            mission_flows, ui_states, "GATHER_RESOURCE",
            {"resource_type": resource_type, "resource_level": resource_level},
        )).actions,
        expected_catalog_digest=actual["catalog_digest"],
    )
    if (current.tzinfo is None or current.utcoffset() is None
            or not job.starts_at <= current < job.expires_at
            or JsonGatherJobStore(ledger_root).progress(job).revoked):
        raise StartupAttestationError("attestation job is expired or revoked")
    return actual
