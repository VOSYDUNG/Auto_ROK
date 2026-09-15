"""Translate frame-local visual targets into current screen coordinates."""
from __future__ import annotations

from dataclasses import replace

from harness.action_surface import ActionRequest, InputKind, ResolvedInput, SemanticActionSurface
from harness.scene_graph import SceneGraph


class ScreenMappedSemanticActionSurface(SemanticActionSurface):
    """Shortcut-first surface; visual clicks require a captured client-screen rect."""

    def resolve(
        self,
        request: ActionRequest,
        *,
        scene: SceneGraph | None = None,
    ) -> ResolvedInput:
        resolved = super().resolve(request, scene=scene)
        if resolved.kind is not InputKind.CLICK_TARGET:
            return resolved
        if scene is None or resolved.point is None:
            raise ValueError("visual action requires a current scene and point")

        rect = scene.facts.get("client_screen_rect")
        if not (
            isinstance(rect, (list, tuple))
            and len(rect) == 4
            and all(type(item) is int for item in rect)
        ):
            raise ValueError("client_screen_rect is missing from current capture facts")
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        x, y = resolved.point
        if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
            raise ValueError("visual target point is outside the current client bounds")
        return replace(
            resolved,
            point=(left + x, top + y),
            source=f"{resolved.source}+client_to_screen",
        )
