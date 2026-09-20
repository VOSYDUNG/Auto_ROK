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
        ocr_backend: str = "windows_direct",
        timeout_seconds: float = 10.0,
        max_age_seconds: float = 30.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.candidates = tuple(candidates)
        self.powershell = powershell
        self.ocr_script = Path(ocr_script).resolve() if ocr_script else Path(__file__).resolve().parents[1] / "scripts" / "windows_ocr.ps1"
        if ocr_backend not in {
            "windows_direct",
            "windows",
            "rapidocr_fixed_roi_experiment",
        }:
            raise ValueError(
                "ocr_backend must be 'windows_direct', 'windows' or "
                "'rapidocr_fixed_roi_experiment'"
            )
        self.ocr_backend = ocr_backend
        #: Created on first use and reused; building the engine costs about
        #: 7 ms and the PowerShell path had to pay it on every frame because
        #: the process died each time.
        self._direct_ocr = None
        self._rapidocr_backend = None
        self.timeout_seconds = timeout_seconds
        self.max_age_seconds = max_age_seconds
        self._previous_timestamp: float | None = None

    def _recognize_in_process(self, capture, image):
        """OCR without leaving this process.

        The capture backend already holds the pixels and has already hashed
        them, so the PowerShell path was re-reading, re-hashing and re-decoding
        a frame we had in hand: 73 ms of real OCR inside 1,036 ms of overhead.
        """
        from harness.windows_ocr_direct import (  # noqa: PLC0415
            WindowsOcr,
            WindowsOcrError,
            recognize_with_regions,
        )

        try:
            if self._direct_ocr is None:
                self._direct_ocr = WindowsOcr()
            # Whole frame PLUS the calibrated regions the state machine turns
            # on.  The sweep alone is not dependable on this client - it
            # returned 3 elements on a city frame against 75 on a world one,
            # and it caught the dispatch drawer on some ticks and not others.
            # The regions cost about 110 ms together and make those strings
            # deterministic.
            return recognize_with_regions(image, capture, engine=self._direct_ocr)
        except WindowsOcrError as exc:
            raise LiveObservationError(str(exc)) from exc

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
            if self.ocr_backend == "windows_direct":
                ocr = self._recognize_in_process(capture, image)
            else:
                # The PowerShell path is retained for replaying stored
                # evidence and for comparison, not for live ticks.  It writes
                # stdout in CP437, so the encoding is stated rather than left
                # to the machine locale - reading it as the locale default
                # silently turned "æ" into a left quote.
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
                    timeout=30,
                    check=False,
                )
                if completed.returncode != 0:
                    raise LiveObservationError(
                        completed.stderr.decode("cp437", errors="replace").strip()
                        or f"Windows OCR exited {completed.returncode}"
                    )
                ocr = json.loads(
                    completed.stdout.decode("cp437"), strict=False
                )
            if self.ocr_backend == "rapidocr_fixed_roi_experiment":
                ocr = self._overlay_rapidocr(capture, image, ocr)
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

    def _overlay_rapidocr(self, capture: dict, image: Path, original: object) -> object:
        """Apply the optional fixed-ROI backend without changing default OCR."""
        try:
            from harness.rapidocr_fixed_roi import (
                RapidOcrFixedRoiBackend,
                RapidOcrFixedRoiError,
                overlay_ocr_payload,
            )
            if self._rapidocr_backend is None:
                self._rapidocr_backend = RapidOcrFixedRoiBackend()
            frame = capture.get("frame", {})
            report = self._rapidocr_backend.recognize_image(
                image,
                frame_id=frame.get("id"),
                expected_sha256=frame.get("image_sha256"),
            )
            report["capture_binding_verified"] = True
            if not isinstance(original, dict):
                raise LiveObservationError("Windows OCR result is not a JSON object")
            return overlay_ocr_payload(original, report)
        except LiveObservationError:
            raise
        except Exception as exc:
            # Keep the optional path fail-closed; the default Windows OCR path
            # is never silently replaced after a backend failure.
            raise LiveObservationError(f"RapidOCR fixed-ROI backend failed: {exc}") from exc

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
