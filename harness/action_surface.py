from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from harness.scene_graph import SceneGraph


class InputKind(str, Enum):
    HOTKEY = "hotkey"
    CLICK_TARGET = "click_target"


@dataclass(frozen=True)
class ShortcutBinding:
    """Native game shortcut bound to one semantic action."""

    action_id: str
    key: str


@dataclass(frozen=True)
class ActionRequest:
    """Semantic request produced by MissionRuntime / GPT-OSS.

    The request intentionally contains no screen coordinates. Typed bounded
    arguments may be carried when the compiled transition declares them.
    """

    action_id: str
    target_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedInput:
    action_id: str
    kind: InputKind
    frame_id: str | None = None
    key: str | None = None
    target_id: str | None = None
    point: tuple[int, int] | None = None
    source: str = "unknown"


class ActionResolutionError(RuntimeError):
    pass


class SemanticActionSurface:
    """Resolve symbolic actions into concrete OS input."""

    def __init__(
        self,
        shortcuts: Mapping[str, str] | None = None,
        *,
        min_target_confidence: float = 0.90,
        allow_unscored_exact_targets: bool = False,
    ) -> None:
        self.shortcuts = dict(shortcuts or {})
        self.min_target_confidence = min_target_confidence
        self.allow_unscored_exact_targets = allow_unscored_exact_targets

    def resolve(
        self,
        request: ActionRequest,
        *,
        scene: SceneGraph | None = None,
    ) -> ResolvedInput:
        key = self.shortcuts.get(request.action_id)
        if key is not None:
            return ResolvedInput(
                action_id=request.action_id,
                kind=InputKind.HOTKEY,
                key=key,
                source="native_shortcut",
            )

        if request.target_id is None:
            raise ActionResolutionError(
                f"action {request.action_id!r} has no native shortcut and no target"
            )
        if scene is None:
            raise ActionResolutionError(
                f"action {request.action_id!r} requires a current scene graph"
            )

        target = scene.target(
            request.target_id,
            min_confidence=self.min_target_confidence,
            allow_unscored_exact=self.allow_unscored_exact_targets,
        )
        if target is None:
            raise LookupError(
                f"target {request.target_id!r} is not grounded for the current action surface"
            )
        if not scene.is_current(target):
            raise ActionResolutionError(
                f"target {request.target_id!r} is stale for frame {scene.frame_id!r}"
            )

        return ResolvedInput(
            action_id=request.action_id,
            kind=InputKind.CLICK_TARGET,
            frame_id=scene.frame_id,
            target_id=target.target_id,
            point=target.click_point,
            source=target.source,
        )


TRAINED_NATIVE_SHORTCUTS: Mapping[str, str] = {
    "TOGGLE_CHAT_WINDOWS": "ENTER",
    "OPEN_VIP": "V",
    "OPEN_QUESTS": "L",
    "OPEN_BUILD": "B",
    "OPEN_SEARCH": "F",
    "TOGGLE_CITY_MAP": "SPACE",
    "OPEN_MAIL": "M",
    "OPEN_CAMPAIGN": "U",
    "OPEN_ITEMS": "I",
    "OPEN_ALLIANCE": "O",
    "OPEN_COMMANDERS": "P",
    "OPEN_EVENTS": "H",
    "OPEN_TROOPS": "J",
    "OPEN_KINGDOM_OVERVIEW": "G",
    "SELECT_ALL_TROOPS": "CTRL+SHIFT+A",
    "SELECT_ALL_TROOPS_ON_SCREEN": "CTRL+A",
    "FOCUS_TROOP_1": "F1",
    "FOCUS_TROOP_2": "F2",
    "FOCUS_TROOP_3": "F3",
    "FOCUS_TROOP_4": "F4",
    "FOCUS_TROOP_5": "F5",
}
