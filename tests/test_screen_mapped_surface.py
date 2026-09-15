import pytest

from harness.action_surface import ActionRequest, InputKind
from harness.contracts import BoundingBox
from harness.scene_graph import SceneGraph, VisualTarget
from harness.screen_mapped_surface import ScreenMappedSemanticActionSurface


def test_visual_target_is_translated_from_client_to_screen_coordinates():
    target = VisualTarget(
        "BUTTON",
        "f1",
        "Button",
        BoundingBox(100, 50, 200, 90),
        0.99,
        "test",
    )
    scene = SceneGraph(
        "f1",
        None,
        (target,),
        {"client_screen_rect": [300, 200, 1580, 920]},
    )
    resolved = ScreenMappedSemanticActionSurface(min_target_confidence=0.9).resolve(
        ActionRequest("CLICK", "BUTTON"),
        scene=scene,
    )
    assert resolved.kind is InputKind.CLICK_TARGET
    assert resolved.point == (450, 270)
    assert "client_to_screen" in resolved.source


def test_visual_target_without_screen_mapping_fails_closed():
    target = VisualTarget(
        "BUTTON",
        "f1",
        "Button",
        BoundingBox(10, 10, 30, 30),
        1.0,
        "test",
    )
    scene = SceneGraph("f1", None, (target,), {})
    with pytest.raises(ValueError, match="client_screen_rect"):
        ScreenMappedSemanticActionSurface().resolve(ActionRequest("CLICK", "BUTTON"), scene=scene)


def test_native_shortcut_does_not_require_screen_mapping():
    resolved = ScreenMappedSemanticActionSurface({"OPEN_SEARCH": "F"}).resolve(
        ActionRequest("OPEN_SEARCH"),
        scene=SceneGraph("f1", None),
    )
    assert resolved.kind is InputKind.HOTKEY
    assert resolved.key == "F"
