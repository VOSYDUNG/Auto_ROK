"""Deterministic bounded action selection for compiled mission flows."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot
from harness.task_graph import TaskFlow, Transition


class SelectionDecision(str, Enum):
    AUTO = "auto"
    REOBSERVE = "reobserve"
    NEEDS_DECISION = "needs_decision"
    WAIT = "wait"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SelectionResult:
    decision: SelectionDecision
    choice: ActionChoice | None = None
    candidates: Sequence[ActionChoice] = field(default_factory=tuple)
    reason: str | None = None


class DeterministicMissionSelector:
    """Select the next action without a model whenever the graph is unambiguous.

    Ordered self-loops are treated as procedural setup steps. A verified
    self-loop is skipped on later ticks of the same run. After setup steps are
    exhausted, only the advancing edge(s) remain. If more than one meaningful
    choice is still possible, the selector returns NEEDS_DECISION rather than
    guessing.
    """

    def select(
        self,
        context: MissionContext,
        snapshot: ToolSnapshot,
        flow: TaskFlow,
        *,
        verified_self_loops: Sequence[tuple[str, str, str]] = (),
    ) -> SelectionResult:
        if snapshot.state in {"UNKNOWN_STATE", "AMBIGUOUS_STATE"}:
            return SelectionResult(
                SelectionDecision.REOBSERVE,
                reason="current state is not deterministically actionable",
            )

        outgoing = flow.outgoing(snapshot.state)
        if not outgoing:
            if flow.is_complete(snapshot.state):
                return SelectionResult(SelectionDecision.WAIT, reason="flow is already in a terminal state")
            return SelectionResult(
                SelectionDecision.BLOCKED,
                reason="compiled flow has no outgoing transition for the current state",
            )

        surface = {item.action_id: item for item in snapshot.allowed_actions}
        if not surface:
            return SelectionResult(
                SelectionDecision.REOBSERVE,
                reason="current tool surface exposes no actions",
            )

        verified = set(verified_self_loops)
        setup_edges = [
            edge
            for edge in outgoing
            if snapshot.state in edge.expect_states
            and (context.run_id, snapshot.state, edge.action_id) not in verified
        ]

        # Self-loop setup transitions are procedural and ordered in the compiled
        # flow. Execute only the next unverified setup edge.
        if setup_edges:
            edges = (setup_edges[0],)
        else:
            edges = tuple(edge for edge in outgoing if snapshot.state not in edge.expect_states)

        if not edges:
            return SelectionResult(
                SelectionDecision.REOBSERVE,
                reason="all setup transitions for this state were already verified",
            )

        candidates: list[ActionChoice] = []
        missing_grounding = False
        for edge in edges:
            if edge.action_id not in surface:
                missing_grounding = True
                continue
            edge_choices = self._choices_for_edge(edge, snapshot)
            if not edge_choices:
                missing_grounding = True
                continue
            candidates.extend(edge_choices)

        unique_items: list[ActionChoice] = []
        for candidate in candidates:
            if candidate not in unique_items:
                unique_items.append(candidate)
        unique = tuple(unique_items)
        if len(unique) == 1:
            return SelectionResult(
                SelectionDecision.AUTO,
                choice=unique[0],
                candidates=unique,
                reason="exactly one bounded action is eligible",
            )
        if len(unique) > 1:
            return SelectionResult(
                SelectionDecision.NEEDS_DECISION,
                candidates=unique,
                reason="multiple meaningful bounded choices remain",
            )
        if missing_grounding:
            return SelectionResult(
                SelectionDecision.REOBSERVE,
                reason="declared action or target is not grounded in the current frame",
            )
        return SelectionResult(SelectionDecision.BLOCKED, reason="no eligible compiled action remains")

    @staticmethod
    def _choices_for_edge(edge: Transition, snapshot: ToolSnapshot) -> tuple[ActionChoice, ...]:
        if not edge.requires_target:
            return (ActionChoice(edge.action_id, arguments=edge.arguments),)

        grounded = tuple(target for target in edge.target_ids if target in snapshot.target_ids)
        return tuple(
            ActionChoice(edge.action_id, target, edge.arguments)
            for target in grounded
        )
