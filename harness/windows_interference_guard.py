"""Fail-closed foreground/geometry guard for optional live Windows actuation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Mapping

from harness.action_surface import ResolvedInput
from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot
from harness.mission_tool import InterferenceCheck
from harness.scene_graph import SceneGraph


class WindowsForegroundInterferenceGuard:
    """Authorize input only for the still-current foreground ROK client.

    Live actuation is disabled unless ``armed=True`` is supplied explicitly.
    The guard verifies captured HWND/PID identity and client-screen geometry
    immediately before input. It never activates or focuses the game window.
    """

    def __init__(
        self,
        *,
        armed: bool = False,
        expected_title: str = "Rise of Kingdoms",
        expected_exe: str = "MASS.exe",
    ) -> None:
        self.armed = armed
        self.expected_title = expected_title
        self.expected_exe = expected_exe

    def check(
        self,
        context: MissionContext,
        before: ToolSnapshot,
        choice: ActionChoice,
        scene: SceneGraph,
        resolved: ResolvedInput,
    ) -> InterferenceCheck:
        if not self.armed:
            return InterferenceCheck(False, "LIVE_ACTUATION_NOT_ARMED")

        window = scene.facts.get("window")
        if not isinstance(window, Mapping):
            return InterferenceCheck(False, "WINDOW_IDENTITY_MISSING")
        if window.get("title") != self.expected_title or str(window.get("exe", "")).casefold() != self.expected_exe.casefold():
            return InterferenceCheck(False, "WINDOW_IDENTITY_MISMATCH")
        hwnd, pid = window.get("hwnd"), window.get("pid")
        if type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0:
            return InterferenceCheck(False, "WINDOW_IDENTITY_INVALID")

        rect = scene.facts.get("client_screen_rect")
        if not (
            isinstance(rect, (list, tuple))
            and len(rect) == 4
            and all(type(item) is int for item in rect)
        ):
            return InterferenceCheck(False, "CLIENT_SCREEN_RECT_MISSING")

        if os.name != "nt":
            return InterferenceCheck(False, "WINDOWS_GUARD_UNAVAILABLE")

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        foreground = int(user32.GetForegroundWindow())
        if foreground != hwnd:
            return InterferenceCheck(
                False,
                "TARGET_NOT_FOREGROUND",
                {"expected_hwnd": hwnd, "foreground_hwnd": foreground},
            )

        current_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(current_pid))
        if int(current_pid.value) != pid:
            return InterferenceCheck(False, "TARGET_PID_CHANGED")

        client = wintypes.RECT()
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
            return InterferenceCheck(False, "CLIENT_RECT_UNAVAILABLE")
        origin = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
            return InterferenceCheck(False, "CLIENT_ORIGIN_UNAVAILABLE")
        current_rect = [
            int(origin.x),
            int(origin.y),
            int(origin.x + client.right - client.left),
            int(origin.y + client.bottom - client.top),
        ]
        if list(rect) != current_rect:
            return InterferenceCheck(
                False,
                "CLIENT_GEOMETRY_CHANGED",
                {"captured_client_screen_rect": list(rect), "current_client_screen_rect": current_rect},
            )

        return InterferenceCheck(
            True,
            "FOREGROUND_TARGET_STABLE",
            {
                "guard_scope": "foreground_hwnd_pid_geometry",
                "target_hwnd": hwnd,
                "target_pid": pid,
                "client_screen_rect": current_rect,
            },
        )
