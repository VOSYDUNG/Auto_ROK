"""Explicit operator policy evidence overlays for compiled mission preconditions."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider


class PolicyEvidenceObservationProvider:
    """Attach only explicitly approved precondition evidence to scene facts.

    This adapter never infers gameplay policy. Callers must provide the exact
    compiled precondition strings they approve for this mission occurrence.
    """

    def __init__(
        self,
        inner: ObservationProvider,
        approvals: Mapping[str, bool] | None = None,
    ) -> None:
        self.inner = inner
        self.approvals = {
            key: value
            for key, value in dict(approvals or {}).items()
            if isinstance(key, str) and key and value is True
        }

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        if not self.approvals:
            return bundle
        facts = dict(bundle.scene.facts)
        existing = facts.get("precondition_evidence")
        evidence = dict(existing) if isinstance(existing, Mapping) else {}
        evidence.update(self.approvals)
        facts["precondition_evidence"] = evidence
        facts["precondition_evidence_source"] = "explicit_operator_configuration"
        return ObservationBundle(
            bundle.observation,
            replace(bundle.scene, facts=facts),
        )
