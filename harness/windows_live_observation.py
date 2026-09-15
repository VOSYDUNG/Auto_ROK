"""Live Windows capture + OCR ObservationProvider for the bounded mission tool."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Sequence

from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.observation_bridge import CandidateSpec, ObservationBridgeError, project_observation


class LiveObservationError(RuntimeError):
    pass


class WindowsLiveObservationProvider:
    """Capture one current ROK frame, OCR it, and return frame-bound contracts.

    Acquisition is passive: this provider never activates the game window and
    never emits mouse or keyboard input.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        candidates: Sequence[CandidateSpec] = (),
        powershell: str = "powershell.exe",
        ocr_script: str | Path | None = None,
        timeout_seconds: float = 10.0,
        max_age_seconds: float = 30.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.candidates = tuple(candidates)
        self.powershell = powershell
        self.ocr_script = Path(ocr_script).resolve() if ocr_script else Path(__file__).resolve().parents[1] / "scripts" / "windows_ocr.ps1"
        self.timeout_seconds = timeout_seconds
        self.max_age_seconds = max_age_seconds
        self._previous_timestamp: float | None = None

    def observe(self, context: MissionContext) -> ObservationBundle:
        # Import lazily so non-Windows CI can import this module.
        try:
            from harness.windows_capture_backend import WindowsCaptureError, capture_rok_client
        except Exception as exc:  # pragma: no cover - platform dependent
            raise LiveObservationError(f"Windows capture backend unavailable: {exc}") from exc

        run_dir = self._run_dir(context)
        run_dir.mkdir(parents=True, exist_ok=True)
        image = run_dir / "current.png"
        capture_path = run_dir / "capture.json"
        ocr_path = run_dir / "ocr.json"
        projection_path = run_dir / "projection.json"

        try:
            capture = capture_rok_client(image, timeout_seconds=self.timeout_seconds)
            self._write_json(capture_path, capture)
            completed = subprocess.run(
                [
                    self.powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.ocr_script),
                    "-Image",
                    str(image),
                    "-CaptureMeta",
                    str(capture_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode != 0:
                raise LiveObservationError(
                    completed.stderr.strip() or f"Windows OCR exited {completed.returncode}"
                )
            ocr = json.loads(completed.stdout, strict=False)
            self._write_json(ocr_path, ocr)
            projected = project_observation(
                capture,
                ocr,
                image,
                self.candidates,
                now=datetime.now(timezone.utc),
                max_age_seconds=self.max_age_seconds,
                previous_timestamp=self._previous_timestamp,
            )
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ObservationBridgeError, WindowsCaptureError) as exc:
            raise LiveObservationError(str(exc)) from exc

        if projected.observation is None or projected.scene is None:
            raise LiveObservationError("projection returned no observation/scene")

        # Preserve current-frame artifact and client->screen geometry captured by
        # the passive backend.  Visual detectors may read only this frame path;
        # it is execution provenance, not persistent game-state memory.
        post = capture.get("post_capture")
        facts = dict(projected.scene.facts)
        facts["image_path"] = str(image)
        facts["image_path_source"] = "current_capture_artifact"
        if isinstance(post, dict):
            rect = post.get("client_screen_rect")
            if (
                isinstance(rect, list)
                and len(rect) == 4
                and all(type(item) is int for item in rect)
                and rect[2] > rect[0]
                and rect[3] > rect[1]
            ):
                facts["client_screen_rect"] = list(rect)
                facts["client_screen_rect_source"] = "capture_post_binding"

        scene = replace(projected.scene, facts=facts)
        self._previous_timestamp = projected.observation.timestamp
        self._write_json(
            projection_path,
            {
                "status": projected.status,
                "reason": projected.reason,
                "frame_id": projected.observation.frame_id,
                "decisions": list(projected.decisions),
                "scene_facts": facts,
            },
        )
        return ObservationBundle(projected.observation, scene)

    def _run_dir(self, context: MissionContext) -> Path:
        identity = "\0".join((context.mission_id, context.task_id, context.run_id))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self.workspace_root / f"{context.mission_id.lower()}-{digest}"

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
