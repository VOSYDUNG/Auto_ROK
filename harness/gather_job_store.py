"""Offline startup-job loader and durable five-slot GATHER dispatch ledger.

Call ``load_gather_job_authority`` with the compiled action catalog and its
digest. At the input boundary call ``reserve_dispatch`` once before an attempt
to emit March; an uncertain attempt keeps its slot reserved across restarts.
Reservations count attempts, not verified queue transitions. A leftover lock
after a crash requires operator recovery and fails closed without retrying.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
from typing import Any, Mapping

from harness.gather_job_authority import GatherJobAuthority, GatherJobAuthorityError, GatherJobProgress


class GatherJobStoreError(RuntimeError):
    """Malformed artifact, conflicting ledger, or denied dispatch."""


class GatherJobRevokedError(GatherJobStoreError):
    """A durable stop was observed at an input eligibility check."""


_JOB_FIELDS = frozenset({
    "schema_version", "job_id", "task_id", "character_id", "catalog_digest",
    "starts_at", "expires_at", "allowed_actions", "max_marches", "mission_id",
})


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GatherJobStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GatherJobStoreError(f"cannot read GATHER job JSON: {path}") from exc


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise GatherJobStoreError("job time must be an ISO-8601 string")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise GatherJobStoreError("invalid job time") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise GatherJobStoreError("job time must carry a timezone")
    return instant


def load_gather_job_authority(
    path: str | Path, *, canonical_actions: frozenset[str], expected_catalog_digest: str,
) -> GatherJobAuthority:
    """Load exact schema v1 JSON; reject actions outside the compiled catalog."""
    raw = _read_json(Path(path))
    if not isinstance(raw, dict) or frozenset(raw) != _JOB_FIELDS:
        raise GatherJobStoreError("startup job must contain exactly the schema v1 fields")
    actions = raw["allowed_actions"]
    if (not isinstance(actions, list) or not actions
            or any(not isinstance(item, str) or not item.strip() for item in actions)
            or len(set(actions)) != len(actions)):
        raise GatherJobStoreError("allowed_actions must be a unique nonempty string list")
    if (not isinstance(canonical_actions, frozenset)
            or not isinstance(expected_catalog_digest, str)
            or not expected_catalog_digest.strip()
            or raw["catalog_digest"] != expected_catalog_digest
            or not set(actions).issubset(canonical_actions)):
        raise GatherJobStoreError("job catalog scope does not match compiled GATHER catalog")
    if type(raw["schema_version"]) is not int or type(raw["max_marches"]) is not int:
        raise GatherJobStoreError("job schema version and march cap must be integers")
    try:
        return GatherJobAuthority(
            job_id=raw["job_id"], task_id=raw["task_id"],
            character_id=raw["character_id"], catalog_digest=raw["catalog_digest"],
            starts_at=_timestamp(raw["starts_at"]), expires_at=_timestamp(raw["expires_at"]),
            allowed_actions=frozenset(actions), max_marches=raw["max_marches"],
            mission_id=raw["mission_id"], schema_version=raw["schema_version"],
        )
    except GatherJobAuthorityError as exc:
        raise GatherJobStoreError(str(exc)) from exc


@dataclass(frozen=True)
class DispatchReservation:
    job_id: str
    run_id: str
    sequence: int
    frame_id: str
    action: str


@dataclass(frozen=True)
class GatherClientBinding:
    hwnd: int
    pid: int
    process_path: str

    @classmethod
    def from_window(cls, window: Any) -> "GatherClientBinding":
        if not isinstance(window, dict):
            raise GatherJobStoreError("GATHER client identity is missing")
        hwnd, pid, path = window.get("hwnd"), window.get("pid"), window.get("process_path")
        if (type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0
                or not isinstance(path, str) or not path.strip()
                or path != path.strip() or not ntpath.isabs(path)):
            raise GatherJobStoreError("GATHER client identity is invalid")
        return cls(hwnd, pid, ntpath.normcase(ntpath.normpath(path)))

    def to_json(self) -> dict[str, Any]:
        return {"hwnd": self.hwnd, "pid": self.pid, "process_path": self.process_path}


def _scope(job: GatherJobAuthority) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "task_id": job.task_id, "character_id": job.character_id,
        "catalog_digest": job.catalog_digest, "starts_at": job.starts_at.isoformat(),
        "expires_at": job.expires_at.isoformat(), "allowed_actions": sorted(job.allowed_actions),
        "max_marches": job.max_marches, "mission_id": job.mission_id,
        "schema_version": job.schema_version,
    }


class JsonGatherJobStore:
    """One immutable job scope plus append-only reservations per job.

    The lock is acquired once with exclusive creation. Contention or an
    uncertain crashed writer is denied, rather than retried or auto-recovered.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, job: GatherJobAuthority) -> Path:
        digest = hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()
        return self.root / f"gather-job-{digest}.json"

    def _load(self, job: GatherJobAuthority) -> dict[str, Any]:
        path = self._path(job)
        if not path.exists():
            return {"schema_version": 4, "scope": _scope(job),
                    "revoked": False, "client_binding": None,
                    "reservations": [], "verifications": []}
        raw = _read_json(path)
        if (not isinstance(raw, dict)
                or frozenset(raw) != {"schema_version", "scope", "revoked", "client_binding", "reservations", "verifications"}
                or type(raw["schema_version"]) is not int or raw["schema_version"] != 4
                or raw["scope"] != _scope(job)
                or type(raw["revoked"]) is not bool
                or not isinstance(raw["reservations"], list)
                or len(raw["reservations"]) > job.max_marches
                or not isinstance(raw["verifications"], list)
                or len(raw["verifications"]) > len(raw["reservations"])
                or len(raw["reservations"]) - len(raw["verifications"]) > 1):
            raise GatherJobStoreError("invalid or conflicting GATHER job ledger")
        binding = raw["client_binding"]
        if binding is not None:
            if (not isinstance(binding, dict)
                    or frozenset(binding) != {"hwnd", "pid", "process_path"}
                    or GatherClientBinding.from_window(binding).to_json() != binding):
                raise GatherJobStoreError("invalid GATHER client binding")
        if raw["reservations"] and binding is None:
            raise GatherJobStoreError("GATHER reservations require a client binding")
        seen_frames: set[str] = set()
        seen_runs: set[str] = set()
        for index, entry in enumerate(raw["reservations"], 1):
            if (not isinstance(entry, dict)
                    or frozenset(entry) != {"sequence", "run_id", "frame_id", "action", "reserved_at"}
                    or type(entry["sequence"]) is not int or entry["sequence"] != index
                    or not isinstance(entry["run_id"], str) or not entry["run_id"].strip()
                    or entry["run_id"] in seen_runs
                    or not isinstance(entry["frame_id"], str) or not entry["frame_id"].strip()
                    or entry["frame_id"] in seen_frames
                    or entry["action"] not in job.allowed_actions
                    or not isinstance(entry["reserved_at"], str)):
                raise GatherJobStoreError("invalid GATHER job reservation history")
            _timestamp(entry["reserved_at"])
            seen_runs.add(entry["run_id"])
            seen_frames.add(entry["frame_id"])
        self._validate_verifications(job, raw)
        return raw

    @staticmethod
    def _validate_verifications(job: GatherJobAuthority, raw: Mapping[str, Any]) -> None:
        seen_transition_frames: set[str] = set()
        previous_after_at: float | None = None
        for index, item in enumerate(raw["verifications"], 1):
            reservation = raw["reservations"][index - 1]
            required = {"sequence", "job_id", "run_id", "before_frame_id", "after_frame_id",
                        "baseline_frame_id", "before_count", "after_count", "capacity",
                        "before_source", "after_source", "character_id", "client_binding",
                        "before_observed_at", "after_observed_at", "verified_at", "receipt"}
            if not isinstance(item, dict) or frozenset(item) != required:
                raise GatherJobStoreError("invalid GATHER verification journal")
            receipt = item["receipt"]
            if (type(item["sequence"]) is not int or item["sequence"] != index
                    or item["job_id"] != job.job_id or item["run_id"] != reservation["run_id"]
                    or item["before_frame_id"] != reservation["frame_id"]
                    or not isinstance(item["after_frame_id"], str) or not item["after_frame_id"]
                    or item["before_frame_id"] in seen_transition_frames
                    or item["after_frame_id"] in seen_transition_frames
                    or not isinstance(item["baseline_frame_id"], str) or not item["baseline_frame_id"]
                    or item["baseline_frame_id"] == item["after_frame_id"]
                    or item["after_frame_id"] == item["before_frame_id"]
                    or type(item["before_count"]) is not int or item["before_count"] != index - 1
                    or type(item["after_count"]) is not int or item["after_count"] != index
                    or type(item["capacity"]) is not int or item["capacity"] != job.max_marches
                    or (index == 1 and item["before_source"] != "job_initial_slot_ordinal")
                    or (index > 1 and item["before_source"] not in {
                        "visible_ocr_queue_anchor", "visible_ocr_march_queue_region"
                    })
                    or item["after_source"] not in {"visible_ocr_queue_anchor", "visible_ocr_march_queue_region"}
                    or item["character_id"] != job.character_id
                    or item["client_binding"] != raw["client_binding"]
                    or not isinstance(receipt, dict)
                    or frozenset(receipt) != {"action_id", "target_id", "before_frame_id",
                                             "after_frame_id", "character_id", "non_interference_confirmed"}
                    or receipt["action_id"] != "MARCH_WITH_CURRENT_SELECTION"
                    or receipt["target_id"] != "TROOP_MARCH"
                    or receipt["before_frame_id"] != item["before_frame_id"]
                    or receipt["after_frame_id"] != item["after_frame_id"]
                    or receipt["character_id"] != job.character_id
                    or receipt["non_interference_confirmed"] is not True):
                raise GatherJobStoreError("invalid GATHER verification journal")
            before_at, after_at = item["before_observed_at"], item["after_observed_at"]
            if (not isinstance(before_at, (int, float)) or isinstance(before_at, bool)
                    or not isinstance(after_at, (int, float)) or isinstance(after_at, bool)
                    or not math.isfinite(before_at) or not math.isfinite(after_at)
                    or after_at <= before_at
                    or (previous_after_at is not None and before_at <= previous_after_at)):
                raise GatherJobStoreError("GATHER verification needs a fresh post-frame")
            _timestamp(item["verified_at"])
            seen_transition_frames.update((item["before_frame_id"], item["after_frame_id"]))
            previous_after_at = after_at

    def progress(self, job: GatherJobAuthority) -> GatherJobProgress:
        """Return separate reserved and verified march counts from the ledger."""
        if self._path(job).with_suffix(".lock").exists():
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required")
        raw = self._load(job)
        return GatherJobProgress(job.job_id, len(raw["reservations"]), raw["revoked"],
                                 len(raw["verifications"]))

    def verifications(self, job: GatherJobAuthority) -> tuple[dict[str, Any], ...]:
        if self._path(job).with_suffix(".lock").exists():
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required")
        return tuple(dict(item) for item in self._load(job)["verifications"])

    def record_verified(self, job: GatherJobAuthority, entry: Mapping[str, Any]) -> GatherJobProgress:
        """Append one proven n→n+1 transition for the pending reservation."""
        if not isinstance(entry, Mapping):
            raise GatherJobStoreError("GATHER verification entry is missing")
        return self._mutate(job, verification=dict(entry))

    def reservations(self, job: GatherJobAuthority) -> tuple[DispatchReservation, ...]:
        if self._path(job).with_suffix(".lock").exists():
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required")
        raw = self._load(job)
        return tuple(DispatchReservation(job.job_id, item["run_id"], item["sequence"],
                                         item["frame_id"], item["action"])
                     for item in raw["reservations"])

    def client_binding(self, job: GatherJobAuthority) -> GatherClientBinding | None:
        if self._path(job).with_suffix(".lock").exists():
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required")
        raw = self._load(job)
        value = raw["client_binding"]
        return None if value is None else GatherClientBinding.from_window(value)

    def bind_client(self, job: GatherJobAuthority, window: Any) -> GatherClientBinding:
        """Persist the first valid client; later observations must match exactly."""
        binding = GatherClientBinding.from_window(window)
        return self._mutate(job, binding=binding)

    def require_client(self, job: GatherJobAuthority, window: Any) -> GatherClientBinding:
        """Read-only check for an active job and its bound client at input."""
        observed = GatherClientBinding.from_window(window)
        if self._path(job).with_suffix(".lock").exists():
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required")
        raw = self._load(job)
        value = raw["client_binding"]
        if raw["revoked"]:
            raise GatherJobRevokedError("GATHER job revoked")
        if value is None:
            raise GatherJobStoreError("GATHER client binding missing")
        bound = GatherClientBinding.from_window(value)
        if observed != bound:
            raise GatherJobStoreError("GATHER client binding changed")
        return bound

    def reserve_dispatch(
        self, job: GatherJobAuthority, *, run_id: str, frame_id: str, action: str,
        now: datetime | None = None,
    ) -> DispatchReservation:
        """Atomically consume the next slot before an input attempt."""
        instant = now if now is not None else datetime.now(timezone.utc)
        if (not isinstance(run_id, str) or not run_id.strip()
                or not isinstance(frame_id, str) or not frame_id.strip()
                or action != "MARCH_WITH_CURRENT_SELECTION"
                or action not in job.allowed_actions
                or not isinstance(instant, datetime) or instant.tzinfo is None
                or instant.utcoffset() is None
                or not job.starts_at <= instant < job.expires_at):
            raise GatherJobStoreError("dispatch is outside the GATHER job scope")
        return self._mutate(job, run_id=run_id, frame_id=frame_id, action=action, instant=instant)

    def revoke(self, job: GatherJobAuthority) -> GatherJobProgress:
        """Persist a permanent stop without discarding reservation history."""
        return self._mutate(job, revoke=True)

    def _mutate(
        self, job: GatherJobAuthority, *, run_id: str | None = None,
        frame_id: str | None = None, action: str | None = None,
        instant: datetime | None = None, revoke: bool = False,
        binding: GatherClientBinding | None = None,
        verification: dict[str, Any] | None = None,
    ) -> DispatchReservation | GatherJobProgress | GatherClientBinding:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(job)
        lock = path.with_suffix(".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise GatherJobStoreError("GATHER job ledger is locked; recovery required") from exc
        try:
            os.close(fd)
            raw = self._load(job)
            if binding is not None:
                existing = raw["client_binding"]
                if raw["revoked"] or (existing is not None and existing != binding.to_json()):
                    raise GatherJobStoreError("GATHER client binding changed or job revoked")
                raw["client_binding"] = binding.to_json()
                result: DispatchReservation | GatherJobProgress | GatherClientBinding = binding
            elif revoke:
                if raw["revoked"]:
                    raise GatherJobStoreError("GATHER job already revoked")
                raw["revoked"] = True
                result: DispatchReservation | GatherJobProgress = GatherJobProgress(
                    job.job_id, len(raw["reservations"]), True, len(raw["verifications"]))
            elif verification is not None:
                if raw["revoked"]:
                    raise GatherJobStoreError("no active pending GATHER reservation to verify")
                sequence = verification.get("sequence")
                if type(sequence) is int and 1 <= sequence <= len(raw["verifications"]):
                    existing = raw["verifications"][sequence - 1]
                    proof_fields = frozenset(existing) - {"verified_at"}
                    if (frozenset(verification) == frozenset(existing)
                            and all(verification[key] == existing[key] for key in proof_fields)):
                        return GatherJobProgress(job.job_id, len(raw["reservations"]), False,
                                                 len(raw["verifications"]))
                    raise GatherJobStoreError("GATHER verification replay differs from journal")
                if len(raw["verifications"]) >= len(raw["reservations"]):
                    raise GatherJobStoreError("no active pending GATHER reservation to verify")
                raw["verifications"].append(verification)
                self._validate_verifications(job, raw)
                result = GatherJobProgress(job.job_id, len(raw["reservations"]), False,
                                           len(raw["verifications"]))
            else:
                assert run_id is not None and frame_id is not None and action is not None and instant is not None
                if (raw["revoked"] or raw["client_binding"] is None
                        or len(raw["reservations"]) != len(raw["verifications"])
                        or len(raw["reservations"]) >= job.max_marches
                        or any(item["run_id"] == run_id or item["frame_id"] == frame_id
                               for item in raw["reservations"])):
                    raise GatherJobStoreError("duplicate, full, or revoked GATHER job")
                sequence = len(raw["reservations"]) + 1
                raw["reservations"].append({"sequence": sequence, "run_id": run_id,
                                            "frame_id": frame_id, "action": action,
                                            "reserved_at": instant.isoformat()})
                result = DispatchReservation(job.job_id, run_id, sequence, frame_id, action)
            temp = path.with_name(path.name + f".{os.getpid()}.tmp")
            try:
                with temp.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(raw, handle, ensure_ascii=False, sort_keys=True, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            return result
        finally:
            lock.unlink(missing_ok=True)
