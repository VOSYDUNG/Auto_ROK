"""Adapters between classifier output, graph state, and the runtime snapshot."""
from __future__ import annotations

from numbers import Real
from typing import Any

from harness.contracts import GameState
from harness.mission_runtime import MissionContext, ToolSnapshot
from harness.scene_graph import SceneGraph
from harness.state_classifier import AMBIGUOUS_STATE, UNKNOWN_STATE, StateClassification
from harness.task_graph import TaskFlow


def _confidence(classification: StateClassification) -> float:
    """Use only an explicitly supplied, bounded confidence value."""
    value = classification.ambiguity.get("confidence")
    if isinstance(value, Real) and not isinstance(value, bool) and 0.0 <= value <= 1.0:
        return float(value)
    return 0.0


def to_game_state(classification: StateClassification) -> GameState:
    """Convert a classification without upgrading deterministic evidence."""
    return GameState(
        name=classification.state_id,
        confidence=_confidence(classification),
        evidence=tuple(classification.matching_evidence),
        attributes={"ambiguity": dict(classification.ambiguity)},
    )


def to_tool_snapshot(
    context: MissionContext,
    classification: StateClassification,
    scene: SceneGraph,
    flow: TaskFlow,
) -> ToolSnapshot:
    """Build a frame-bound runtime surface from a compiled task flow.

    Unknown and ambiguous classifications deliberately expose no actions.
    Evidence and visual targets must belong to the same current frame.
    """
    if not isinstance(scene, SceneGraph):
        raise TypeError("scene must be a SceneGraph")
    for evidence in classification.matching_evidence:
        if evidence.metadata.get("frame_id") != scene.frame_id:
            raise ValueError("classification evidence is not bound to the scene frame")
    for target in scene.targets:
        if target.frame_id != scene.frame_id:
            raise ValueError("scene contains a target from a different frame")

    known = classification.state_id not in {UNKNOWN_STATE, AMBIGUOUS_STATE}
    allowed = flow.allowed_actions(classification.state_id) if known else ()
    grounded = tuple(dict.fromkeys(target.target_id for target in scene.targets))
    return ToolSnapshot(
        mission_id=context.mission_id,
        task_id=context.task_id,
        frame_id=scene.frame_id,
        state=classification.state_id,
        facts=dict(scene.facts),
        allowed_actions=allowed,
        target_ids=grounded,
        last_feedback={},
    )
