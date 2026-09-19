"""Run one elevated, foreground-gated GATHER occurrence.

This operator helper is intentionally narrow: it never activates ROK and never
tries to bypass UAC.  After the user approves the Windows elevation prompt,
the process waits for the already-open ROK window to be foreground, records a
fresh direct-host trace, and only then invokes the normal guarded runner.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.r3_endurance_authorization import (  # noqa: E402
    R3AuthorizationError,
    authorization_reasons,
    load_json_object,
    manifest_contract,
    reserve_run,
)
from harness.windows_capture_backend import WindowsCaptureError, discover_rok_window  # noqa: E402


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,96}$")


def _foreground_hwnd() -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def _run_id(value: str) -> str:
    if not _RUN_ID.fullmatch(value):
        raise ValueError("run-id must be a bounded ASCII identifier")
    return value


def _wait_for_rok_foreground(timeout_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_target: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            target = discover_rok_window()
        except WindowsCaptureError:
            target = None
        if target is not None:
            last_target = target
            if _foreground_hwnd() == int(target["hwnd"]):
                return target
        time.sleep(0.25)
    target_name = last_target.get("title") if last_target else "ROK"
    raise RuntimeError(f"{target_name} was not foreground within {timeout_seconds:.1f}s")


def _subprocess(command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=_run_id)
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int, default=6)
    parser.add_argument(
        "--approve-current-troop-selection",
        action="store_true",
        help="explicitly approve the currently visible troop selection for this exact occurrence",
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--recovery-evidence", required=True)
    parser.add_argument("--foreground-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--subprocess-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-ticks", type=int, default=1)
    parser.add_argument("--operator-confirms-quiescent", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--r3-endurance-authorization",
        help=(
            "explicit operator authorization for one bounded R3 repetition; "
            "the run is reserved append-only immediately before live dispatch"
        ),
    )
    parser.add_argument(
        "--r3-manifest",
        default=str(ROOT / "config" / "r3_registered_runs.json"),
        help="registered R3 contract used with --r3-endurance-authorization",
    )
    parser.add_argument(
        "--r3-reservation-ledger",
        default=str(ROOT / "workspace" / "evidence" / "gather" / "R3_RUN_RESERVATIONS.jsonl"),
        help="append-only R3 attempt ledger",
    )
    args = parser.parse_args(argv)
    if not args.operator_confirms_quiescent:
        raise SystemExit("refusing to run without --operator-confirms-quiescent")
    if args.resource_level is not None and not 0 <= args.resource_level <= 30:
        raise SystemExit("resource-level must be within [0, 30]")
    if not 1 <= args.max_ticks <= 12:
        raise SystemExit("max-ticks must be within [1, 12]")

    output = Path(args.output).resolve()
    evidence_root = (ROOT / "workspace" / "evidence").resolve()
    if not output.is_relative_to(evidence_root) or output == evidence_root:
        raise SystemExit("output must stay under workspace/evidence")
    if args.r3_endurance_authorization and args.max_ticks != 1:
        raise SystemExit("R3 endurance mode permits exactly one live occurrence per invocation")

    host_trace = evidence_root / "host" / f"{args.run_id}.json"
    capture_output = ROOT / "workspace" / "runs" / args.run_id / "host-isolation" / "rok.png"
    try:
        r3_authorization: dict[str, object] | None = None
        r3_manifest: dict[str, object] | None = None
        r3_authorization_path: Path | None = None
        r3_ledger_path: Path | None = None
        r3_reservation: dict[str, object] | None = None
        if args.r3_endurance_authorization:
            r3_authorization_path = Path(args.r3_endurance_authorization).resolve()
            r3_manifest_path = Path(args.r3_manifest).resolve()
            r3_ledger_path = Path(args.r3_reservation_ledger).resolve()
            for label, path in (
                ("R3 authorization", r3_authorization_path),
                ("R3 reservation ledger", r3_ledger_path),
            ):
                if not path.is_relative_to(evidence_root):
                    raise R3AuthorizationError(f"{label} must stay under workspace/evidence")
            raw_manifest = load_json_object(r3_manifest_path)
            raw_authorization = load_json_object(r3_authorization_path)
            contract, registered, required_runs = manifest_contract(raw_manifest)
            reasons = authorization_reasons(
                raw_authorization,
                required_additional_runs=max(0, required_runs - len(registered)),
                expected_contract=contract,
            )
            if reasons:
                raise R3AuthorizationError("; ".join(reasons))
            r3_manifest = dict(raw_manifest)
            r3_authorization = dict(raw_authorization)

        ticks: list[dict[str, object]] = []
        target: dict[str, object] | None = None
        for tick_index in range(args.max_ticks):
            target = _wait_for_rok_foreground(args.foreground_timeout_seconds)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            host_trace = evidence_root / "host" / f"{args.run_id}-{stamp}-{tick_index:02d}.json"
            capture_output = ROOT / "workspace" / "runs" / args.run_id / "host-isolation" / f"{stamp}-{tick_index:02d}.png"
            trace_command = [
                sys.executable,
                str(ROOT / "scripts" / "record_host_input_isolation.py"),
                "--run-id", args.run_id,
                "--session-id", args.session_id,
                "--output", str(host_trace),
                "--capture-output", str(capture_output),
                "--operator-confirms-quiescent",
                "--recovery-evidence", str(Path(args.recovery_evidence).resolve()),
            ]
            trace = _subprocess(trace_command, timeout_seconds=args.subprocess_timeout_seconds)
            if trace.returncode != 0:
                raise RuntimeError(f"direct-host trace failed: {trace.stdout.strip() or trace.stderr.strip()}")
            trace_payload = json.loads(host_trace.read_text(encoding="utf-8"))
            if trace_payload.get("assessment", {}).get("ready") is not True:
                raise RuntimeError("direct-host trace did not pass its ready assessment")

            if r3_authorization is not None and r3_manifest is not None and r3_ledger_path is not None:
                # Reserve only after passive host preflight succeeds.  A
                # foreground timeout or failed isolation probe therefore does
                # not consume an authorized attempt, while any later live
                # failure remains conservatively counted.
                r3_reservation = reserve_run(
                    r3_authorization,
                    r3_manifest,
                    run_id=args.run_id,
                    ledger_path=r3_ledger_path,
                )

            runner_command = [
                sys.executable,
                str(ROOT / "scripts" / "run_autorok.py"),
                "--run-id", args.run_id,
                "--task-id", args.task_id,
                "--character-id", args.character_id,
                "--resource-type", args.resource_type,
                "--arm-live",
                "--input-isolation-evidence", str(host_trace),
            ]
            if r3_authorization is not None and r3_ledger_path is not None:
                runner_command.extend(("--r3-repetition", "--r3-reservation-ledger", str(r3_ledger_path)))
            if args.resource_level is not None:
                runner_command.extend(("--resource-level", str(args.resource_level)))
            if args.approve_current_troop_selection:
                runner_command.append("--approve-current-troop-selection")
            runner = _subprocess(runner_command, timeout_seconds=args.subprocess_timeout_seconds)
            runner_payload: object = None
            try:
                runner_payload = json.loads(runner.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                runner_payload = {"stdout": runner.stdout, "stderr": runner.stderr}
            ticks.append({
                "tick_index": tick_index,
                "host_trace": str(host_trace),
                "trace_stdout": trace.stdout,
                "runner_returncode": runner.returncode,
                "runner": runner_payload,
                "runner_stderr": runner.stderr,
                "r3_reservation": r3_reservation,
            })
            if not isinstance(runner_payload, dict):
                break
            if runner_payload.get("status") == "running":
                continue
            # A fresh frame can land during the game's panel animation.  A
            # reobserve that is explicitly UNKNOWN_STATE is safe to retry: no
            # new action was selected, so this loop only waits for a stable
            # visible state.  Never auto-retry a known-state action mismatch.
            if (
                runner_payload.get("status") == "reobserve"
                and runner_payload.get("state") == "UNKNOWN_STATE"
            ):
                time.sleep(1.0)
                continue
            break

        payload = {
            "schema_version": 1,
            "status": "completed",
            "elevated_process": True,
            "target": target,
            "run_id": args.run_id,
            "ticks": ticks,
            "input_emitted": False,
            "r3_endurance": {
                "authorization": str(r3_authorization_path) if r3_authorization_path else None,
                "reservation_ledger": str(r3_ledger_path) if r3_ledger_path else None,
                "reservation": r3_reservation,
            } if r3_authorization_path else None,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False))
        return runner.returncode
    except (OSError, ValueError, RuntimeError, R3AuthorizationError, WindowsCaptureError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "elevated_process": True,
            "run_id": args.run_id,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
