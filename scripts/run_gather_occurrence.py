"""Drive one whole gather occurrence: record isolation, then tick to a march.

``run_gather_tick.py`` executes ONE transition. A gather run is about a dozen
of them, so reaching the operator's acceptance target - one character's march
queue at 5/5 - was sixty-odd hand-typed commands. This is that loop.

Two things learned on the first live run are baked in here, because both cost
real time to find:

``run_id`` is the mission OCCURRENCE, not the tick. The selector tracks which
self-loop setup transitions it has already verified, keyed on run_id, and the
search panel has three transitions leaving the same state - pick the resource
type, set the level, press search. Give each tick a fresh run_id and it
re-runs the first one forever, because nothing remembers the category was
already chosen. One run_id, many ticks.

The host input-isolation trace is bound to that same run_id, so it is recorded
once per occurrence rather than once per tick.

This script sends real input. It refuses to start unless the isolation trace
comes back ready, which requires the client in the foreground and the operator
stating they are off the mouse and keyboard.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Transitions in the compiled gather flow, plus room for the reobserve ticks
#: that happen while the client is mid-animation. Bounded so a flow that
#: stalls stops rather than pressing forever.
DEFAULT_MAX_TICKS = 24

#: Terminal-ish statuses that mean this occurrence has nothing left to do.
DONE_STATUSES = {"completed", "blocked", "failed"}


def _focus_client() -> bool:
    """Bring the client forward without sending it any input."""
    from harness.windows_capture_backend import discover_rok_window

    target = discover_rok_window()
    hwnd = int(target["hwnd"])
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    return int(user32.GetForegroundWindow() or 0) == hwnd


def _read_queue() -> str:
    """Current march queue, or why it could not be read."""
    import cv2

    from harness.queue_indicator import QueueIndicatorProfile, QueueIndicatorReader
    from harness.windows_capture_backend import capture_rok_client

    frame = ROOT / "workspace" / "runs" / "queue-probe" / "frame.png"
    frame.parent.mkdir(parents=True, exist_ok=True)
    capture_rok_client(frame)
    profile = QueueIndicatorProfile.load(ROOT / "config" / "queue_indicator_profile.json")
    reading = QueueIndicatorReader(profile).read(
        cv2.cvtColor(cv2.imread(str(frame)), cv2.COLOR_BGR2GRAY)
    )
    if reading.status.value != "READ":
        return f"{reading.status.value} ({reading.reason[:60]})"
    return f"{reading.used}/{reading.capacity}"


def _run(command: list[str]) -> dict:
    """Run one harness command and return its last JSON line."""
    completed = subprocess.run(
        [sys.executable, *command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    merged = (completed.stdout or "") + "\n" + (completed.stderr or "")
    for line in reversed(merged.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    return {"status": "failed", "error": {"message": merged.strip()[-300:]}}


def record_isolation(run_id: str, session_id: str, *, focus_delay: float) -> dict:
    output = f"workspace/evidence/input_isolation/{run_id}.json"
    return _run(
        [
            "scripts/record_host_input_isolation.py",
            "--run-id", run_id,
            "--session-id", session_id,
            "--output", output,
            "--capture-output", f"workspace/runs/{run_id}-iso",
            "--recovery-evidence", "workspace/evidence/recovery/m7-recovery-01.json",
            "--operator-confirms-quiescent",
            "--focus-delay-seconds", str(focus_delay),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="the mission occurrence id")
    parser.add_argument("--session-id", default="m7-live")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", required=True,
                        choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int, default=6)
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    parser.add_argument("--focus-delay-seconds", type=float, default=2.0)
    parser.add_argument(
        "--approve-current-troop-selection",
        action="store_true",
        help="approve whatever troop/commander selection the client shows for "
             "this occurrence; without it the run stops at the march step",
    )
    args = parser.parse_args(argv)

    print(f"queue before: {_read_queue()}", flush=True)

    if not _focus_client():
        print("the client did not come to the foreground; nothing was sent", file=sys.stderr)
        return 2

    isolation = record_isolation(
        args.run_id, args.session_id, focus_delay=args.focus_delay_seconds
    )
    ready = bool(isolation.get("assessment", {}).get("ready"))
    if not ready:
        reasons = isolation.get("assessment", {}).get("reasons", [])
        print("input isolation is not ready; nothing was sent:", file=sys.stderr)
        for reason in reasons or [isolation.get("error", {}).get("message", "unknown")]:
            print(f"  - {reason}", file=sys.stderr)
        return 3

    tick_command = [
        "scripts/run_gather_tick.py",
        "--run-id", args.run_id,
        "--character-id", args.character_id,
        "--resource-type", args.resource_type,
        "--resource-level", str(args.resource_level),
        "--input-isolation-evidence",
        f"workspace/evidence/input_isolation/{args.run_id}.json",
        "--arm-live",
    ]
    if args.approve_current_troop_selection:
        tick_command.append("--approve-current-troop-selection")

    last: dict = {}
    for tick in range(1, args.max_ticks + 1):
        last = _run(tick_command)
        choice = last.get("choice") or {}
        print(
            f"  tick {tick:>2} rev={last.get('checkpoint_revision')} "
            f"{str(last.get('status')):<13} {str(last.get('state')):<24} "
            f"-> {choice.get('action_id') or '-'} "
            f"{str(last.get('reason') or (last.get('error') or {}).get('message', ''))[:52]}",
            flush=True,
        )
        if last.get("status") in DONE_STATUSES:
            break
        if last.get("status") == "needs_decision":
            # A decision the operator owns. Stopping is the point, so say so
            # plainly rather than burning the remaining ticks on it.
            print("  stopped: this step needs an operator decision", flush=True)
            break

    print(f"queue after : {_read_queue()}", flush=True)
    return 0 if last.get("status") not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
