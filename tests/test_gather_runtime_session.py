"""Offline canonical session: real providers/tool/runner/guards, fake OS edges."""
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from harness.contracts import BoundingBox, Evidence, Observation
from harness.gather_job_coordinator import gather_slot_run_id
from harness.gather_job_store import GatherClientBinding, JsonGatherJobStore, load_gather_job_authority
from harness.mission_runtime import ActionChoice
from harness.mission_selector import SelectionDecision, SelectionResult
from harness.mission_tool import InterferenceCheck, ObservationBundle
from harness.scene_graph import SceneGraph, VisualTarget
from scripts import run_gather_job as driver, run_gather_tick as tick
from scripts.create_gather_job import build_artifact, write_artifact


@pytest.fixture
def runtime(monkeypatch):
    import cv2
    import numpy as np

    with TemporaryDirectory(dir=tick.ROOT / "workspace") as folder:
        root = Path(folder)
        counts = Counter()
        frames = deque()
        observed = []
        actions = []
        trace = {"ready": True}
        window = {"hwnd": 1001, "pid": 2001, "title": "Rise of Kingdoms",
                  "exe": "MASS.exe", "process_path": r"C:\Game\MASS.exe"}
        now = datetime.now(timezone.utc)
        scope = build_artifact(job_id="retained-job", task_id="task", character_id="character",
                               resource_level=5, starts_at=now - timedelta(minutes=1),
                               expires_at=now + timedelta(minutes=20))
        artifact = write_artifact(root / "job.json", tick.ROOT / "workspace", scope)
        job = load_gather_job_authority(artifact, canonical_actions=frozenset(scope["allowed_actions"]),
                                        expected_catalog_digest=scope["catalog_digest"])
        monkeypatch.setattr(tick, "GATHER_JOB_STORE_ROOT", root / "ledger")
        monkeypatch.setattr(tick, "validate_canonical_startup_attestation", lambda *a, **k: "a" * 64)
        monkeypatch.setattr(tick, "_attested_job_client", lambda *a: GatherClientBinding.from_window(window))
        def validate_trace(*a, **k):
            counts["trace_validation"] += 1
            return dict(trace)
        monkeypatch.setattr(tick, "validate_gather_job_host_trace", validate_trace)

        class Capture:
            def __init__(self, *a, **k):
                counts["capture_init"] += 1
            def close(self):
                counts["capture_close"] += 1
            def observe(self, context):
                counts["observe"] += 1
                state, extras = frames.popleft()
                frame = f"frame-{counts['observe']}"
                observed.append((context.run_id, frame))
                directory = root / frame
                directory.mkdir()
                image = directory / "current.png"
                pixels = np.zeros((768, 1366, 3), dtype=np.uint8)
                pixels[568:607, 815:975] = (0, 130, 240)
                pixels[233:246, 703:735] = (0, 200, 0)
                pixels[245:465, 380:500] = (60, 120, 220)
                pixels[295:465, 520:595] = (60, 120, 220)
                ok, encoded = cv2.imencode(".png", pixels)
                assert ok
                png = encoded.tobytes()
                image.write_bytes(png)
                digest = hashlib.sha256(png).hexdigest()
                (directory / "capture.json").write_text(json.dumps({
                    "target": window, "post_capture": window, "png": str(image),
                    "frame": {"id": frame, "image_sha256": digest},
                }))
                labels = {
                    "CITY_VIEW": (("city buildings occupy central world canvas", None),
                                  ("resource counters across top", None),
                                  ("primary circular navigation/actions at bottom-right", None),
                                  ("quest/task list at left", None)),
                    "WORLD_MAP_VIEW": (("map terrain and world objects occupy central canvas", None),
                                       ("resource counters across top", None),
                                       ("bottom-right primary navigation is visible", None)),
                    "TROOP_DISPATCH_DRAWER": (("Dispatch a new troop from your city", None),
                                              ("New Troop", None)),
                    "NEW_TROOP_SETUP": (("New Troop", (620, 137, 735, 160)),
                                        ("MARCH", (850, 570, 940, 595)),
                                        ("Total Power", (650, 505, 735, 525)),
                                        ("12,345", (745, 505, 805, 525)),
                                        ("123,456", (940, 300, 990, 322)),
                                        ("Units", (900, 208, 951, 230))),
                }.get(state, ())
                evidence = tuple(Evidence("ocr" if box else "semantic", label, 1.0,
                                           BoundingBox(*box) if box else None, value=label,
                                           metadata={"frame_id": frame, "image_sha256": digest,
                                                     "confidence_known": True})
                                 for label, box in labels)
                targets = ()
                if state == "NEW_TROOP_SETUP":
                    targets = (VisualTarget("TROOP_MARCH", frame, "MARCH",
                                            BoundingBox(850, 570, 940, 595), 1.0, "ocr",
                                            metadata={"image_sha256": digest}),)
                facts = {"window": dict(window), "client_screen_rect": (0, 0, 1366, 768),
                         "image_path": str(image),
                         "image_path_source": "current_capture_artifact", "image_sha256": digest}
                facts.update(extras)
                return ObservationBundle(Observation(datetime.now(timezone.utc).timestamp() - .001,
                                                      frame, (1366, 768), evidence),
                                         SceneGraph(frame, None, targets, facts))

        class Actuator:
            def __init__(self):
                counts["actuator_init"] += 1
            def perform(self, action):
                actions.append(action)
            def close(self):
                counts["actuator_close"] += 1

        host = {"allowed": True}
        class HostGuard:
            def __init__(self, **kwargs):
                counts["host_init"] += 1
            def check(self, *a):
                return InterferenceCheck(host["allowed"], "OFFLINE_HOST_OK" if host["allowed"] else "TARGET_NOT_FOREGROUND")

        class Decision:
            model = "offline-model"
            behavior = None
            def choose(self, snapshot, candidates):
                counts["model_calls"] += 1
                self.last_model_output = "offline-choice"
                return self.behavior(snapshot, candidates) if self.behavior else None
            def close(self):
                counts["decision_close"] += 1
        decision = Decision()
        def decision_factory(*a):
            counts["decision_init"] += 1
            return decision
        monkeypatch.setattr(tick, "WindowsLiveObservationProvider", Capture)
        monkeypatch.setattr(tick, "WindowsHumanInputActuator", Actuator)
        monkeypatch.setattr(tick, "WindowsForegroundInterferenceGuard", HostGuard)
        monkeypatch.setattr(tick, "_local_llm_provider", decision_factory)
        # Count actual canonical provider/runner construction; do not replace behavior.
        for name in ("FarmSearchVisualObservationProvider", "OcrSemanticObservationProvider",
                     "QueueIndicatorObservationProvider", "MainViewVisualObservationProvider",
                     "MapCoordinateObservationProvider", "ResourceLevelControlObservationProvider",
                     "GatherFactObservationProvider",
                     "MissionRunner", "BoundedMissionTool"):
            original = getattr(tick, name)
            def factory(*a, _name=name, _original=original, **k):
                counts[_name] += 1
                return _original(*a, **k)
            monkeypatch.setattr(tick, name, factory)
        args = tick.build_parser().parse_args([
            "--gather-job", str(artifact), "--task-id", "task", "--character-id", "character",
            "--resource-type", job.resource_for_slot(1), "--resource-level", "5",
            "--startup-attestation-sha256", "a" * 64, "--arm-live",
            "--checkpoint-root", str(root / "checkpoints"), "--evidence-root", str(root / "evidence"),
        ])
        session = tick.GatherRuntimeSession(args)
        def step(state_frames, sequence=1):
            frames.extend(state_frames)
            return session.step(run_id=gather_slot_run_id(job, sequence),
                                resource_type=job.resource_for_slot(sequence),
                                host_trace_path=root / f"trace-{len(observed)}.json")
        yield SimpleNamespace(session=session, args=args, root=root, artifact=artifact, job=job,
                              counts=counts, observed=observed, actions=actions, step=step,
                              decision=decision, trace=trace, host=host)
        session.close()


