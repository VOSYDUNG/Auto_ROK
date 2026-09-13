import unittest

from harness.action_surface import (
    ActionRequest,
    ActionResolutionError,
    InputKind,
    SemanticActionSurface,
    TRAINED_NATIVE_SHORTCUTS,
)
from harness.contracts import BoundingBox
from harness.scene_graph import SceneGraph, VisualTarget


class SemanticActionSurfaceTests(unittest.TestCase):
    def test_native_shortcut_does_not_require_scene(self) -> None:
        surface = SemanticActionSurface(TRAINED_NATIVE_SHORTCUTS)

        resolved = surface.resolve(ActionRequest("OPEN_MAIL"))

        self.assertEqual(InputKind.HOTKEY, resolved.kind)
        self.assertEqual("M", resolved.key)
        self.assertIsNone(resolved.point)
        self.assertEqual("native_shortcut", resolved.source)

    def test_visual_target_fallback_uses_current_frame(self) -> None:
        scene = SceneGraph(
            frame_id="frame-2",
            state_hint="DIALOG",
            targets=(
                VisualTarget(
                    target_id="CLAIM_BUTTON",
                    frame_id="frame-2",
                    label="Claim",
                    bbox=BoundingBox(100, 200, 200, 260),
                    confidence=0.98,
                    source="ocr",
                ),
            ),
        )
        surface = SemanticActionSurface({})

        resolved = surface.resolve(
            ActionRequest("CLAIM_REWARD", target_id="CLAIM_BUTTON"),
            scene=scene,
        )

        self.assertEqual(InputKind.CLICK_TARGET, resolved.kind)
        self.assertEqual((150, 230), resolved.point)
        self.assertEqual("frame-2", resolved.frame_id)
        self.assertEqual("ocr", resolved.source)

    def test_unknown_action_without_target_is_rejected(self) -> None:
        surface = SemanticActionSurface({})

        with self.assertRaises(ActionResolutionError):
            surface.resolve(ActionRequest("UNKNOWN_ACTION"))

    def test_low_confidence_target_is_rejected(self) -> None:
        scene = SceneGraph(
            frame_id="frame-3",
            state_hint=None,
            targets=(
                VisualTarget(
                    target_id="BUTTON",
                    frame_id="frame-3",
                    label="Button",
                    bbox=BoundingBox(0, 0, 10, 10),
                    confidence=0.60,
                    source="visual_grounder",
                ),
            ),
        )
        surface = SemanticActionSurface({}, min_target_confidence=0.90)

        with self.assertRaises(LookupError):
            surface.resolve(
                ActionRequest("CLICK_BUTTON", target_id="BUTTON"),
                scene=scene,
            )


if __name__ == "__main__":
    unittest.main()
