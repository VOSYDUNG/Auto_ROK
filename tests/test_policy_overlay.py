from datetime import datetime, timedelta, timezone

import pytest

from harness.contracts import BoundingBox
from harness.gather_job_authority import GatherJobAuthority, GatherJobProgress
from harness.contracts import Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.policy_overlay import PolicyEvidenceObservationProvider
from harness.scene_graph import SceneGraph, VisualTarget


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-policy")
RULE = "troop/commander selection policy is valid for this mission"


class One:
    def observe(self, context):
        return ObservationBundle(
            Observation(1.0, "f1", (1280, 720)),
            SceneGraph("f1", None, facts={"existing": True}),
        )


def test_only_explicit_true_approvals_are_injected():
    result = PolicyEvidenceObservationProvider(
        One(),
        {RULE: True, "not-approved": False},
    ).observe(CONTEXT)
    assert result.scene.facts["precondition_evidence"] == {RULE: True}
    assert result.scene.facts["precondition_evidence_source"] == "explicit_operator_configuration"


def test_empty_policy_overlay_does_not_invent_evidence():
    result = PolicyEvidenceObservationProvider(One(), {}).observe(CONTEXT)
    assert "precondition_evidence" not in result.scene.facts


NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)


class NewTroop:
    def __init__(self, *, stale=False):
        self.stale = stale

    def observe(self, context):
        timestamp = NOW.timestamp() - (60 if self.stale else 1)
        return ObservationBundle(
            Observation(timestamp, "new-troop-frame", (1366, 768)),
            SceneGraph(
                "new-troop-frame",
                "NEW_TROOP_SETUP",
                targets=(VisualTarget(
                    "TROOP_MARCH", "new-troop-frame", "MARCH",
                    BoundingBox(800, 560, 980, 610), 1.0, "ocr",
                ),),
                facts={"character_id": "character-1"},
            ),
        )


def _job():
    return GatherJobAuthority(
        job_id="job-1",
        task_id=CONTEXT.task_id,
        character_id="character-1",
        catalog_digest="catalog-1",
        starts_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        allowed_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
    )


def test_bounded_job_supplies_march_precondition_without_legacy_approval():
    progress = GatherJobProgress("job-1", 3, verified_marches=3)
    result = PolicyEvidenceObservationProvider(
        NewTroop(),
        gather_job=_job(),
        job_progress=lambda: progress,
        catalog_digest="catalog-1",
        canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
        max_frame_age_seconds=10,
        clock=lambda: NOW,
    ).observe(CONTEXT)
    assert result.scene.facts["precondition_evidence"] == {RULE: True}
    assert result.scene.facts["precondition_evidence_source"] == "bounded_gather_job"
    assert result.scene.facts["gather_job_id"] == "job-1"


def test_bounded_job_does_not_approve_a_stale_new_troop_frame():
    result = PolicyEvidenceObservationProvider(
        NewTroop(stale=True),
        gather_job=_job(),
        job_progress=lambda: GatherJobProgress("job-1", 0),
        catalog_digest="catalog-1",
        canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
        max_frame_age_seconds=10,
        clock=lambda: NOW,
    ).observe(CONTEXT)
    assert "precondition_evidence" not in result.scene.facts


def test_bounded_job_cannot_mix_with_b003_approval_or_missing_progress():
    with pytest.raises(ValueError):
        PolicyEvidenceObservationProvider(
            NewTroop(), {RULE: True}, gather_job=_job(),
            job_progress=lambda: GatherJobProgress("job-1", 0),
            catalog_digest="catalog-1",
            canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
            max_frame_age_seconds=10,
        )
    with pytest.raises(ValueError):
        PolicyEvidenceObservationProvider(
            NewTroop(), gather_job=_job(),
            catalog_digest="catalog-1",
            canonical_actions=frozenset({"MARCH_WITH_CURRENT_SELECTION"}),
            max_frame_age_seconds=10,
        )
