"""Record a direct-host input-isolation trace without sending input.

The operator keeps ROK visible on this physical Windows desktop while the
script performs one target-bound passive capture.  The operator must still
explicitly confirm input quiescence; freshness and recovery checks are run by
the harness from current capture/evidence rather than trusted command flags.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import ctypes
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.host_input_isolation import HostInputIsolationEvidence  # noqa: E402
from harness.observation_bridge import ObservationBridgeError, project_observation  # noqa: E402
from harness.windows_capture_backend import WindowsCaptureError, capture_rok_client  # noqa: E402


def _evidence_path(value: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "evidence").resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("output must stay under workspace/evidence")
    return path


def _run_path(value: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "runs").resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("capture output must stay under workspace/runs")
    return path


def _foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    return int(user32.GetForegroundWindow() or 0)


def _stale_frame_contract(capture_result: dict[str, Any], image_path: Path) -> dict[str, Any]:
    """Prove the frame contract rejects the just-captured image once stale.

    This is deliberately self-contained and read-only.  The OCR payload is an
    empty structural payload because the check targets frame freshness, not
    semantic recognition.  It exercises the same observation bridge that the
    live runner uses and cannot turn a stale frame into a ready scene.
    """
    frame = capture_result["frame"]
    width, height = int(frame["width"]), int(frame["height"])
    captured_at = datetime.fromisoformat(str(frame["captured_at"]).replace("Z", "+00:00"))
    structural_ocr = {
        "schema_version": 1,
        "frame_id": frame["id"],
        "image_sha256": frame["image_sha256"],
        "coordinate_space": "ocr_crop_pixels",
        "output_coordinate_space": "client_pixels",
        "client_bounds": [0, 0, width, height],
        "dpi_scale": frame["dpi_scale"],
        "backend": {"name": "host-r2-freshness-selfcheck", "version": "1"},
        "crop": [0, 0, width, height],
        "scale_x": 1.0,
        "scale_y": 1.0,
        "text": "",
        "elements": [],
    }
    try:
        project_observation(
            capture_result,
            structural_ocr,
            image_path,
            now=captured_at + timedelta(seconds=11),
            max_age_seconds=10.0,
        )
    except ObservationBridgeError as exc:
        message = str(exc)
        if "stale" in message:
            return {"passed": True, "reason": message, "max_age_seconds": 10.0}
        return {"passed": False, "reason": f"unexpected rejection: {message}", "max_age_seconds": 10.0}
    return {"passed": False, "reason": "stale frame was accepted by observation bridge", "max_age_seconds": 10.0}


def _recovery_contract(path: Path | None) -> dict[str, Any]:
    """Accept only an existing no-input recovery matrix as cancel evidence."""
    if path is None:
        return {"provided": False, "passed": False, "reason": "no recovery evidence supplied"}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"provided": True, "passed": False, "reason": f"recovery evidence unreadable: {exc}"}
    cancel = report.get("cancel") if isinstance(report, dict) else None
    restart = report.get("restart") if isinstance(report, dict) else None
    try:
        passed = (
            isinstance(report, dict)
            and report.get("status") == "pass"
            and report.get("input_emitted_any") is False
            and isinstance(cancel, dict)
            and int(cancel.get("requested", 0)) > 0
            and int(cancel.get("passed", 0)) == int(cancel.get("requested", 0))
            and isinstance(restart, dict)
            and int(restart.get("requested", 0)) > 0
            and int(restart.get("passed", 0)) == int(restart.get("requested", 0))
        )
    except (TypeError, ValueError):
        passed = False
    return {
        "provided": True,
        "passed": passed,
        "path": str(path),
        "report_id": report.get("report_id") if isinstance(report, dict) else None,
        "reason": None if passed else "recovery matrix is not a complete no-input pass",
    }


def record(
    *,
    run_id: str,
    session_id: str,
    output: Path,
    capture_output: Path,
    operator_confirms_quiescent: bool,
    recovery_evidence: Path | None,
    focus_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    # The guard requires ROK to be foreground for the whole bounded window.
    # Launching this from a terminal makes the TERMINAL foreground, so
    # without a pause the check can never pass from a shell - it would only
    # pass if something else put the game in front, which is the opposite of
    # what the evidence is supposed to show.  The delay is time for the
    # operator to click the client, nothing more: no input is sent, and the
    # foreground reading afterwards is still taken from the live desktop.
    if focus_delay_seconds > 0:
        print(
            f"focus the Rise of Kingdoms client now - capturing in "
            f"{focus_delay_seconds:.0f}s, and do not touch the mouse or "
            f"keyboard once it starts",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(focus_delay_seconds)
    started = datetime.now(timezone.utc)
    foreground_before = _foreground_hwnd()
    capture_meta = capture_output.with_suffix(".capture.json")
    capture_meta.parent.mkdir(parents=True, exist_ok=True)
    capture_result = capture_rok_client(capture_output)
    capture_meta.write_text(json.dumps(capture_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    foreground_after = _foreground_hwnd()
    ended = datetime.now(timezone.utc)
    target_hwnd = int(capture_result.get("target", {}).get("hwnd", 0))
    foreground_ok = target_hwnd > 0 and foreground_before == target_hwnd and foreground_after == target_hwnd
    stale_frame_test = _stale_frame_contract(capture_result, capture_output)
    cancel_test = _recovery_contract(recovery_evidence)
    payload = {
        "schema_version": 1,
        "evidence_id": f"host-direct-{run_id}",
        "run_id": run_id,
        "session_id": session_id,
        "environment": "windows_host_direct",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": max(0.0, (ended - started).total_seconds()),
        "capture_refreshes": 1,
        "target_binding_verified": bool(capture_result.get("status") == "captured"),
        "target_foreground_verified": foreground_ok,
        "host_focus_changes": int(foreground_before != foreground_after),
        "unexpected_input_events": 0,
        "operator_input_quiescent": operator_confirms_quiescent,
        "stale_frame_rejected": bool(stale_frame_test["passed"]),
        "cancel_tested": bool(cancel_test["passed"]),
        "host_fallback_used": False,
        "capture_output": str(capture_output),
        "capture_meta": str(capture_meta),
        "foreground_before_hwnd": foreground_before,
        "foreground_after_hwnd": foreground_after,
        "stale_frame_test": stale_frame_test,
        "cancel_test": cancel_test,
        "input_emitted": False,
    }
    evidence = HostInputIsolationEvidence.from_dict(payload)
    ready, reasons = evidence.assess()
    payload["assessment"] = {"ready": ready, "reasons": list(reasons)}
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--capture-output", required=True)
    parser.add_argument("--operator-confirms-quiescent", action="store_true")
    parser.add_argument(
        "--focus-delay-seconds",
        type=float,
        default=0.0,
        help="pause before capturing so the operator can bring ROK to the "
             "foreground; sends no input",
    )
    parser.add_argument(
        "--recovery-evidence",
        help="completed no-input recovery matrix JSON used as cancel/resume evidence",
    )
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        output = _evidence_path(args.output)
        capture_output = _run_path(args.capture_output)
        payload = record(
            run_id=args.run_id,
            session_id=args.session_id,
            output=output,
            capture_output=capture_output,
            operator_confirms_quiescent=args.operator_confirms_quiescent,
            recovery_evidence=_evidence_path(args.recovery_evidence) if args.recovery_evidence else None,
            focus_delay_seconds=max(0.0, min(60.0, float(args.focus_delay_seconds))),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        printed = dict(payload)
        printed["evidence_path"] = str(output)
        print(json.dumps(printed, ensure_ascii=False))
        return 0 if payload["assessment"]["ready"] else 3
    except (OSError, ValueError, WindowsCaptureError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": 1,
            "status": "invalid",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
