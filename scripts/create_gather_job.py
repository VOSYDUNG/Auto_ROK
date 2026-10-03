"""Create one offline, bounded FIRST DONE GATHER job artifact.

This command derives the action catalog from the canonical compiled mission.
It neither observes the game nor arms input or calls a model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_authority import GatherJobAuthority, compiled_gather_catalog, schedule_digest  # noqa: E402
from harness.gather_job_store import GatherJobStoreError, load_gather_job_authority  # noqa: E402
from harness.mission_loader import compile_mission  # noqa: E402
from autorok.mission.allocation import allocate_by_ratio  # noqa: E402


def build_artifact(
    *, job_id: str, task_id: str, character_id: str,
    resource_type: str | None = None, resource_level: int | None = None,
    starts_at: datetime, expires_at: datetime,
) -> dict[str, object]:
    resources = tuple(kind.value for kind in allocate_by_ratio(5)) if resource_type is None else (resource_type,)
    catalogs = tuple(compiled_gather_catalog(compile_mission(
        ROOT / "config" / "mission_flows.yaml",
        ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE",
        {"resource_type": resource, "resource_level": resource_level},
    )) for resource in resources)
    catalog = catalogs[0]
    job = GatherJobAuthority(
        job_id, task_id, character_id, catalog.digest, starts_at, expires_at,
        catalog.actions, schema_version=2 if resource_type is None else 1,
        resource_schedule=resources if resource_type is None else (),
        slot_catalog_digests=tuple(item.digest for item in catalogs) if resource_type is None else (),
        resource_level=resource_level if resource_type is None else None,
        schedule_digest=schedule_digest(resources, tuple(item.digest for item in catalogs), resource_level)
            if resource_type is None else None,
    )
    artifact = {
        "schema_version": job.schema_version,
        "job_id": job.job_id,
        "mission_id": job.mission_id,
        "task_id": job.task_id,
        "character_id": job.character_id,
        "catalog_digest": job.catalog_digest,
        "starts_at": job.starts_at.isoformat(),
        "expires_at": job.expires_at.isoformat(),
        "allowed_actions": sorted(job.allowed_actions),
        "max_marches": job.max_marches,
    }
    if job.schema_version == 2:
        artifact.update({
            "resource_schedule": list(job.resource_schedule),
            "slot_catalog_digests": list(job.slot_catalog_digests),
            "resource_level": job.resource_level,
            "schedule_digest": job.schedule_digest,
        })
    return artifact


def _artifact_payload(artifact: dict[str, object]) -> bytes:
    return (json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_artifact(path: Path, workspace_root: Path, artifact: dict[str, object]) -> Path:
    destination = path.resolve()
    if not destination.is_relative_to(workspace_root.resolve()):
        raise ValueError("GATHER job artifact must be under workspace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _artifact_payload(artifact)
    # Exclusive creation is the authorization event: never replace an older job.
    created = False
    try:
        with destination.open("xb") as handle:
            created = True
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def write_launch_spec(
    path: Path, workspace_root: Path, artifact_path: Path, *,
    resource_type: str | None = None, resource_level: int | None = None,
    artifact_payload: bytes | None = None,
) -> Path:
    """Record replayable launch parameters without granting extra authority."""
    destination = path.resolve()
    source = artifact_path.resolve()
    if (not destination.is_relative_to(workspace_root.resolve())
            or not source.is_relative_to(workspace_root.resolve())
            or destination == source):
        raise ValueError("GATHER launch spec and artifact must be distinct paths under workspace")
    raw = source.read_bytes() if artifact_payload is None else artifact_payload
    artifact = json.loads(raw)
    spec = {
        "schema_version": 1,
        "job_artifact": str(source),
        "job_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "job_id": artifact["job_id"],
        "task_id": artifact["task_id"],
        "character_id": artifact["character_id"],
        "catalog_digest": artifact["catalog_digest"],
        "resource_level": resource_level,
    }
    if artifact["schema_version"] == 2:
        if resource_type is not None or resource_level != artifact["resource_level"]:
            raise ValueError("mixed GATHER launch cannot override the authority schedule")
        spec.update({"schema_version": 2, "resource_schedule": artifact["resource_schedule"],
                     "schedule_digest": artifact["schedule_digest"]})
    else:
        spec["resource_type"] = resource_type
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(spec, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", choices=("FOOD", "WOOD", "STONE", "GOLD"),
                        help="legacy single-resource offline fixture; omit for default five-slot mix")
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--expires-at", required=True,
                        help="timezone-aware ISO 8601 timestamp; one five-march job expires then")
    parser.add_argument("--output", required=True, help="new JSON path under workspace")
    parser.add_argument("--launch-output", type=Path,
                        help="new non-authoritative launch JSON; defaults beside the job artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expires_at = datetime.fromisoformat(args.expires_at.replace("Z", "+00:00"))
        starts_at = datetime.now(timezone.utc)
        artifact = build_artifact(
            job_id=args.job_id, task_id=args.task_id, character_id=args.character_id,
            resource_type=args.resource_type, resource_level=args.resource_level,
            starts_at=starts_at, expires_at=expires_at,
        )
        compiled = compile_mission(
            ROOT / "config" / "mission_flows.yaml",
            ROOT / "config" / "ui_states.yaml",
            "GATHER_RESOURCE",
            {"resource_type": artifact.get("resource_schedule", [args.resource_type])[0],
             "resource_level": args.resource_level},
        )
        catalog = compiled_gather_catalog(compiled)
        destination = Path(args.output).resolve()
        launch_path = write_launch_spec(
            args.launch_output or destination.with_name(destination.stem + ".launch.json"),
            ROOT / "workspace", destination,
            resource_type=args.resource_type, resource_level=args.resource_level,
            artifact_payload=_artifact_payload(artifact),
        )
        created = False
        try:
            destination = write_artifact(destination, ROOT / "workspace", artifact)
            created = True
            load_gather_job_authority(
                destination, canonical_actions=catalog.actions,
                expected_catalog_digest=catalog.digest,
            )
        except (ValueError, OSError, GatherJobStoreError):
            if created:
                destination.unlink(missing_ok=True)
            launch_path.unlink(missing_ok=True)
            raise
        print(json.dumps({
            "status": "created_offline", "path": str(destination),
            "launch_path": str(launch_path),
            "job_id": artifact["job_id"], "character_id": artifact["character_id"],
            "task_id": artifact["task_id"], "max_marches": 5,
            "catalog_digest": artifact["catalog_digest"],
            "live_armed": False,
        }, ensure_ascii=False))
        return 0
    except (ValueError, OSError, GatherJobStoreError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
