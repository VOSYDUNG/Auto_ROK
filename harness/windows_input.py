"""Ordinary Win32 mouse/keyboard actuator used behind the mission guard."""
from __future__ import annotations

import os
import time
import ctypes
from ctypes import wintypes
from typing import Protocol

from harness.human_io import HumanInputAction, KeyboardAction, MouseAction


class WindowsInputError(RuntimeError):
    pass


class Win32InputBackend(Protocol):
    def move_to(self, x: int, y: int) -> None: ...
    def left_click(self) -> None: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...


class CtypesWin32InputBackend:
    """Thin user32 wrapper. It never activates or focuses a window."""

    _VK = {
        "ENTER": 0x0D,
        "SPACE": 0x20,
        "CTRL": 0x11,
        "SHIFT": 0x10,
        "ALT": 0x12,
        "F1": 0x70,
        "F2": 0x71,
        "F3": 0x72,
        "F4": 0x73,
        "F5": 0x74,
    }

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsInputError("Win32 input backend is available only on Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.user32.OpenInputDesktop.restype = wintypes.HANDLE
        self.user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        self.user32.SetThreadDesktop.restype = wintypes.BOOL
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
        session_id = wintypes.DWORD()
        session_ok = kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        self.diagnostics = {
            "process_id": os.getpid(),
            "thread_id": int(kernel32.GetCurrentThreadId()),
            "session_id": int(session_id.value) if session_ok else None,
            "desktop_name": None,
            "foreground_hwnd": int(self.user32.GetForegroundWindow()),
            "expected_game_hwnd": None,
        }
        hdesk = self.user32.OpenInputDesktop(0, False, 0x01FF)
        if not hdesk:
            self.diagnostics["open_input_desktop_error"] = ctypes.get_last_error()
        else:
            if not self.user32.SetThreadDesktop(hdesk):
                self.diagnostics["set_thread_desktop_error"] = ctypes.get_last_error()
            else:
                self.diagnostics["set_thread_desktop"] = True

    def move_to(self, x: int, y: int) -> None:
        if not self.user32.SetCursorPos(int(x), int(y)):
            error = ctypes.get_last_error()
            self.diagnostics["set_cursor_pos_error"] = error
            raise WindowsInputError(f"SetCursorPos failed (win32_error={error})")

    def left_click(self) -> None:
        self.user32.mouse_event(0x0002, 0, 0, 0, 0)
        self.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def _vk(self, key: str) -> int:
        normalized = key.upper()
        if normalized in self._VK:
            return self._VK[normalized]
        if len(normalized) == 1 and ("A" <= normalized <= "Z" or "0" <= normalized <= "9"):
            return ord(normalized)
        raise WindowsInputError(f"unsupported keyboard key: {key!r}")

    def key_down(self, key: str) -> None:
        self.user32.keybd_event(self._vk(key), 0, 0, 0)

    def key_up(self, key: str) -> None:
        self.user32.keybd_event(self._vk(key), 0, 0x0002, 0)


class WindowsHumanInputActuator:
    """Concrete HumanInputActuator with a deliberately small action surface."""

    def __init__(self, backend: Win32InputBackend | None = None) -> None:
        self.backend = backend or CtypesWin32InputBackend()

    def perform(self, action: HumanInputAction) -> None:
        if isinstance(action, MouseAction):
            if action.kind != "click" or action.x is None or action.y is None:
                raise WindowsInputError("only bounded left-click mouse actions are supported")
            if action.button not in (None, "left"):
                raise WindowsInputError("only left mouse click is supported")
            self.backend.move_to(action.x, action.y)
            time.sleep(0.05)
            self.backend.left_click()
            time.sleep(0.4)
            return

        if isinstance(action, KeyboardAction):
            keys = tuple(str(item).upper() for item in action.keys if str(item))
            if not keys:
                raise WindowsInputError("keyboard action contains no keys")
            pressed: list[str] = []
            try:
                for key in keys:
                    self.backend.key_down(key)
                    pressed.append(key)
                time.sleep(0.05)
            finally:
                for key in reversed(pressed):
                    self.backend.key_up(key)
            time.sleep(0.4)
            return

        raise WindowsInputError(f"unsupported input action: {type(action).__name__}")
