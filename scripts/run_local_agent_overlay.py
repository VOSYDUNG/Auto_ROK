"""Topmost click-through shadow HUD for the local LLM/harness loop."""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import sys
import tkinter as tk
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_events(path: Path, start: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], start
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start)
        lines = handle.readlines()
        offset = handle.tell()
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events, offset


def _payload_text(value: Any, limit: int = 110) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


class ShadowOverlay:
    def __init__(self, events: Path, poll_ms: int, opacity: float) -> None:
        self.events = events
        self.poll_ms = poll_ms
        self.offset = 0
        self.latest: dict[str, Any] | None = None
        self.root = tk.Tk()
        self.root.title("Auto_ROK Local LLM Shadow")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", opacity)
        self.transparent = "#ff00ff"
        self.root.configure(bg=self.transparent)
        self.root.attributes("-transparentcolor", self.transparent)
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")
        self.canvas = tk.Canvas(
            self.root,
            width=width,
            height=height,
            bg=self.transparent,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.after(100, self._make_click_through)
        self.root.after(0, self._poll)

    def _make_click_through(self) -> None:
        if sys.platform != "win32":
            return
        hwnd = self.root.winfo_id()
        user32 = ctypes.windll.user32
        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_transparent = 0x00000020
        ws_ex_noactivate = 0x08000000
        ws_ex_toolwindow = 0x00000080
        current = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(
            hwnd,
            gwl_exstyle,
            current | ws_ex_layered | ws_ex_transparent | ws_ex_noactivate | ws_ex_toolwindow,
        )

    def _poll(self) -> None:
        events, self.offset = _read_events(self.events, self.offset)
        if events:
            self.latest = events[-1]
        self._render()
        self.root.after(self.poll_ms, self._poll)

    def _render(self) -> None:
        self.canvas.delete("all")
        event = self.latest or {}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        local_llm = payload.get("local_llm") if isinstance(payload.get("local_llm"), dict) else {}
        harness = payload.get("harness") if isinstance(payload.get("harness"), dict) else {}
        status = payload.get("status") or harness.get("status") or event.get("event_type") or "idle"
        model = local_llm.get("model") or payload.get("model") or "local-llm"
        output = local_llm.get("model_output") or local_llm.get("output")
        choice = local_llm.get("choice") or harness.get("choice")
        frame_id = payload.get("frame_id") or harness.get("frame_id")
        state = payload.get("state") or harness.get("state")

        x0, y0 = 18, 18
        width, height = 470, 122
        self.canvas.create_rectangle(
            x0,
            y0,
            x0 + width,
            y0 + height,
            fill="#06151f",
            outline="#6ffcff",
            width=2,
            stipple="gray75",
        )
        self.canvas.create_text(
            x0 + 14,
            y0 + 13,
            anchor="nw",
            text="LOCAL LLM SHADOW  |  HARNESS OWNS INPUT",
            fill="#d8ffff",
            font=("Segoe UI", 10, "bold"),
        )
        lines = [
            f"status: {_payload_text(status, 54)}",
            f"state/frame: {_payload_text(state, 32)} / {_payload_text(frame_id, 42)}",
            f"model: {_payload_text(model, 68)}",
            f"choice: {_payload_text(choice, 96)}",
            f"raw: {_payload_text(output, 96)}",
        ]
        for index, line in enumerate(lines):
            self.canvas.create_text(
                x0 + 14,
                y0 + 36 + index * 16,
                anchor="nw",
                text=line,
                fill="#b6e9ef",
                font=("Consolas", 9),
            )

        cursor = payload.get("cursor_screen")
        if not (
            isinstance(cursor, list)
            and len(cursor) == 2
            and all(isinstance(item, (int, float)) for item in cursor)
        ):
            cursor = payload.get("target_screen")
        if (
            isinstance(cursor, list)
            and len(cursor) == 2
            and all(isinstance(item, (int, float)) for item in cursor)
        ):
            cx, cy = float(cursor[0]), float(cursor[1])
            self.canvas.create_oval(cx - 24, cy - 24, cx + 24, cy + 24, outline="#6ffcff", width=2)
            self.canvas.create_line(cx - 34, cy, cx + 34, cy, fill="#6ffcff", width=1)
            self.canvas.create_line(cx, cy - 34, cx, cy + 34, fill="#6ffcff", width=1)
            self.canvas.create_text(
                cx + 30,
                cy + 28,
                anchor="nw",
                text="shadow cursor",
                fill="#d8ffff",
                font=("Segoe UI", 9, "bold"),
            )

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--opacity", type=float, default=0.92)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = Path(args.events).resolve()
    if not events.is_relative_to((ROOT / "workspace").resolve()):
        raise SystemExit("events must stay under workspace")
    if not 25 <= args.poll_ms <= 2000:
        raise SystemExit("poll-ms must be within 25..2000")
    if not 0.20 <= args.opacity <= 1.0:
        raise SystemExit("opacity must be within 0.20..1.0")
    ShadowOverlay(events, args.poll_ms, args.opacity).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
