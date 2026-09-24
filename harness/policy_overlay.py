"""Explicit operator policy evidence overlays for compiled mission preconditions."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable, Mapping

from harness.gather_job_authority import GatherJobAuthority, GatherJobProgress
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider
from harness.troop_policy import TROOP_SELECTION_PRECONDITION


class PolicyEvidenceObservationProvider:
    """Attach only explicitly approved precondition evidence to scene facts.

    This adapter never infers gameplay policy. Callers must provide the exact
    compiled precondition strings they approve for this mission occurrence.
    """

    def __init__(
        self,
        inner: ObservationProvider,
        approvals: Mapping[str, bool] | None = None,
        *,
        gather_job: GatherJobAuthority | None = None,
        job_progress: Callable[[], GatherJobProgress] | None = None,
        catalog_digest: str | None = None,
        canonical_actions: frozenset[str] | None = None,
        max_frame_age_seconds: float | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if gather_job is not None and approvals:
            raise ValueError("legacy B003 approvals and a GATHER job cannot be combined")
        if gather_job is not None and (
            job_progress is None or not catalog_digest or canonical_actions is None
            or max_frame_age_seconds is None
        ):
            raise ValueError("GATHER job needs progress, catalog and frame-age bound")
        self.inner = inner
        self.approvals = {
            key: value
            for key, value in dict(approvals or {}).items()
            if isinstance(key, str) and key and value is True
        }
        self.gather_job = gather_job
        self.job_progress = job_progress
        self.catalog_digest = catalog_digest
        self.canonical_actions = canonical_actions
        self.max_frame_age_seconds = max_frame_age_seconds
        self.clock = clock

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        approvals = self.approvals
        if self.gather_job is not None:
            if bundle.observation.frame_id != bundle.scene.frame_id:
                raise ValueError("GATHER job observation and scene must share one frame")
            existing = bundle.scene.facts.get("precondition_evidence")
            if isinstance(existing, Mapping) and TROOP_SELECTION_PRECONDITION in existing:
                raise ValueError("GATHER job cannot reuse upstream troop approval")
            approvals = self.gather_job.march_precondition(
                context,
                current_character_id=bundle.scene.facts.get("character_id"),
                current_catalog_digest=self.catalog_digest,
                canonical_actions=self.canonical_actions,  # type: ignore[arg-type]
                frame_id=bundle.scene.frame_id,
                frame_timestamp=bundle.observation.timestamp,
                max_frame_age_seconds=self.max_frame_age_seconds,
                target_ids=frozenset(
                    target.target_id for target in bundle.scene.targets
                    if target.frame_id == bundle.scene.frame_id
                ),
                progress=self.job_progress(),  # type: ignore[misc]
                now=self.clock() if self.clock is not None else None,
            )
        if not approvals:
            return bundle
        facts = dict(bundle.scene.facts)
        existing = facts.get("precondition_evidence")
        evidence = dict(existing) if isinstance(existing, Mapping) else {}
        evidence.update(approvals)
        facts["precondition_evidence"] = evidence
        facts["precondition_evidence_source"] = (
            "bounded_gather_job" if self.gather_job is not None
            else "explicit_operator_configuration"
        )
        if self.gather_job is not None:
            facts["gather_job_id"] = self.gather_job.job_id
        return ObservationBundle(
            bundle.observation,
            replace(bundle.scene, facts=facts),
        )
