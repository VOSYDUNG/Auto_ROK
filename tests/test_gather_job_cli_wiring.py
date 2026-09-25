import json
import hashlib
from dataclasses import replace
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.action_surface import SemanticActionSurface
from harness.gather_job_authority import compiled_gather_catalog
from harness.gather_job_authority import GatherJobProgress
from harness.gather_job_coordinator import GatherJobPlan, GatherJobTick
from harness.gather_job_store import JsonGatherJobStore, load_gather_job_authority
from harness.gather_client_binding import GatherClientBindingObservationProvider
from harness.contracts import BoundingBox, Evidence, Observation
from harness.mission_loader import compile_mission
from harness.mission_runner import MissionTickResult
from harness.mission_store import CheckpointStatus, MissionCheckpoint
from harness.policy_overlay import PolicyEvidenceObservationProvider
from harness.mission_tool import InterferenceCheck, ObservationBundle
from harness.scene_graph import SceneGraph, VisualTarget
from harness.windows_interference_guard import GatherJobInputGuard, WindowsForegroundInterferenceGuard
from scripts import run_gather_tick


ROOT = Path(__file__).resolve().parents[1]
BASE_ARGS = [
    "--run-id", "run-1", "--task-id", "task-1", "--character-id", "character-1",
    "--resource-type", "FOOD", "--resource-level", "5",
]


@pytest.mark.parametrize("fake_status", [CheckpointStatus.WAITING, CheckpointStatus.COMPLETE])
def test_canonical_cli_constructs_job_overlay_and_pre_input_guard_without_game(
    monkeypatch, capsys, fake_status,
):
    monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                        lambda *a, **k: "a" * 64)
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )
    catalog = compiled_gather_catalog(compiled)
    now = datetime.now(timezone.utc)
    seen = {}

    class FakeRunner:
        def __init__(self, compiled, tool, store, **kwargs):
            self.tool = tool
            seen["tool"] = tool
            seen["catalog"] = compiled_gather_catalog(compiled)

        def tick(self, context):
            return MissionTickResult(
                fake_status,
                MissionCheckpoint(context.mission_id, context.task_id, context.run_id, 0,
                                  status=fake_status),
                reason="offline wiring fixture; no observation or input",
            )

    monkeypatch.setattr(run_gather_tick, "MissionRunner", FakeRunner)
    monkeypatch.setattr(run_gather_tick, "WindowsHumanInputActuator", lambda: object())
    monkeypatch.setattr(run_gather_tick, "build_gather_tick_evidence", lambda **kwargs: {"runtime": {}})
    monkeypatch.setattr(
        run_gather_tick, "save_gather_tick_evidence",
        lambda root, record: Path(root) / "offline-wiring.json",
    )
    with TemporaryDirectory(dir=ROOT / "workspace") as folder:
        folder_path = Path(folder)
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", folder_path / "ledger")
        artifact = folder_path / "operator-job.json"
        artifact.write_text(json.dumps({
            "schema_version": 1,
            "job_id": "job-1",
            "task_id": "task-1",
            "character_id": "character-1",
            "catalog_digest": catalog.digest,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
            "allowed_actions": sorted(catalog.actions),
            "max_marches": 5,
            "mission_id": "GATHER_RESOURCE",
        }), encoding="utf-8")
        result = run_gather_tick.main(BASE_ARGS[2:] + ["--gather-job", str(artifact)])
    assert result == (3 if fake_status is CheckpointStatus.WAITING else 4)
    tool = seen["tool"]
    assert isinstance(tool.observations, PolicyEvidenceObservationProvider)
    assert tool.observations.gather_job.job_id == "job-1"
    assert tool.observations.catalog_digest == catalog.digest
    assert tool.observations.job_progress().dispatched_marches == 0
    assert isinstance(tool.observations.inner, GatherClientBindingObservationProvider)
    assert isinstance(tool.actions.guard, GatherJobInputGuard)
    assert isinstance(tool.actions.guard.host_guard, WindowsForegroundInterferenceGuard)
    assert tool.actions.guard.host_guard.armed is False
    assert seen["catalog"] == catalog
    payload = json.loads(capsys.readouterr().out)
    assert payload["gather_job_id"] == "job-1"
    assert payload["startup_attestation_sha256"] == "a" * 64
    assert payload["policy_approved"] is False
    assert payload["gather_job_verified_marches"] == 0
    assert bool(payload["gather_job_verification_error"]) is (
        fake_status is CheckpointStatus.COMPLETE
    )