def test_retained_canonical_composition_across_navigation_and_two_resources(runtime):
    r = runtime
    code, payload = r.step([("CITY_VIEW", {}), ("WORLD_MAP_VIEW", {})])
    assert (code, payload["status"]) == (0, "running"), payload
    identities = tuple(id(obj) for obj in (r.session._base_observations, r.session._runner,
                                          r.session._runner.tool, r.session._runner.tool.actions,
                                          r.session._actuator, r.session._decision_provider))
    # Canonical coordinator, completion rules and journal consume actual March postchecks.
    for sequence in range(1, 4):
        if sequence > 1:
            code, payload = r.step([("TROOP_DISPATCH_DRAWER", {
                "march_queue_used": sequence - 1, "march_queue_capacity": 5,
                "march_queue_source": "visible_ocr_queue_anchor"})], sequence)
            assert code == 3, payload  # no New Troop target in this frame: observe only
        code, payload = r.step([("NEW_TROOP_SETUP", {}), ("WORLD_MAP_VIEW", {
            "march_queue_used": sequence, "march_queue_capacity": 5,
            "march_queue_source": "visible_ocr_queue_anchor"})], sequence)
        assert (code, payload["status"]) == (0, "complete"), json.dumps(payload)
        assert payload["gather_job_verified_marches"] == sequence
        assert payload["gather_job_journaled_this_tick"] is True
        assert identities == tuple(id(obj) for obj in (r.session._base_observations, r.session._runner,
                                  r.session._runner.tool, r.session._runner.tool.actions,
                                  r.session._actuator, r.session._decision_provider))
    assert len({r.job.resource_for_slot(n) for n in range(1, 4)}) >= 2
    for name in ("capture_init", "actuator_init", "decision_init", "host_init", "MissionRunner",
                 "BoundedMissionTool", "OcrSemanticObservationProvider", "QueueIndicatorObservationProvider",
                 "MainViewVisualObservationProvider", "MapCoordinateObservationProvider"):
        assert r.counts[name] == 1, r.counts
    assert len({frame for _, frame in r.observed}) == r.counts["observe"]
    assert r.counts["ResourceLevelControlObservationProvider"] == 2
    r.session.close()
    assert r.session._runner is None and not r.session._resource_providers
    assert r.counts["actuator_close"] == r.counts["decision_close"] == r.counts["capture_close"] == 1
    with pytest.raises(RuntimeError, match="closed"):
        r.session.step()


