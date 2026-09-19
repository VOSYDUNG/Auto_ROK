"""Read-only Windows input/desktop diagnostics.

This probe must never move the pointer or change the calling thread's desktop.
Earlier versions called ``SetThreadDesktop`` and ``SetCursorPos`` while merely
diagnosing the host; that is outside the passive-observation contract.
"""

import ctypes
import json
import os
from ctypes import wintypes

u = ctypes.WinDLL('user32', use_last_error=True)
k = ctypes.WinDLL('kernel32', use_last_error=True)
u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
u.OpenInputDesktop.restype = wintypes.HANDLE
u.GetThreadDesktop.argtypes = [wintypes.DWORD]
u.GetThreadDesktop.restype = wintypes.HANDLE
u.GetProcessWindowStation.restype = wintypes.HANDLE
u.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
u.GetUserObjectInformationW.restype = wintypes.BOOL
u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u.GetCursorPos.restype = wintypes.BOOL
u.GetForegroundWindow.restype = wintypes.HWND
k.GetCurrentThreadId.restype = wintypes.DWORD
k.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
k.ProcessIdToSessionId.restype = wintypes.BOOL

DESKTOP_READOBJECTS = 0x0001
DESKTOP_READATTRIBUTES = 0x0002

def name(handle):
    n = wintypes.DWORD()
    buf = ctypes.create_unicode_buffer(256)
    if not handle or not u.GetUserObjectInformationW(handle, 2, buf, ctypes.sizeof(buf), ctypes.byref(n)):
        return None
    return buf.value

def cursor():
    p = wintypes.POINT()
    return [p.x, p.y] if u.GetCursorPos(ctypes.byref(p)) else None

sid = wintypes.DWORD()
k.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
tid = int(k.GetCurrentThreadId())
before = u.GetThreadDesktop(tid)
# Request read-only desktop rights; this handle is never used for mutation.
inp = u.OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_READATTRIBUTES)
out = {
    'PROCESS_ID': os.getpid(), 'THREAD_ID': tid, 'SESSION_ID': sid.value,
    'WINDOW_STATION_NAME': name(u.GetProcessWindowStation()),
    'THREAD_DESKTOP_BEFORE_HANDLE': int(before or 0), 'THREAD_DESKTOP_BEFORE_NAME': name(before),
    'INPUT_DESKTOP_HANDLE': int(inp or 0), 'INPUT_DESKTOP_NAME': name(inp),
    'OPEN_INPUT_DESKTOP_RESULT': bool(inp), 'OPEN_INPUT_DESKTOP_ERROR': None if inp else ctypes.get_last_error(),
    'SET_THREAD_DESKTOP_RESULT': False, 'SET_THREAD_DESKTOP_ERROR': None,
    'FOREGROUND_HWND': int(u.GetForegroundWindow() or 0), 'EXPECTED_GAME_HWND': 1772876,
    'CURSOR_BEFORE': cursor(), 'CURSOR_TARGET': None,
    'input_emitted': False,
}
# Keep the diagnostic call entirely observational.  In particular, do not
# switch the calling thread to the input desktop and do not call SetCursorPos.
out['THREAD_DESKTOP_AFTER_HANDLE'] = int(before or 0)
out['THREAD_DESKTOP_AFTER_NAME'] = name(before)
out['SET_CURSOR_POS_RESULT'] = False
out['SET_CURSOR_POS_ERROR'] = None
out['CURSOR_AFTER'] = cursor()
print(json.dumps(out))