def test_job_mode_live_arm_is_blocked_before_any_capture(capsys):
    result = run_gather_tick.main(BASE_ARGS + ["--gather-job", "missing.json", "--arm-live"])
    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert "GATHER_JOB_LIVE_ARM_BLOCKED_PENDING_BASELINE_IDENTITY_AND_FIVE_MARCH_PREFLIGHT" in error["error"]["message"]


def test_direct_job_tick_requires_canonical_attestation_before_runner(monkeypatch, capsys):
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )
    catalog = compiled_gather_catalog(compiled)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(run_gather_tick, "MissionRunner",
                        lambda *a, **k: pytest.fail("runner must not start"))
    with TemporaryDirectory(dir=ROOT / "workspace") as folder:
        artifact = Path(folder) / "job.json"
        artifact.write_text(json.dumps({
            "schema_version": 1, "job_id": "direct-missing-record", "task_id": "task-1",
            "character_id": "character-1", "catalog_digest": catalog.digest,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
            "allowed_actions": sorted(catalog.actions), "max_marches": 5,
            "mission_id": "GATHER_RESOURCE",
        }), encoding="utf-8")
        assert run_gather_tick.main(BASE_ARGS[2:] + ["--gather-job", str(artifact)]) == 2
    assert "canonical startup attestation is missing" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["plan", "closeout_write"])
def test_cli_never_reports_closeout_when_validation_or_write_fails(monkeypatch, capsys, failure):
    monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                        lambda *a, **k: "a" * 64)
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )
    catalog = compiled_gather_catalog(compiled)
    now = datetime.now(timezone.utc)
    saved = {}

    class FakeCoordinator:
        def __init__(self, job, ledger, checkpoints):
            self.calls = 0
            self.job = job

        def plan(self):
            self.calls += 1
            if self.calls > 1:
                if failure == "plan":
                    raise ValueError("synthetic closeout validation failure")
                return GatherJobPlan(
                    GatherJobProgress(self.job.job_id, 5, False, 5), None, None, True,
                    tuple({"after_count": n} for n in range(1, 6)),
                )
            return GatherJobPlan(GatherJobProgress(self.job.job_id, 0), "slot-1", 1, False)

        def tick(self, runner):
            checkpoint = MissionCheckpoint(
                "GATHER_RESOURCE", "task-1", "slot-1", 0,
                status=CheckpointStatus.COMPLETE,
            )
            return GatherJobTick(
                self.plan_initial, MissionTickResult(CheckpointStatus.COMPLETE, checkpoint),
                GatherJobProgress(self.job.job_id, 5, False, 5), True, None,
            )

        plan_initial = GatherJobPlan(GatherJobProgress("synthetic-close", 0), "slot-1", 1, False)

    monkeypatch.setattr(run_gather_tick, "GatherJobCoordinator", FakeCoordinator)
    if failure == "closeout_write":
        monkeypatch.setattr(
            run_gather_tick, "persist_gather_job_closeout",
            lambda *a: (_ for _ in ()).throw(OSError("synthetic closeout write failure")),
        )
    monkeypatch.setattr(run_gather_tick, "MissionRunner", lambda *a, **k: object())
    monkeypatch.setattr(run_gather_tick, "WindowsHumanInputActuator", lambda: object())
    monkeypatch.setattr(run_gather_tick, "build_gather_tick_evidence", lambda **kwargs: {"runtime": {}})
    monkeypatch.setattr(run_gather_tick, "save_gather_tick_evidence", lambda root, record: saved.setdefault("record", record) and Path(root) / "synthetic.json")
    with TemporaryDirectory(dir=ROOT / "workspace") as folder:
        folder_path = Path(folder)
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", folder_path / "ledger")
        artifact = folder_path / "job.json"
        artifact.write_text(json.dumps({
            "schema_version": 1, "job_id": "synthetic-close", "task_id": "task-1",
            "character_id": "character-1", "catalog_digest": catalog.digest,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
            "allowed_actions": sorted(catalog.actions), "max_marches": 5,
            "mission_id": "GATHER_RESOURCE",
        }), encoding="utf-8")
        exit_code = run_gather_tick.main(BASE_ARGS[2:] + ["--gather-job", str(artifact)])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 4
    assert payload["gather_job_verified_marches"] == 5
    assert payload["gather_job_closed_at_five"] is False
    assert payload["gather_job_closeout"] is None
    assert saved["record"]["runtime"]["gather_job"]["closed_at_five"] is False


