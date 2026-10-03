from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from harness.windows_live_observation import WindowsLiveObservationProvider, LiveObservationError
from harness.mission_runtime import MissionContext
from harness.observation_bridge import CandidateSpec
from harness import windows_live_observation as live_module


def test_the_default_backend_calls_windows_ocr_without_leaving_the_process(tmp_path):
    """The PowerShell path cost 1,036 ms to do 73 ms of OCR.

    It spawned a process, reloaded WinRT, then re-hashed and re-decoded a frame
    this process already held. Same engine either way; the in-process call
    measures 93 ms and matches it element for element.
    """
    provider = WindowsLiveObservationProvider(tmp_path)
    assert provider.ocr_backend == "windows_direct"
    assert provider._rapidocr_backend is None
    assert provider._direct_ocr is None, "the engine is built on first use, not eagerly"


def test_the_powershell_path_is_still_selectable_for_replay(tmp_path):
    """Retained for replaying stored evidence, not for live ticks."""
    provider = WindowsLiveObservationProvider(tmp_path, ocr_backend="windows")
    assert provider.ocr_backend == "windows"


def test_rapidocr_fixed_roi_is_explicit_opt_in(tmp_path):
    provider = WindowsLiveObservationProvider(
        tmp_path,
        ocr_backend="rapidocr_fixed_roi_experiment",
    )
    assert provider.ocr_backend == "rapidocr_fixed_roi_experiment"
    assert provider._rapidocr_backend is None


def test_unknown_ocr_backend_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="ocr_backend"):
        WindowsLiveObservationProvider(tmp_path, ocr_backend="free_form")


def test_rapidocr_overlay_is_frame_bound_and_keeps_base_words(tmp_path):
    provider = WindowsLiveObservationProvider(
        tmp_path,
        ocr_backend="rapidocr_fixed_roi_experiment",
    )

    class FakeBackend:
        def recognize_image(self, image, *, frame_id, expected_sha256):
            assert Path(image).name == "frame.png"
            assert frame_id == "frame-1"
            assert expected_sha256 == "sha-1"
            return {
                "image": str(image),
                "image_sha256": "sha-1",
                "frame_id": "frame-1",
                "roi_profile_id": "profile-1",
                "results": [
                    {
                        "rect": [350, 732, 105, 24],
                        "text": "Barbarians",
                        "score": 0.99,
                        "confidence_known": True,
                        "frame_id": "frame-1",
                        "image_sha256": "sha-1",
                    }
                ],
            }

    provider._rapidocr_backend = FakeBackend()
    image = tmp_path / "frame.png"
    image.write_bytes(b"not decoded; fake backend does not read it")
    capture = {"frame": {"id": "frame-1", "image_sha256": "sha-1"}}
    original = {
        "schema_version": 1,
        "frame_id": "frame-1",
        "image_sha256": "sha-1",
        "elements": [
            {"text": "SEARCH", "bbox": [500, 590, 66, 13]},
            {"text": "old", "bbox": [350, 732, 105, 24]},
        ],
    }
    overlay = provider._overlay_rapidocr(capture, image, original)
    assert overlay["backend"]["name"] == "Windows.Media.Ocr+RapidOCR.fixed_roi"
    assert overlay["rapidocr_overlay"]["capture_binding_verified"] is True
    assert [item["text"] for item in overlay["elements"]] == ["SEARCH", "Barbarians"]


@pytest.fixture
def offline_provider(tmp_path, monkeypatch):
    """Only acquisition is mocked; canonical hash/age/geometry projection runs."""
    provider = WindowsLiveObservationProvider(tmp_path, candidates=(CandidateSpec("CLAIM", ("Claim",), 0.9),))
    captures = []

    class FakeCaptureError(RuntimeError):
        pass

    def capture(image, *, timeout_seconds):
        captures.append(image)
        image.write_bytes(f"offline-frame-{len(captures)}".encode())
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        return {
            "schema_version": 1, "status": "captured", "backend": {"name": "offline-fixture", "version": "1"},
            "target": {"title": "Rise of Kingdoms", "exe": "MASS.exe", "hwnd": 123, "pid": 456},
            "frame": {"id": f"frame-{len(captures)}", "captured_at": datetime.now(timezone.utc).isoformat(),
                      "width": 800, "height": 600, "client_bounds": [0, 0, 800, 600],
                      "dpi_scale": 1.0, "image_sha256": digest},
            "post_capture": {"client_screen_rect": [10, 20, 810, 620]}, "png": str(image),
        }

    def recognize(capture, image):
        assert image == Path(capture["png"])
        assert image.read_bytes()
        return {
            "schema_version": 1, "frame_id": capture["frame"]["id"],
            "image_sha256": capture["frame"]["image_sha256"],
            "coordinate_space": "ocr_crop_pixels", "output_coordinate_space": "client_pixels",
            "client_bounds": [0, 0, 800, 600], "dpi_scale": 1.0,
            "backend": {"name": "offline-fixture", "version": "1"}, "crop": [0, 0, 800, 600],
            "scale_x": 1.0, "scale_y": 1.0, "text": "Claim",
            "elements": [{"text": "Claim", "bbox": [20, 30, 100, 40], "confidence": 0.97}],
        }

    monkeypatch.setitem(sys.modules, "harness.windows_capture_backend", SimpleNamespace(
        WindowsCaptureError=FakeCaptureError, capture_rok_client=capture,
    ))
    monkeypatch.setattr(provider, "_recognize_in_process", recognize)
    return provider, captures, MissionContext("GATHER_RESOURCE", "offline-task", "offline-run")


