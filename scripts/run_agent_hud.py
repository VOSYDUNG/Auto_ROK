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

3. It drew a 68px crosshair over live game UI at every action point.  The
   agent cursor here is a small conical farm hat standing above the target,
   with a 5px dot marking the exact pixel, so the thing being clicked stays
   visible underneath.

Two windows, and each uses exactly ONE transparency mechanism:

    the docked bar     alpha, no colour key
    the agent cursor   colour key, no alpha

Mixing the two is what produced the pink, so the split is deliberate rather
than incidental.

On the agent cursor.  Windows has one physical pointer and SendInput moves it,
so the agent cannot own a second one the way a remote-desktop agent can.  The
marker is better than a second pointer would be anyway: it appears at the
target BEFORE the click, so the operator sees where the agent is going while
there is still time to stop it.  A real cursor only tells you where it went.

It is a nón lá, because the operator calls the accounts "nông dân" and the
marker should speak the same language the business does.  It is also nothing
like an arrow, which is what makes it readable at a glance - and the state
shows in the shape as well as the colour: hollow while targeting, filled once
input is armed.

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

#: The agent cursor: a marker at the point it intends to act on, visible
#: BEFORE the click.  The real pointer cannot give you that - by the time it
#: has moved, the decision is already made.
CURSOR_BOX = 64
#: A conical farm hat.  The operator calls the accounts "nông dân", so the
#: marker wears the same word the business does - and a hat silhouette is
#: unmistakable against an arrow pointer at any size.
HAT_HALF_W = 15
HAT_HEIGHT = 22
#: Gap between the brim and the click point, so the hat never covers the
#: thing it is about to click.
STEM = 9
POINT_R = 2.5

#: Colour-key transparency, and NO alpha.  The HUD bar uses alpha and no key.
#: Each window uses exactly one mechanism - using both together is what made
#: the previous overlay fringe pink.  The key is a near-black the marker never
#: draws, so nothing can be keyed out by accident.
CURSOR_KEY = "#010203"
#: Dark stroke drawn under the marker so it reads on pale grass and on dark
#: city panels alike.  Deliberately not the key colour, which would be keyed
#: out and leave the marker with no contrast at all.
HALO = "#12171d"

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


def read_target_point(payload: dict[str, Any]) -> tuple[float, float] | None:
    """Where the agent intends to act, in screen pixels.

    ``cursor_screen`` wins over ``target_screen`` because it is where the
    pointer will actually land; the target is the element it was grounded to.
    """
    for key in ("cursor_screen", "target_screen"):
        value = payload.get(key)
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ):
            return float(value[0]), float(value[1])
    return None


class AgentCursor:
    """A farm hat standing over the point the agent is about to act on.

    Click-through, and the hat sits above the target rather than on it, so the
    operator can see what is about to be clicked.
    """

    def __init__(self, master: tk.Misc) -> None:
        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", CURSOR_KEY)
        self.window.configure(bg=CURSOR_KEY)
        self.canvas = tk.Canvas(
            self.window, width=CURSOR_BOX, height=CURSOR_BOX,
            highlightthickness=0, bd=0, bg=CURSOR_KEY,
        )
        self.canvas.pack()
        self.visible = False
        self.window.withdraw()
        _set_click_through(self.window)

    def hide(self) -> None:
        if self.visible:
            self.window.withdraw()
            self.visible = False

    def show(self, x: float, y: float, look: Look, *, armed: bool) -> None:
        half = CURSOR_BOX // 2
        left, top = int(round(x)) - half, int(round(y)) - half
        self.window.geometry(f"{CURSOR_BOX}x{CURSOR_BOX}+{left}+{top}")
        if not self.visible:
            self.window.deiconify()
            self.window.attributes("-topmost", True)
            self.visible = True

        self.canvas.delete("all")
        self._draw_hat(half, look.dot, armed=armed)

    def _draw_hat(self, centre: int, colour: str, *, armed: bool) -> None:
        """A nón lá silhouette standing above the click point.

        Everything is anchored on ``centre`` - the window is positioned so
        that pixel sits exactly on the target, so the dot must be drawn there
        and the hat built upward from it.  Anchoring the hat instead would put
        the click a few pixels off, which is the kind of error that only shows
        up as a misclick on a live client.

        Hollow while targeting, filled once armed, so the state reads from the
        shape and not from colour alone.
        """
        cx = centre
        point_y = centre
        brim = point_y - STEM
        top = brim - HAT_HEIGHT
        left, right = cx - HAT_HALF_W, cx + HAT_HALF_W

        # Apex, down the right slope, then back along a brim that sags very
        # slightly in the middle.  An earlier version curved the brim UP and
        # the silhouette read as an umbrella rather than a hat.
        crown = (
            cx, top,
            cx, top,
            cx + 8, top + 11,
            right, brim - 1,
            cx + 8, brim + 2,
            cx, brim + 3,
            cx - 8, brim + 2,
            left, brim - 1,
            cx - 8, top + 11,
            cx, top,
        )
        # A darker stroke underneath, so the marker survives both the pale
        # grass of the world map and the dark panels of the city UI.  Without
        # it the hollow state disappears against anything dim.
        self.canvas.create_polygon(
            crown, fill="", outline=HALO, width=4, smooth=True
        )
        self.canvas.create_polygon(
            crown,
            fill=colour if armed else "",
            outline=colour,
            width=2,
            smooth=True,
        )
        if not armed:
            # Hollow needs an interior line or it reads as an empty blob at
            # this size - this is the ridge from apex to brim.
            self.canvas.create_line(cx, top + 3, cx, brim, fill=colour, width=1)

        self.canvas.create_line(cx, brim + 1, cx, point_y - 4, fill=HALO, width=3)
        self.canvas.create_line(cx, brim + 1, cx, point_y - 4, fill=colour, width=1)
        self.canvas.create_oval(
            cx - POINT_R - 1, point_y - POINT_R - 1,
            cx + POINT_R + 1, point_y + POINT_R + 1,
            fill=HALO, outline="",
        )
        self.canvas.create_oval(
            cx - POINT_R, point_y - POINT_R, cx + POINT_R, point_y + POINT_R,
            fill=colour, outline="",
        )


def _set_click_through(window: tk.Misc) -> None:
    """Mouse events pass through to whatever is underneath."""
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )
    except Exception:
        # A marker that cannot become click-through must at least not steal
        # clicks it is unable to forward.
        try:
            window.attributes("-disabled", True)
        except tk.TclError:
            pass


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
        _set_click_through(self.root)
        self.cursor = AgentCursor(self.root)
        self.target: tuple[float, float] | None = None

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

        self.target = read_target_point(payload)
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
                self.target = None
        self._render()
        self.root.after(self.poll_ms, self._poll)

    def _render(self) -> None:
        look = LOOKS[self.state_key]
        if self.target is None:
            self.cursor.hide()
        else:
            self.cursor.show(*self.target, look, armed=self.state_key == "armed")
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
