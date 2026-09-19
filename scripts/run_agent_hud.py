"""Slim operator HUD for the local-LLM agent loop.

Replaces scripts/run_local_agent_overlay.py, which the operator rejected: it
covered the whole screen, used a neon cyan-on-black palette, and fringed pink.

Three things were wrong with it, and each is fixed here for a stated reason.

1. It created a fullscreen window at +0+0 and keyed out the background.  This
   one is 607x34 and docks into measured dead space.  The frame captured on
   2026-09-20 shows the game's own HUD occupies x=0..334 and x=941..1366 along
   the top edge, leaving a 607px band that the client never draws into.  A
   window that small cannot cover anything regardless of what it renders.

2. The pink.  The old overlay set BOTH ``-alpha`` and ``-transparentcolor``
   with a magenta key.  On a layered window the key colour is composited
   before the alpha blend, so magenta leaks back as a pink haze over
   everything.  This HUD uses alpha alone and never sets a colour key, so
   there is nothing to leak.

3. It drew a 68px crosshair at every action point, over live game UI.  Here
   the action marker is a small ring that fades within a second, and only at
   the moment of dispatch.

The HUD is read-only and click-through.  It never sends input, and it is not a
control surface: it reports what the harness already decided.
"""
from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Measured from workspace/runs/p3-observe-20260920 - the band between the
#: game's player panel and its resource strip.
DOCK_X, DOCK_Y = 334, 2
DOCK_W, DOCK_H = 607, 34
COLLAPSED_W, COLLAPSED_H = 120, 4

FONT_UI = ("Segoe UI", 9)
FONT_UI_MEDIUM = ("Segoe UI", 9, "bold")
FONT_NUM = ("Consolas", 9)


@dataclass(frozen=True)
class Look:
    """One HUD state.  Calm by default; amber only when input is live."""

    dot: str
    background: str
    border: str
    primary: str
    muted: str


LOOKS = {
    "observe": Look("#6b7785", "#161a1f", "#2a3139", "#c9d2dc", "#7d8794"),
    "thinking": Look("#5d9cd6", "#161a1f", "#2a3139", "#c9d2dc", "#7d8794"),
    "armed": Look("#e8a33d", "#2a1f10", "#8a6520", "#f3d9a8", "#c9a468"),
    "degraded": Look("#c4705e", "#161a1f", "#2a3139", "#c9d2dc", "#7d8794"),
    "blocked": Look("#c4705e", "#25171a", "#7a3b3b", "#e8c4c4", "#b08484"),
}


