"""Bind a delegated GATHER job to the client from its first captured frame."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Mapping

from harness.gather_job_authority import GatherJobAuthority
from harness.gather_job_store import GatherJobStoreError, JsonGatherJobStore
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider


class GatherClientBindingObservationProvider:
    """Check the capture artifact before policy can expose job actions."""

    def __init__(self, inner: ObservationProvider, job: GatherJobAuthority,
                 ledger: JsonGatherJobStore) -> None:
        self.inner = inner
        self.job = job
        self.ledger = ledger

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        facts = bundle.scene.facts
        frame_id = bundle.observation.frame_id
        image_path = facts.get("image_path")
        if (not frame_id or frame_id != bundle.scene.frame_id
                or facts.get("image_path_source") != "current_capture_artifact"
                or not isinstance(image_path, str) or not image_path):
            raise GatherJobStoreError("GATHER client capture provenance is missing")
        try:
            capture = json.loads((Path(image_path).parent / "capture.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise GatherJobStoreError("GATHER client capture artifact is unavailable") from exc
        target = capture.get("target") if isinstance(capture, dict) else None
        frame = capture.get("frame") if isinstance(capture, dict) else None
        post = capture.get("post_capture") if isinstance(capture, dict) else None
        window = facts.get("window")
        if (not isinstance(target, dict) or not isinstance(frame, dict)
                or not isinstance(post, dict) or not isinstance(window, Mapping)
                or capture.get("png") != image_path
                or frame.get("id") != frame_id
                or frame.get("image_sha256") != facts.get("image_sha256")
                or any(target.get(key) != window.get(key)
                       for key in ("hwnd", "pid", "title", "exe"))
                or any(target.get(key) != post.get(key)
                       for key in ("hwnd", "pid", "process_path"))
                or target.get("title") != "Rise of Kingdoms"
                or str(target.get("exe", "")).casefold() != "mass.exe"):
            raise GatherJobStoreError("GATHER client capture identity is inconsistent")
        bound_window = dict(window)
        bound_window["process_path"] = target.get("process_path")
        self.ledger.bind_client(self.job, bound_window)
        updated = dict(facts)
        updated["window"] = bound_window
        updated["gather_client_binding_source"] = "same_frame_capture_target_and_post_capture"
        return ObservationBundle(bundle.observation, replace(bundle.scene, facts=updated))
