import json
from datetime import datetime, timedelta, timezone

import pytest

from harness.contracts import Observation
from harness.gather_client_binding import GatherClientBindingObservationProvider
from harness.gather_job_authority import GatherJobAuthority
from harness.gather_job_store import GatherJobStoreError, JsonGatherJobStore
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph


NOW = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
CONTEXT = MissionContext("GATHER_RESOURCE", "task-1", "run-1")
WINDOW = {"hwnd": 1001, "pid": 2001, "title": "Rise of Kingdoms",
          "exe": "MASS.exe", "process_path": r"C:\Game\MASS.exe"}


def job():
    return GatherJobAuthority("job-1", "task-1", "character-1", "digest",
                              NOW - timedelta(minutes=1), NOW + timedelta(minutes=20),
                              frozenset({"MARCH_WITH_CURRENT_SELECTION"}))


def frame(tmp_path, frame_id, window=WINDOW, *, omit_path=False, corrupt_frame=False):
    run_dir = tmp_path / frame_id
    run_dir.mkdir()
    image = run_dir / "current.png"
    captured = dict(window)
    if omit_path:
        captured.pop("process_path")
    (run_dir / "capture.json").write_text(json.dumps({
        "target": captured, "post_capture": captured,
        "frame": {"id": "different" if corrupt_frame else frame_id,
                  "image_sha256": "a" * 64},
        "png": str(image),
    }), encoding="utf-8")
    facts = {"window": {key: captured[key] for key in ("hwnd", "pid", "title", "exe")},
             "image_path": str(image), "image_path_source": "current_capture_artifact",
             "image_sha256": "a" * 64}
    return ObservationBundle(
        Observation(NOW.timestamp(), frame_id, (1280, 720), ()),
        SceneGraph(frame_id, None, (), facts),
    )


class Frames:
    def __init__(self, *bundles):
        self.bundles = iter(bundles)

    def observe(self, context):
        return next(self.bundles)


def test_first_capture_binds_and_restart_keeps_client(tmp_path):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    first = GatherClientBindingObservationProvider(
        Frames(frame(tmp_path, "frame-1")), job(), ledger).observe(CONTEXT)
    assert first.scene.facts["window"]["process_path"] == WINDOW["process_path"]
    assert first.scene.facts["gather_client_binding_source"] == "same_frame_capture_target_and_post_capture"
    reopened = JsonGatherJobStore(tmp_path / "ledger")
    second = GatherClientBindingObservationProvider(
        Frames(frame(tmp_path, "frame-2")), job(), reopened).observe(CONTEXT)
    assert second.scene.facts["window"]["hwnd"] == 1001
    assert reopened.client_binding(job()).hwnd == 1001
    assert reopened.progress(job()).dispatched_marches == 0


@pytest.mark.parametrize("change", [
    {"hwnd": 9999}, {"pid": 9999}, {"process_path": r"C:\Other\MASS.exe"},
])
def test_replacement_client_is_denied_without_reservation(tmp_path, change):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    ledger.bind_client(job(), WINDOW)
    replacement = WINDOW | change
    provider = GatherClientBindingObservationProvider(
        Frames(frame(tmp_path, "replacement", replacement)), job(), ledger)
    with pytest.raises(GatherJobStoreError, match="binding changed"):
        provider.observe(CONTEXT)
    assert ledger.client_binding(job()).hwnd == WINDOW["hwnd"]
    assert ledger.progress(job()).dispatched_marches == 0


@pytest.mark.parametrize("options", [{"omit_path": True}, {"corrupt_frame": True}])
def test_missing_or_inconsistent_identity_never_binds(tmp_path, options):
    ledger = JsonGatherJobStore(tmp_path / "ledger")
    provider = GatherClientBindingObservationProvider(
        Frames(frame(tmp_path, "invalid", **options)), job(), ledger)
    with pytest.raises(GatherJobStoreError):
        provider.observe(CONTEXT)
    assert ledger.client_binding(job()) is None
    assert ledger.progress(job()).dispatched_marches == 0