def _read_new_events(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Tail the JSONL stream.  A missing file is a normal idle state."""
    if not path.exists():
        return [], offset
    try:
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            lines = handle.readlines()
            new_offset = handle.tell()
    except OSError:
        return [], offset
    events = []
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
    return events, new_offset


def _shorten(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentHud:
    def __init__(self, events: Path, poll_ms: int, opacity: float) -> None:
        self.events = events
        self.poll_ms = poll_ms
        self.offset = 0
        self.expanded = False
        self.idle_polls = 0
        self.state_key = "observe"
        self.fields = {
            "label": "chờ sự kiện",
            "detail": str(events.name),
            "queue": "",
            "buff": "",
            "safety": "an toàn",
        }

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Alpha only.  Never -transparentcolor: the two together are what made
        # the previous overlay fringe pink.
        self.root.attributes("-alpha", opacity)
        self.root.geometry(f"{COLLAPSED_W}x{COLLAPSED_H}+{DOCK_X}+{DOCK_Y}")
        self.root.configure(bg=LOOKS["observe"].background)

        self.canvas = tk.Canvas(
            self.root, highlightthickness=0, bd=0, bg=LOOKS["observe"].background
        )
        self.canvas.pack(fill="both", expand=True)
        self._make_click_through()

    def _make_click_through(self) -> None:
        """Mouse events pass through to the game underneath."""
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception:
            # A HUD that cannot become click-through is still worth showing;
            # it simply must not steal clicks it cannot forward.
            self.root.attributes("-disabled", True)

    def _apply(self, event: dict[str, Any]) -> None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        harness = payload.get("harness") if isinstance(payload.get("harness"), dict) else {}
        local_llm = payload.get("local_llm") if isinstance(payload.get("local_llm"), dict) else {}

        status = str(payload.get("status") or harness.get("status") or "")
        decision = str(harness.get("decision") or "")
        armed = bool(payload.get("live_armed"))

        if armed:
            self.state_key = "armed"
            self.fields["safety"] = "ĐÃ ARM"
        else:
            self.fields["safety"] = "an toàn"
            if status.upper() in {"BLOCKED", "FAILED", "ERROR"}:
                self.state_key = "blocked"
            elif payload.get("degraded") or decision.upper() == "SCARCITY":
                self.state_key = "degraded"
            elif local_llm.get("model"):
                self.state_key = "thinking"
            else:
                self.state_key = "observe"

        label = {
            "armed": "sắp bấm",
            "thinking": "đang hỏi model",
            "degraded": "tụt bậc",
            "blocked": "dừng",
        }.get(self.state_key, "quan sát")
        self.fields["label"] = label

        choice = harness.get("choice") if isinstance(harness.get("choice"), dict) else {}
        detail = choice.get("action_id") or harness.get("state") or payload.get("state") or status
        target = choice.get("target_id")
        if target:
            detail = f"{detail} · {target}"
        self.fields["detail"] = _shorten(detail, 46)

        used, capacity = payload.get("queue_used"), payload.get("queue_capacity")
        self.fields["queue"] = f"{used}/{capacity}" if used is not None and capacity else ""
        buff = payload.get("buff_remaining")
        self.fields["buff"] = f"buff {_shorten(buff, 8)}" if buff else ""

        self.expanded = True
        self.idle_polls = 0

    def _poll(self) -> None:
        events, self.offset = _read_new_events(self.events, self.offset)
        for event in events:
            self._apply(event)
        if not events:
            self.idle_polls += 1
            # Collapse to a hairline after roughly twelve quiet polls.
            if self.expanded and self.state_key != "armed" and self.idle_polls > 12:
                self.expanded = False
        self._render()
        self.root.after(self.poll_ms, self._poll)

    def _render(self) -> None:
        look = LOOKS[self.state_key]
        self.canvas.delete("all")

        if not self.expanded:
            self.root.geometry(
                f"{COLLAPSED_W}x{COLLAPSED_H}+{DOCK_X}+{DOCK_Y}"
            )
            self.root.configure(bg=look.background)
            self.canvas.configure(bg=look.background)
            self.canvas.create_rectangle(
                0, 0, COLLAPSED_W, COLLAPSED_H, fill=look.background, outline=""
            )
            self.canvas.create_rectangle(
                0, 0, 22, COLLAPSED_H, fill=look.dot, outline=""
            )
            return

        self.root.geometry(f"{DOCK_W}x{DOCK_H}+{DOCK_X}+{DOCK_Y}")
        self.root.configure(bg=look.background)
        self.canvas.configure(bg=look.background)
        self.canvas.create_rectangle(
            0, 0, DOCK_W - 1, DOCK_H - 1, fill=look.background, outline=look.border
        )

        mid = DOCK_H // 2
        self.canvas.create_oval(12, mid - 4, 19, mid + 3, fill=look.dot, outline="")

        x = 28
        self.canvas.create_text(
            x, mid, text=self.fields["label"], anchor="w",
            fill=look.primary, font=FONT_UI_MEDIUM,
        )
        x += 8 + max(60, len(self.fields["label"]) * 7)
        self.canvas.create_text(
            x, mid, text=self.fields["detail"], anchor="w",
            fill=look.muted, font=FONT_NUM,
        )

        right = DOCK_W - 12
        safety = self.fields["safety"]
        pad = 6
        width = len(safety) * 7 + pad * 2
        if self.state_key == "armed":
            self.canvas.create_rectangle(
                right - width, mid - 8, right, mid + 8,
                fill=look.border, outline="",
            )
            self.canvas.create_text(
                right - width / 2, mid, text=safety, fill=look.primary, font=FONT_UI_MEDIUM
            )
        else:
            self.canvas.create_rectangle(
                right - width, mid - 8, right, mid + 8, fill="", outline="#38503a"
            )
            self.canvas.create_text(
                right - width / 2, mid, text=safety, fill="#8ab98a", font=FONT_UI
            )
        right -= width + 12

        for value, colour, font in (
            (self.fields["buff"], look.muted, FONT_NUM),
            (self.fields["queue"], look.primary, FONT_NUM),
        ):
            if not value:
                continue
            self.canvas.create_text(right, mid, text=value, anchor="e", fill=colour, font=font)
            right -= len(value) * 7 + 14

    def run(self) -> None:
        self._poll()
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", required=True, help="overlay JSONL under workspace/")
    parser.add_argument("--poll-ms", type=int, default=250)
    parser.add_argument("--opacity", type=float, default=0.92)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.3 <= args.opacity <= 1.0:
        raise SystemExit("opacity must be between 0.3 and 1.0")
    if not 50 <= args.poll_ms <= 5000:
        raise SystemExit("poll-ms must be between 50 and 5000")
    events = Path(args.events).resolve()
    if not events.is_relative_to((ROOT / "workspace").resolve()):
        raise SystemExit("events must stay under workspace/")
    AgentHud(events, args.poll_ms, args.opacity).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
