from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from harness.mission_runtime import AllowedAction


@dataclass(frozen=True)
class Transition:
    """One trained state/action edge.

    The graph is knowledge compiled from operator training. It is not generated
    by the local model at runtime. GPT-OSS may only choose among transitions
    exposed from the currently observed state.
    """

    from_state: str
    action_id: str
    expect_states: Sequence[str] = field(default_factory=tuple)
    expect_family: str | None = None
    requires_target: bool = False
    target_ids: Sequence[str] = field(default_factory=tuple)
    arguments: Mapping[str, object] = field(default_factory=dict)
    completion_edge: bool = False


@dataclass(frozen=True)
class TaskFlow:
    flow_id: str
    transitions: Sequence[Transition]
    completion_states: Sequence[str] = field(default_factory=tuple)
    completion_families: Sequence[str] = field(default_factory=tuple)

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        return tuple(edge for edge in self.transitions if edge.from_state == state)

    def allowed_actions(self, state: str) -> tuple[AllowedAction, ...]:
        """Compile current graph edges into the selector's action surface."""
        return tuple(
            AllowedAction(
                action_id=edge.action_id,
                requires_target=edge.requires_target,
                target_ids=edge.target_ids,
                argument_hints=edge.arguments,
            )
            for edge in self.outgoing(state)
        )

    def transition_for(self, state: str, action_id: str) -> Transition | None:
        matches = [
            edge
            for edge in self.outgoing(state)
            if edge.action_id == action_id
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous graph: {self.flow_id!r} has multiple {action_id!r} "
                f"edges from state {state!r}"
            )
        return matches[0]

    def accepts_observation(
        self,
        edge: Transition,
        observed_state: str,
        observed_family: str | None = None,
    ) -> bool:
        if observed_state in edge.expect_states:
            return True
        if edge.expect_family is not None and observed_family == edge.expect_family:
            return True
        return False

    def is_complete(self, state: str, family: str | None = None) -> bool:
        if state in self.completion_states:
            return True
        return family is not None and family in self.completion_families


class FlowRegistry:
    def __init__(self, flows: Sequence[TaskFlow]) -> None:
        self._flows = {flow.flow_id: flow for flow in flows}
        if len(self._flows) != len(flows):
            raise ValueError("duplicate flow_id in task graph registry")

    def require(self, flow_id: str) -> TaskFlow:
        try:
            return self._flows[flow_id]
        except KeyError as exc:
            raise KeyError(f"unknown task flow {flow_id!r}") from exc
