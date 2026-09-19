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


class _SendInputMouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _SendInputKeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _SendInputHardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _SendInputUnion(ctypes.Union):
    _fields_ = [
        ("mi", _SendInputMouseInput),
        ("ki", _SendInputKeyboardInput),
        ("hi", _SendInputHardwareInput),
    ]


class _SendInput(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _SendInputUnion),
    ]


class Win32InputBackend(Protocol):
    def move_to(self, x: int, y: int) -> None: ...
    def left_click(self) -> None: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...


class CtypesWin32InputBackend:
    """Thin user32 wrapper. It never activates or focuses a window.

    ``keybd_event``/``mouse_event`` are legacy compatibility shims and are not
    reliably delivered to a DirectX game.  Use the native ``SendInput`` API so
    the actuator follows the same foreground-only guard while emitting normal
    user-level input packets.  Coordinates are still moved with
    ``SetCursorPos`` because the guard owns the screen mapping and bounds.
    """

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _KEYEVENTF_KEYUP = 0x0002

    _MOUSEINPUT = _SendInputMouseInput
    _KEYBDINPUT = _SendInputKeyboardInput
    _INPUT = _SendInput

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
        self.user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(self._INPUT),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = wintypes.UINT
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
        events = (
            self._INPUT(
                type=self._INPUT_MOUSE,
                mi=self._MOUSEINPUT(dwFlags=self._MOUSEEVENTF_LEFTDOWN),
            ),
            self._INPUT(
                type=self._INPUT_MOUSE,
                mi=self._MOUSEINPUT(dwFlags=self._MOUSEEVENTF_LEFTUP),
            ),
        )
        self._send(events)

    def _send(self, events: tuple[_SendInput, ...]) -> None:
        if not events:
            return
        array_type = self._INPUT * len(events)
        sent = int(self.user32.SendInput(len(events), array_type(*events), ctypes.sizeof(self._INPUT)))
        if sent != len(events):
            error = ctypes.get_last_error()
            self.diagnostics["send_input_error"] = error
            raise WindowsInputError(
                f"SendInput sent {sent}/{len(events)} events (win32_error={error})"
            )

    def _vk(self, key: str) -> int:
        normalized = key.upper()
        if normalized in self._VK:
            return self._VK[normalized]
        if len(normalized) == 1 and ("A" <= normalized <= "Z" or "0" <= normalized <= "9"):
            return ord(normalized)
        raise WindowsInputError(f"unsupported keyboard key: {key!r}")

    def key_down(self, key: str) -> None:
        event = self._INPUT(
            type=self._INPUT_KEYBOARD,
            ki=self._KEYBDINPUT(wVk=self._vk(key)),
        )
        self._send((event,))

    def key_up(self, key: str) -> None:
        event = self._INPUT(
            type=self._INPUT_KEYBOARD,
            ki=self._KEYBDINPUT(wVk=self._vk(key), dwFlags=self._KEYEVENTF_KEYUP),
        )
        self._send((event,))


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