def test_cli_does_not_offer_a_second_ledger_root_for_the_same_job():
    assert "--gather-job-store-root" not in run_gather_tick.build_parser().format_help()


@pytest.mark.parametrize("journal_failure", [False, True])
def test_canonical_runner_consumes_job_guard_with_synthetic_frames_only(
    monkeypatch, capsys, journal_failure,
):
    """No capture, Win32 input, endpoint, or live game is used by this fixture."""
    monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                        lambda *a, **k: "a" * 64)
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": "FOOD", "resource_level": 5},
    )
    catalog = compiled_gather_catalog(compiled)
    now = datetime.now(timezone.utc)
    frame = "synthetic-new-troop"
    target = VisualTarget(
        "TROOP_MARCH", frame, "MARCH", BoundingBox(850, 570, 940, 595), 1.0, "ocr",
    )

    def bundle(frame_id, labels, *, targets=(), facts=None):
        evidence = tuple(Evidence("semantic", label, 1.0, metadata={"frame_id": frame_id})
                         for label in labels)
        return ObservationBundle(
            Observation(now.timestamp() - (1 if frame_id == frame else 0.1), frame_id,
                        (1280, 720), evidence),
            SceneGraph(frame_id, None, targets, facts or {}),
        )

    observations = iter((
        bundle(frame, ("New Troop", "MARCH", "Units", "Total Power"),
               targets=(target,), facts={}),
        bundle("synthetic-after", (
            "used march count is greater than before dispatch",
            "troop/path indicator may be visible on map",
        ), facts={
            "march_queue_used": 1, "march_queue_capacity": 5,
            "march_queue_source": "visible_ocr_march_queue_region",
        }),
    ))

    class FakeCapture:
        def observe(self, context):
            import cv2
            import numpy as np

            bundle = next(observations)
            image = capture_root / "current.png"
            pixels = np.zeros((768, 1366, 3), dtype=np.uint8)
            pixels[568:607, 815:975] = (0, 130, 240)  # active orange March
            pixels[233:246, 703:735] = (0, 200, 0)  # selected troop slider
            pixels[245:465, 380:500] = (60, 120, 220)  # occupied portraits
            pixels[295:465, 520:595] = (60, 120, 220)
            ok, encoded = cv2.imencode(".png", pixels)
            assert ok
            png = encoded.tobytes()
            image.write_bytes(png)
            image_hash = hashlib.sha256(png).hexdigest()
            if bundle.scene.frame_id == frame:
                labels = (
                    ("New Troop", (620, 137, 735, 160)),
                    ("MARCH", (850, 570, 940, 595)),
                    ("Total Power", (650, 505, 735, 525)),
                    ("12,345", (745, 505, 805, 525)),
                    ("123,456", (940, 300, 990, 322)),
                    ("Units", (900, 208, 951, 230)),
                )
                evidence = tuple(Evidence(
                    "ocr", label, 1.0, BoundingBox(*box), value=label,
                    metadata={"frame_id": frame, "image_sha256": image_hash},
                ) for label, box in labels)
                observation = Observation(now.timestamp() - 1, frame, (1366, 768), evidence)
                grounded = replace(target, metadata={"image_sha256": image_hash})
                bundle = ObservationBundle(observation, replace(bundle.scene, targets=(grounded,)))
            window = {"hwnd": 1001, "pid": 2001, "title": "Rise of Kingdoms",
                      "exe": "MASS.exe", "process_path": r"C:\Game\MASS.exe"}
            (capture_root / "capture.json").write_text(json.dumps({
                "target": window, "post_capture": window,
                "frame": {"id": bundle.scene.frame_id, "image_sha256": image_hash},
                "png": str(image),
            }), encoding="utf-8")
            facts = dict(bundle.scene.facts) | {
                "window": {key: window[key] for key in ("hwnd", "pid", "title", "exe")},
                "image_path": str(image),
                "image_path_source": "current_capture_artifact",
                "image_sha256": image_hash,
            }
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))

    class FakeActuator:
        actions = []

        def perform(self, action):
            self.actions.append(action)

    class FakeHostGuard:
        def __init__(self, **kwargs):
            pass

        def check(self, context, before, choice, scene, resolved):
            return InterferenceCheck(True, "SYNTHETIC_HOST_OK")

    actuator = FakeActuator()
    monkeypatch.setattr(run_gather_tick, "WindowsLiveObservationProvider", lambda *a, **k: FakeCapture())
    for name in (
        "OcrSemanticObservationProvider", "QueueIndicatorObservationProvider",
        "MainViewVisualObservationProvider", "MapCoordinateObservationProvider",
        "ResourceLevelControlObservationProvider",
    ):
        monkeypatch.setattr(run_gather_tick, name, lambda inner, *a, **k: inner)
    monkeypatch.setattr(run_gather_tick, "WindowsHumanInputActuator", lambda: actuator)
    monkeypatch.setattr(run_gather_tick, "WindowsForegroundInterferenceGuard", FakeHostGuard)
    monkeypatch.setattr(run_gather_tick, "GatherScreenMappedActionSurface", lambda *a, **k: SemanticActionSurface())
    monkeypatch.setattr(run_gather_tick, "build_gather_tick_evidence", lambda **kwargs: {"runtime": {}})
    monkeypatch.setattr(run_gather_tick, "save_gather_tick_evidence", lambda root, record: Path(root) / "synthetic.json")
    if journal_failure:
        def deny_journal(*args, **kwargs):
            raise OSError("synthetic journal write failure")

        monkeypatch.setattr(JsonGatherJobStore, "record_verified", deny_journal)

    with TemporaryDirectory(dir=ROOT / "workspace") as folder:
        folder_path = Path(folder)
        capture_root = folder_path / "capture"
        capture_root.mkdir()
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", folder_path / "job-ledger")
        artifact = folder_path / "job.json"
        artifact.write_text(json.dumps({
            "schema_version": 1, "job_id": "synthetic-job", "task_id": "task-1",
            "character_id": "character-1", "catalog_digest": catalog.digest,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
            "allowed_actions": sorted(catalog.actions), "max_marches": 5,
            "mission_id": "GATHER_RESOURCE",
        }), encoding="utf-8")
        result = run_gather_tick.main(BASE_ARGS[2:] + [
            "--gather-job", str(artifact), "--checkpoint-root", str(folder_path / "checkpoints"),
        ])
        payload = json.loads(capsys.readouterr().out)
        assert len(actuator.actions) == 1, (
            payload.get("reason"), payload.get("selection"), payload.get("choice"),
        )
        assert payload["gather_job_id"] == "synthetic-job"
        assert payload["status"] == "complete"
        assert payload["gather_job_verified_marches"] == (0 if journal_failure else 1)
        assert payload["gather_job_journaled_this_tick"] is (not journal_failure)
        assert payload["gather_job_closed_at_five"] is False
        assert bool(payload["gather_job_verification_error"]) is journal_failure
        loaded = load_gather_job_authority(
            artifact, canonical_actions=catalog.actions,
            expected_catalog_digest=catalog.digest,
        )
        assert JsonGatherJobStore(folder_path / "job-ledger").client_binding(loaded).hwnd == 1001
    assert result == (4 if journal_failure else 0)
