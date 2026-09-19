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


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INFORMATION_CLASS_INTEGRITY = 25


def _process_integrity_rid(pid: int) -> int | None:
    """Return the process token's mandatory-integrity RID, if readable."""
    if type(pid) is not int or pid <= 0:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS_INTEGRITY,
            None,
            0,
            ctypes.byref(size),
        )
        if size.value <= 0:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS_INTEGRITY,
            buffer,
            size.value,
            ctypes.byref(size),
        ):
            return None
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not sid_pointer:
            return None
        subauthority_count = ctypes.cast(
            sid_pointer + 1,
            ctypes.POINTER(ctypes.c_ubyte),
        ).contents.value
        if subauthority_count <= 0:
            return None
        rid_pointer = sid_pointer + 8 + (subauthority_count - 1) * ctypes.sizeof(ctypes.c_ulong)
        return int(ctypes.cast(rid_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


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
        try:
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass
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

        current_integrity = _process_integrity_rid(os.getpid())
        target_integrity = _process_integrity_rid(pid)
        if current_integrity is None or target_integrity is None:
            return InterferenceCheck(
                False,
                "PROCESS_INTEGRITY_UNAVAILABLE",
                {
                    "current_integrity_rid": current_integrity,
                    "target_integrity_rid": target_integrity,
                },
            )
        if current_integrity < target_integrity:
            return InterferenceCheck(
                False,
                "INPUT_INTEGRITY_MISMATCH",
                {
                    "current_integrity_rid": current_integrity,
                    "target_integrity_rid": target_integrity,
                    "reason": "Windows UIPI can block lower-integrity SendInput to the target",
                },
            )

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