def test_observations_publish_distinct_exact_frame_artifacts_without_overwriting(offline_provider, monkeypatch):
    provider, captures, context = offline_provider
    run_dir = provider._run_dir(context)
    run_dir.mkdir(parents=True)
    legacy = run_dir / "ocr.json"
    legacy.write_bytes(b"preserved legacy OCR")
    first = provider.observe(context)
    first_image = Path(first.scene.facts["image_path"])
    old_files = [legacy, *first_image.parent.iterdir()]
    old_bytes = {path: path.read_bytes() for path in old_files}
    original_replace = Path.replace
    replacements = []

    def deny_old_destination(source, target):
        target = Path(target)
        replacements.append(target)
        if target in old_files:
            raise PermissionError(5, "old destination held open")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", deny_old_destination)
    # A held old OCR destination and deterministic replacement denial ensure
    # isolation, without depending on platform file-sharing behavior.
    with (first_image.parent / "ocr.json").open("rb"):
        second = provider.observe(context)
    second_image = Path(second.scene.facts["image_path"])
    assert first_image.parent != second_image.parent
    assert first_image.parent.parent == second_image.parent.parent == run_dir
    assert first_image.parent.name.startswith("observation-")
    assert len(captures) == 2 and captures == [first_image, second_image]
    assert old_bytes == {path: path.read_bytes() for path in old_files}
    assert len(replacements) == 3 and all(path.parent == second_image.parent for path in replacements)
    for bundle, image in ((first, first_image), (second, second_image)):
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        metadata = json.loads((image.parent / "capture.json").read_text())
        projection = json.loads((image.parent / "projection.json").read_text())
        assert metadata["png"] == str(image)
        assert metadata["frame"]["image_sha256"] == bundle.scene.facts["image_sha256"] == digest
        assert metadata["frame"]["id"] == bundle.observation.frame_id
        assert projection["scene_facts"]["image_path"] == str(image)
        assert bundle.scene.facts["image_path_source"] == "current_capture_artifact"
        assert bundle.scene.facts["client_screen_rect"] == [10, 20, 810, 620]
        assert bundle.scene.require_target("CLAIM", 0.9).metadata["image_sha256"] == digest


def test_exclusive_directory_collision_fails_once_before_capture(offline_provider, monkeypatch):
    provider, captures, context = offline_provider
    occupied = provider._run_dir(context) / "observation-fixed"
    occupied.mkdir(parents=True)
    marker = occupied / "current.png"
    marker.write_bytes(b"older immutable frame")
    allocations = []

    def one_id():
        allocations.append("fixed")
        return SimpleNamespace(hex="fixed")

    monkeypatch.setattr(live_module, "uuid4", one_id)
    with pytest.raises(LiveObservationError):
        provider.observe(context)
    assert allocations == ["fixed"] and captures == []
    assert marker.read_bytes() == b"older immutable frame"
    assert provider._previous_timestamp is None


@pytest.mark.parametrize("stage", ["capture.json", "ocr.json", "projection.json"])
def test_publication_failure_returns_no_bundle_and_preserves_prior_observation(offline_provider, monkeypatch, stage):
    provider, captures, context = offline_provider
    first = provider.observe(context)
    image = Path(first.scene.facts["image_path"])
    previous = provider._previous_timestamp
    old_bytes = {path: path.read_bytes() for path in image.parent.iterdir()}
    original_write = provider._write_json
    failures = []

    def deny(path, value):
        if path.name == stage:
            failures.append(path)
            raise PermissionError(5, f"publication denied: {stage}")
        original_write(path, value)

    monkeypatch.setattr(provider, "_write_json", deny)
    with pytest.raises(LiveObservationError, match="publication denied"):
        provider.observe(context)
    assert len(failures) == 1 and len(captures) == 2
    assert provider._previous_timestamp == previous
    assert old_bytes == {path: path.read_bytes() for path in old_bytes}
    assert not failures[0].exists()


def test_cross_frame_ocr_still_fails_closed_without_bundle(offline_provider, monkeypatch):
    provider, captures, context = offline_provider
    original = provider._recognize_in_process

    def wrong_frame(capture, image):
        result = original(capture, image)
        result["frame_id"] = "foreign-frame"
        return result

    monkeypatch.setattr(provider, "_recognize_in_process", wrong_frame)
    with pytest.raises(LiveObservationError, match="frame id/hash"):
        provider.observe(context)
    assert len(captures) == 1 and provider._previous_timestamp is None
    assert not (captures[0].parent / "projection.json").exists()


def test_capture_failure_never_reaches_ocr_or_returns_bundle(offline_provider, monkeypatch):
    provider, captures, context = offline_provider
    backend = sys.modules["harness.windows_capture_backend"]
    attempts = []

    def fail_capture(image, **kwargs):
        attempts.append(image)
        raise backend.WindowsCaptureError("native capture unavailable")

    monkeypatch.setattr(backend, "capture_rok_client", fail_capture)
    monkeypatch.setattr(provider, "_recognize_in_process", lambda *_: pytest.fail("OCR after capture failure"))
    with pytest.raises(LiveObservationError, match="native capture unavailable"):
        provider.observe(context)
    assert len(attempts) == 1 and captures == []
    assert list(attempts[0].parent.iterdir()) == []
    assert provider._previous_timestamp is None
