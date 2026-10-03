"""Offline policy contract for one operator-delegated five-march GATHER job.

This object supplies only the compiled troop-selection precondition. It is not
an input guard, a quota ledger, or a live-arm token. The canonical CLI must not
consume it until those downstream boundaries are wired and tested.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping

from harness.mission_loader import CompiledMission, compile_mission
from harness.mission_runtime import MissionContext
from harness.troop_policy import TROOP_SELECTION_PRECONDITION


class GatherJobAuthorityError(ValueError):
    """The proposed startup authorization is malformed."""


def schedule_digest(resources: tuple[str, ...], catalogs: tuple[str, ...],
                    level: int | None) -> str:
    payload = {"resources": resources, "catalogs": catalogs, "resource_level": level}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_schedule_catalog(job: "GatherJobAuthority", mission_flows: object,
                              ui_states: object) -> None:
    """Recompile every pinned slot before trusting a mixed job."""
    if job.schema_version != 2:
        return
    for resource, digest in zip(job.resource_schedule, job.slot_catalog_digests):
        compiled = compile_mission(mission_flows, ui_states, job.mission_id,
                                   {"resource_type": resource, "resource_level": job.resource_level})
        if compiled_gather_catalog(compiled).digest != digest:
            raise GatherJobAuthorityError("GATHER schedule catalog differs from compiled mission")


@dataclass(frozen=True)
class GatherCatalogIdentity:
    """Identity and action universe derived from the actual compiled flow."""

    digest: str
    actions: frozenset[str]


def compiled_gather_catalog(compiled: CompiledMission) -> GatherCatalogIdentity:
    """Bind a startup job to the exact compiled GATHER flow and parameters.

    The digest excludes the checkout path so equivalent source in another
    workspace yields the same identity. It includes every compiled transition,
    completion rule and precondition that can change input eligibility.
    """
    if compiled.flow.flow_id != "GATHER_RESOURCE":
        raise GatherJobAuthorityError("job catalog must be compiled GATHER_RESOURCE")
    actions = frozenset(edge.action_id for edge in compiled.flow.transitions)
    if (not actions or any(not isinstance(action, str) or not action for action in actions)
            or "MARCH_WITH_CURRENT_SELECTION" not in actions):
        raise GatherJobAuthorityError("compiled GATHER catalog has no march action")
    payload = {
        "flow": asdict(compiled.flow),
        "parameters": dict(compiled.parameters),
        "completion": asdict(compiled.completion) if compiled.completion is not None else None,
        "transition_preconditions": {
            key: list(value) for key, value in sorted(compiled.transition_preconditions.items())
        },
    }
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatherJobAuthorityError("compiled GATHER catalog is not serializable") from exc
    return GatherCatalogIdentity(hashlib.sha256(encoded).hexdigest(), actions)


@dataclass(frozen=True)
class GatherJobProgress:
    """Checkpoint-derived progress, supplied afresh by the future job store."""

    job_id: str
    dispatched_marches: int
    revoked: bool = False
    verified_marches: int = 0

    def __post_init__(self) -> None:
        if (not isinstance(self.job_id, str) or not self.job_id.strip()
                or type(self.dispatched_marches) is not int
                or self.dispatched_marches < 0
                or type(self.revoked) is not bool
                or type(self.verified_marches) is not int
                or not 0 <= self.verified_marches <= self.dispatched_marches):
            raise GatherJobAuthorityError("invalid checkpoint-derived job progress")


@dataclass(frozen=True)
class GatherJobAuthority:
    job_id: str
    task_id: str
    character_id: str
    catalog_digest: str
    starts_at: datetime
    expires_at: datetime
    allowed_actions: frozenset[str]
    max_marches: int = 5
    mission_id: str = "GATHER_RESOURCE"
    schema_version: int = 1
    resource_schedule: tuple[str, ...] = ()
    slot_catalog_digests: tuple[str, ...] = ()
    resource_level: int | None = None
    schedule_digest: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in (1, 2) or self.mission_id != "GATHER_RESOURCE":
            raise GatherJobAuthorityError("unsupported GATHER job schema or mission")
        for name in ("job_id", "task_id", "character_id", "catalog_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GatherJobAuthorityError(f"{name} must be non-empty")
        if (not isinstance(self.starts_at, datetime)
                or not isinstance(self.expires_at, datetime)
                or self.starts_at.tzinfo is None
                or self.expires_at.tzinfo is None
                or self.starts_at.utcoffset() is None
                or self.expires_at.utcoffset() is None
                or self.starts_at >= self.expires_at):
            raise GatherJobAuthorityError("job time window must be aware and increasing")
        if type(self.max_marches) is not int or self.max_marches != 5:
            raise GatherJobAuthorityError("FIRST DONE job must allow exactly five marches")
        if (not isinstance(self.allowed_actions, frozenset)
                or not self.allowed_actions
                or any(not isinstance(action, str) or not action.strip()
                       for action in self.allowed_actions)
                or "MARCH_WITH_CURRENT_SELECTION" not in self.allowed_actions):
            raise GatherJobAuthorityError("allowed_actions must include the GATHER march")
        if self.schema_version == 2:
            from autorok.mission.allocation import allocate_by_ratio
            expected = tuple(kind.value for kind in allocate_by_ratio(5))
            if (self.resource_schedule != expected
                    or len(self.slot_catalog_digests) != 5
                    or any(not isinstance(item, str) or not item for item in self.slot_catalog_digests)
                    or self.catalog_digest != self.slot_catalog_digests[0]
                    or (self.resource_level is not None and type(self.resource_level) is not int)
                    or self.schedule_digest != schedule_digest(
                        self.resource_schedule, self.slot_catalog_digests, self.resource_level)):
                raise GatherJobAuthorityError("invalid immutable five-slot GATHER schedule")

    def resource_for_slot(self, sequence: int) -> str:
        if self.schema_version != 2 or type(sequence) is not int or not 1 <= sequence <= 5:
            raise GatherJobAuthorityError("job has no mixed-resource slot")
        return self.resource_schedule[sequence - 1]

    def catalog_for_slot(self, sequence: int) -> str:
        if self.schema_version != 2 or type(sequence) is not int or not 1 <= sequence <= 5:
            raise GatherJobAuthorityError("job has no mixed-resource slot")
        return self.slot_catalog_digests[sequence - 1]

    def march_precondition(
        self,
        context: MissionContext,
        *,
        current_character_id: object,
        current_catalog_digest: object,
        canonical_actions: frozenset[str],
        frame_id: object,
        frame_timestamp: object,
        max_frame_age_seconds: object,
        target_ids: frozenset[str],
        progress: GatherJobProgress,
        now: datetime | None = None,
    ) -> Mapping[str, bool]:
        """Return evidence only for an active job and current March target.

        The game auto-fills the current commander pair. The harness never chooses
        or edits commanders here; their names and internal ranking are not gates.
        The mission state classifier separately restricts March to New Troop.
        """
        instant = now if now is not None else datetime.now(timezone.utc)
        if (not isinstance(instant, datetime) or instant.tzinfo is None
                or instant.utcoffset() is None):
            return {}
        if (not isinstance(frame_timestamp, (int, float))
                or isinstance(frame_timestamp, bool)
                or not math.isfinite(frame_timestamp)
                or not isinstance(max_frame_age_seconds, (int, float))
                or isinstance(max_frame_age_seconds, bool)
                or not math.isfinite(max_frame_age_seconds)
                or max_frame_age_seconds <= 0
                or not 0 <= instant.timestamp() - frame_timestamp <= max_frame_age_seconds):
            return {}
        if (context.mission_id != self.mission_id or context.task_id != self.task_id
                or current_character_id != self.character_id
                or current_catalog_digest != (self.catalog_for_slot(progress.verified_marches + 1)
                    if self.schema_version == 2 and progress.verified_marches < 5 else self.catalog_digest)
                or not self.allowed_actions.issubset(canonical_actions)
                or progress.job_id != self.job_id or progress.revoked
                or type(progress.dispatched_marches) is not int
                or not 0 <= progress.dispatched_marches < self.max_marches
                or progress.verified_marches != progress.dispatched_marches
                or not self.starts_at <= instant < self.expires_at
                or not isinstance(frame_id, str) or not frame_id
                or "TROOP_MARCH" not in target_ids):
            return {}
        return {TROOP_SELECTION_PRECONDITION: True}
