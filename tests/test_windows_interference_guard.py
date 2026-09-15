from harness.action_surface import InputKind, ResolvedInput
from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot
from harness.scene_graph import SceneGraph
from harness.windows_interference_guard import WindowsForegroundInterferenceGuard


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-guard")
SNAPSHOT = ToolSnapshot("GATHER_RESOURCE", "one-character", "f1", "CITY_VIEW")
CHOICE = ActionChoice("OPEN_SEARCH")
RESOLVED = ResolvedInput("OPEN_SEARCH", InputKind.HOTKEY, key="F")


def test_live_actuation_is_disabled_by_default():
    scene = SceneGraph("f1", None, facts={})
    result = WindowsForegroundInterferenceGuard().check(
        CONTEXT, SNAPSHOT, CHOICE, scene, RESOLVED
    )
    assert result.allowed is False
    assert result.code == "LIVE_ACTUATION_NOT_ARMED"


def test_armed_guard_requires_bound_window_identity_before_platform_checks():
    scene = SceneGraph("f1", None, facts={})
    result = WindowsForegroundInterferenceGuard(armed=True).check(
        CONTEXT, SNAPSHOT, CHOICE, scene, RESOLVED
    )
    assert result.allowed is False
    assert result.code == "WINDOW_IDENTITY_MISSING"
