"""Passive HWND-only Windows Graphics Capture backend for the ROK client."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version as package_version
from pathlib import Path
import threading
from typing import Any


class WindowsCaptureError(RuntimeError):
    pass


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _process_path(pid: int) -> str | None:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def discover_rok_window(title: str = "Rise of Kingdoms", exe: str = "MASS.exe") -> dict[str, Any]:
    matches: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd: int, _lparam: int) -> bool:
        if _user32.IsWindowVisible(hwnd) and _window_title(hwnd) == title:
            pid = _window_pid(hwnd)
            process_path = _process_path(pid)
            if process_path and Path(process_path).name.casefold() == exe.casefold():
                matches.append({"hwnd": int(hwnd), "pid": pid, "title": title,
                                "exe": exe, "process_path": process_path})
        return True

    _user32.EnumWindows(visit, 0)
    if len(matches) != 1:
        raise WindowsCaptureError(f"expected exactly one visible {title}/{exe} window, found {len(matches)}")
    return matches[0]


def _snapshot(target: dict[str, Any]) -> dict[str, Any]:
    hwnd = target["hwnd"]
    if not _user32.IsWindow(hwnd) or _window_pid(hwnd) != target["pid"]:
        raise WindowsCaptureError("target HWND/PID identity changed")
    if _window_title(hwnd) != target["title"]:
        raise WindowsCaptureError("target window title changed")
    process_path = _process_path(target["pid"])
    if not process_path or Path(process_path).name.casefold() != target["exe"].casefold():
        raise WindowsCaptureError("target executable identity changed")
    if _user32.IsIconic(hwnd):
        raise WindowsCaptureError("target window is minimized")

    window = wintypes.RECT()
    client = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(window)) or not _user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise WindowsCaptureError("cannot read target window/client bounds")
    origin = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise WindowsCaptureError("cannot map target client bounds to screen")
    client_width, client_height = client.right - client.left, client.bottom - client.top
    if client_width < 1 or client_height < 1:
        raise WindowsCaptureError("target client bounds are empty")
    dpi = int(_user32.GetDpiForWindow(hwnd)) if hasattr(_user32, "GetDpiForWindow") else 96
    return {
        **target,
        "process_path": process_path,
        "window_rect": [window.left, window.top, window.right, window.bottom],
        "client_screen_rect": [origin.x, origin.y, origin.x + client_width, origin.y + client_height],
        "client_size": [client_width, client_height],
        "dpi": dpi,
        "dpi_scale": dpi / 96.0,
    }


def _same_binding(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("hwnd", "pid", "title", "exe", "process_path", "window_rect",
            "client_screen_rect", "client_size", "dpi", "dpi_scale")
    return all(before[key] == after[key] for key in keys)


def _capture_options(hwnd: int) -> dict[str, Any]:
    """Keep every optional setting at OS default and bind only one HWND."""
    if type(hwnd) is not int or hwnd <= 0:
        raise WindowsCaptureError("capture HWND must be a positive integer")
    return {"cursor_capture": None, "draw_border": None, "secondary_window": None,
            "minimum_update_interval": None, "dirty_region": None, "window_hwnd": hwnd}


def capture_rok_client(output: str | Path, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """Persist one current client-area frame without activation or input."""
    if not 0.1 <= timeout_seconds <= 30.0:
        raise WindowsCaptureError("timeout_seconds must be between 0.1 and 30")
    output = Path(output)
    target = discover_rok_window()
    before = _snapshot(target)

    try:
        import cv2
        from windows_capture import WindowsCapture
    except ImportError as exc:
        raise WindowsCaptureError("windows-capture 2.0.1 runtime is unavailable") from exc

    arrived = threading.Event()
    result: dict[str, Any] = {}
    capture = WindowsCapture(**_capture_options(target["hwnd"]))

    @capture.event
    def on_frame_arrived(frame, capture_control) -> None:
        if arrived.is_set():
            capture_control.stop()
            return
        try:
            result["pixels"] = frame.frame_buffer.copy()
            result["frame_width"] = int(frame.width)
            result["frame_height"] = int(frame.height)
            result["captured_at"] = datetime.now(timezone.utc)
        except Exception as exc:  # callback exceptions must reach the caller
            result["error"] = exc
        finally:
            arrived.set()
            capture_control.stop()

    @capture.event
    def on_closed() -> None:
        arrived.set()

    control = capture.start_free_threaded()
    if not arrived.wait(timeout_seconds):
        control.stop()
        control.wait()
        raise WindowsCaptureError("target-window capture timed out before a frame arrived")
    control.wait()
    if "error" in result:
        raise WindowsCaptureError(f"capture callback failed: {result['error']}")
    if "pixels" not in result:
        raise WindowsCaptureError("capture session closed before a frame arrived")

    after = _snapshot(target)
    if not _same_binding(before, after):
        raise WindowsCaptureError("target identity, bounds, or DPI changed during capture")

    pixels = result["pixels"]
    frame_width, frame_height = result["frame_width"], result["frame_height"]
    client_width, client_height = before["client_size"]
    window_left, window_top, window_right, window_bottom = before["window_rect"]
    window_width, window_height = window_right - window_left, window_bottom - window_top
    if (frame_width, frame_height) == (client_width, client_height):
        client_pixels = pixels
        crop = [0, 0, client_width, client_height]
        mapping = "capture_frame_is_client"
    elif (frame_width, frame_height) == (window_width, window_height):
        client_left, client_top, _, _ = before["client_screen_rect"]
        x, y = client_left - window_left, client_top - window_top
        if x < 0 or y < 0 or x + client_width > frame_width or y + client_height > frame_height:
            raise WindowsCaptureError("derived client crop exceeds captured window frame")
        client_pixels = pixels[y:y + client_height, x:x + client_width].copy()
        crop = [x, y, client_width, client_height]
        mapping = "window_rect_to_client"
    else:
        raise WindowsCaptureError(
            f"capture dimensions {frame_width}x{frame_height} match neither client "
            f"{client_width}x{client_height} nor window {window_width}x{window_height}"
        )

    bgr = client_pixels[:, :, :3]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sample = gray[::max(1, gray.shape[0] // 300), ::max(1, gray.shape[1] // 300)]
    quality = {"mean_luminance": float(sample.mean()), "std_luminance": float(sample.std()),
               "nonblack_ratio": float((sample > 5).mean())}
    if quality["std_luminance"] < 2.0 or quality["nonblack_ratio"] < 0.01:
        raise WindowsCaptureError(f"captured client frame is blank or low-information: {quality}")
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise WindowsCaptureError("OpenCV failed to encode captured client frame")
    png = encoded.tobytes()
    digest = hashlib.sha256(png).hexdigest()
    captured_at = result["captured_at"]
    frame_id = f"rok-{captured_at.strftime('%Y%m%dT%H%M%S%fZ')}-{digest[:12]}"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(png)
    temporary.replace(output)
    return {
        "schema_version": 1,
        "status": "captured",
        "backend": {"name": "windows-capture", "version": package_version("windows-capture"),
                    "target_mode": "window_hwnd", "draw_border": "default",
                    "cursor_capture": "default", "secondary_window": "default",
                    "dirty_region": "default", "minimum_update_interval": "default"},
        "target": {key: after[key] for key in ("hwnd", "pid", "title", "exe", "process_path")},
        "frame": {"id": frame_id, "captured_at": captured_at.isoformat(), "width": client_width,
                  "height": client_height, "client_bounds": [0, 0, client_width, client_height],
                  "dpi_scale": after["dpi_scale"], "image_sha256": digest},
        "capture_mapping": {"source_frame_size": [frame_width, frame_height],
                            "client_crop_in_source": crop, "method": mapping},
        "pre_capture": before,
        "post_capture": after,
        "quality": quality,
        "png": str(output),
        "non_interference": {"foreground_activation": False, "mouse_input": False,
                             "keyboard_input": False, "desktop_fallback": False},
    }
