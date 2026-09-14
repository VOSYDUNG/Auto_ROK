from harness.contracts import Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.policy_overlay import PolicyEvidenceObservationProvider
from harness.scene_graph import SceneGraph


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
