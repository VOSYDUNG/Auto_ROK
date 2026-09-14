"""Atomic durable checkpoints for bounded mission occurrences."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness.mission_runtime import MissionContext


class CheckpointStatus(str, Enum):
    RUNNING = "running"
    WAITING = "waiting"
    REOBSERVE = "reobserve"
    NEEDS_DECISION = "needs_decision"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETE = "complete"


class CheckpointConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionCheckpoint:
    mission_id: str
    task_id: str
    run_id: str
    attempt: int
    parameters: Mapping[str, Any] = field(default_factory=dict)
    status: CheckpointStatus = CheckpointStatus.RUNNING
    revision: int = 0
    last_frame_id: str | None = None
    last_state: str | None = None
    last_decision: str | None = None
    last_reason: str | None = None
    verified_self_loops: Sequence[tuple[str, str, str]] = field(default_factory=tuple)
    updated_at: str | None = None

    def matches(self, context: MissionContext) -> bool:
        return (
            self.mission_id == context.mission_id
            and self.task_id == context.task_id
            and self.run_id == context.run_id
        )


class JsonMissionStore:
    """One JSON file per run with compare-and-swap revisions and atomic replace."""

    schema_version = 1

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load(self, context: MissionContext) -> MissionCheckpoint | None:
        path = self._path(context)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read mission checkpoint {path}: {exc}") from exc
        if raw.get("schema_version") != self.schema_version:
            raise RuntimeError(f"unsupported mission checkpoint schema in {path}")
        payload = raw.get("checkpoint")
        if not isinstance(payload, dict):
            raise RuntimeError(f"malformed mission checkpoint {path}")
        checkpoint = self._decode(payload)
        if not checkpoint.matches(context):
            raise RuntimeError(f"checkpoint identity mismatch in {path}")
        return checkpoint

    def save(
        self,
        checkpoint: MissionCheckpoint,
        *,
        expected_revision: int | None = None,
    ) -> MissionCheckpoint:
        context = MissionContext(
            checkpoint.mission_id,
            checkpoint.task_id,
            checkpoint.run_id,
            checkpoint.attempt,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        current = self.load(context)
        current_revision = current.revision if current is not None else 0
        if expected_revision is not None and current_revision != expected_revision:
            raise CheckpointConflict(
                f"checkpoint revision changed: expected {expected_revision}, found {current_revision}"
            )

        saved = replace(
            checkpoint,
            revision=current_revision + 1,
            updated_at=datetime.now(timezone.utc).isoformat(),
            verified_self_loops=tuple(tuple(item) for item in checkpoint.verified_self_loops),
        )
        payload = {
            "schema_version": self.schema_version,
            "checkpoint": self._encode(saved),
        }
        path = self._path(context)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return saved

    def _path(self, context: MissionContext) -> Path:
        identity = "\0".join((context.mission_id, context.task_id, context.run_id))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return self.root / f"{context.mission_id.lower()}-{digest}.json"

    @staticmethod
    def _encode(checkpoint: MissionCheckpoint) -> dict[str, Any]:
        result = asdict(checkpoint)
        result["status"] = checkpoint.status.value
        result["verified_self_loops"] = [list(item) for item in checkpoint.verified_self_loops]
        return result

    @staticmethod
    def _decode(payload: Mapping[str, Any]) -> MissionCheckpoint:
        loops_raw = payload.get("verified_self_loops", ())
        if not isinstance(loops_raw, list):
            raise RuntimeError("verified_self_loops must be a list")
        loops: list[tuple[str, str, str]] = []
        for item in loops_raw:
            if not isinstance(item, list) or len(item) != 3 or not all(isinstance(x, str) for x in item):
                raise RuntimeError("invalid verified self-loop checkpoint entry")
            loops.append((item[0], item[1], item[2]))
        try:
            status = CheckpointStatus(payload.get("status", CheckpointStatus.RUNNING.value))
            return MissionCheckpoint(
                mission_id=str(payload["mission_id"]),
                task_id=str(payload["task_id"]),
                run_id=str(payload["run_id"]),
                attempt=int(payload.get("attempt", 0)),
                parameters=dict(payload.get("parameters", {})),
                status=status,
                revision=int(payload.get("revision", 0)),
                last_frame_id=payload.get("last_frame_id"),
                last_state=payload.get("last_state"),
                last_decision=payload.get("last_decision"),
                last_reason=payload.get("last_reason"),
                verified_self_loops=tuple(loops),
                updated_at=payload.get("updated_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("malformed mission checkpoint payload") from exc