@pytest.mark.parametrize("behavior", ["abstain", "failed", "stale_frame", "stale_trace", "scope_changed", "client_changed", "focus_changed"])
def test_bounded_decision_wait_never_bypasses_dispatch_preflight_and_survives(runtime, behavior):
    r = runtime
    r.step([("UNKNOWN_STATE", {})])
    runner = r.session._runner
    original_selector = runner.selector
    class AmbiguousCity:
        def select(self, *a, **k):
            return SelectionResult(SelectionDecision.NEEDS_DECISION,
                                   candidates=(ActionChoice("TOGGLE_CITY_MAP"),))
    runner.selector = AmbiguousCity()
    original_scope = r.artifact.read_bytes()
    def choose(snapshot, candidates):
        r.decision.last_request_elapsed_ms = 11000  # model wait is synthetic; no sleeps or endpoint
        if behavior == "failed":
            raise TimeoutError("bounded model timeout")
        if behavior == "abstain":
            return None
        if behavior == "stale_frame":
            guard = next(iter(r.session._resource_guards.values()))
            guard.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=11)
        elif behavior == "stale_trace":
            r.trace["ready"] = False
        elif behavior == "scope_changed":
            r.artifact.write_bytes(original_scope + b" ")
        elif behavior == "client_changed":
            # The canonical guard must reject a scene whose bound client
            # changes while a retained decision provider is choosing.
            scene = runner.tool.inner._scenes[snapshot.frame_id]
            scene.facts["window"]["hwnd"] = 9999
        elif behavior == "focus_changed":
            r.host["allowed"] = False
        return candidates[0]
    r.decision.behavior = choose
    code, payload = r.step([("CITY_VIEW", {})])
    assert code in (2, 3, 4), payload
    assert r.actions == []
    assert JsonGatherJobStore(r.root / "ledger").progress(r.job).dispatched_marches == 0
    assert "approval" not in str(payload.get("reason", "")).lower()
    assert r.session._runner is runner and r.counts["capture_init"] == 1
    r.artifact.write_bytes(original_scope)
    r.trace["ready"] = True
    r.host["allowed"] = True
    for guard in r.session._resource_guards.values():
        guard.clock = lambda: datetime.now(timezone.utc)
    runner.selector = original_selector
    code, payload = r.step([("CITY_VIEW", {}), ("WORLD_MAP_VIEW", {})])
    assert (code, payload["status"]) == (0, "running"), payload
    assert len(r.actions) == 1 and r.counts["actuator_init"] == 1
    assert payload["local_llm"]["model_output"] is None
    assert payload["local_llm"]["request_elapsed_ms"] is None


def test_arguments_are_copied_and_asset_mutation_denies_before_new_observation(runtime):
    r = runtime
    r.args.character_id = "other-character"
    code, payload = r.step([("UNKNOWN_STATE", {})])
    assert code == 3 and payload["gather_job_id"] == r.job.job_id
    original = r.artifact.read_bytes()
    r.artifact.write_bytes(original + b" ")
    observed = r.counts["observe"]
    code, payload = r.session.step(run_id=gather_slot_run_id(r.job, 1),
                                  host_trace_path=r.root / "trace.json")
    assert code == 2 and "assets changed" in payload["error"]["message"]
    assert r.counts["observe"] == observed and r.actions == []
    r.artifact.write_bytes(original)


def test_pending_march_is_observation_only_in_the_same_session(runtime):
    r = runtime
    code, payload = r.step([("NEW_TROOP_SETUP", {}), ("UNKNOWN_STATE", {})])
    assert (code, payload["status"]) == (3, "reobserve"), payload
    assert len(r.actions) == 1, json.dumps(payload)
    code, payload = r.step([("WORLD_MAP_VIEW", {"march_queue_used": 1, "march_queue_capacity": 5,
                                               "march_queue_source": "visible_ocr_queue_anchor"})])
    assert (code, payload["status"]) == (0, "complete"), json.dumps(payload)
    assert len(r.actions) == 1 and payload["gather_job_verified_marches"] == 1


def test_default_driver_consumes_session_without_subprocess():
    import ast
    tree = ast.parse(Path(driver.__file__).read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                   for node in ast.walk(tree))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    methods = {node.func.attr for node in ast.walk(main)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and isinstance(node.func.value, ast.Name) and node.func.value.id == "session"}
    assert {"step", "close"} <= methods
