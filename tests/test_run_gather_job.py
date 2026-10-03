"""The outer driver consumes canonical tick results without using game input."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from harness.gather_job_coordinator import gather_slot_run_id
from harness.gather_job_store import load_gather_job_authority
from harness.gather_job_store import JsonGatherJobStore
from harness.gather_job_store import GatherClientBinding
from harness.mission_runner import MissionTickResult
from harness.mission_runtime import AllowedAction, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, JsonMissionStore, MissionCheckpoint
from scripts.create_gather_job import build_artifact, write_artifact, write_launch_spec
from scripts import run_gather_job as driver
from scripts import run_gather_tick
from scripts import audit_first_done_job as auditor
from scripts import record_host_input_isolation as host_recorder
from scripts.run_gather_job import build_parser, drive_job, _tick_command


JOB = "one-startup-job"
ATTESTATION_SHA = "a" * 64


def closeout():
    return [
        {"job_id": JOB, "sequence": sequence,
         "run_id": f"run-{sequence}", "before_count": sequence - 1,
         "after_count": sequence, "capacity": 5,
         "receipt": {"action_id": "MARCH_WITH_CURRENT_SELECTION",
                     "target_id": "TROOP_MARCH"}}
        for sequence in range(1, 6)
    ]


def tick_result(status, sequence, verified, **extras):
    return 0, {
        "status": status, "gather_job_id": JOB,
        "run_id": f"run-{sequence}",
        "gather_job_verified_marches": verified,
        "gather_job_closed_at_five": False,
        "gather_job_journaled_this_tick": status == "complete",
        **extras,
    }


def feed(results):
    pending = iter(results)
    return lambda: next(pending)


def drive(results, *, max_ticks=20, max_idle_ticks=2):
    sleeps = []
    outcome = drive_job(
        feed(results), job_id=JOB, max_ticks=max_ticks,
        max_idle_ticks=max_idle_ticks, idle_delay_seconds=0.5,
        settle_seconds=1.2, sleeper=sleeps.append,
    )
    return outcome, sleeps


def test_five_distinct_occurrences_close_only_with_verified_journal():
    ticks = []
    for sequence in range(1, 6):
        ticks.append(tick_result(
            "running", sequence, sequence - 1,
            choice={"action_id": "CREATE_NEW_TROOP"},
        ))
        final = tick_result("complete", sequence, sequence)
        if sequence == 5:
            final[1]["gather_job_closed_at_five"] = True
            final[1]["gather_job_closeout"] = closeout()
        ticks.append(final)
    result, sleeps = drive(ticks)
    assert result["status"] == "complete"
    assert result["verified_marches"] == 5
    assert result["ticks"] == 10
    assert len(sleeps) == 5
    assert [entry["run_id"] for entry in result["closeout"]] == [f"run-{i}" for i in range(1, 6)]


def test_restart_may_resume_from_durable_progress_without_starting_at_zero():
    fourth = tick_result("complete", 4, 4)
    fifth = tick_result("complete", 5, 5,
                        gather_job_closed_at_five=True, gather_job_closeout=closeout())
    result, _ = drive([tick_result("running", 4, 3), fourth,
                       tick_result("running", 5, 4), fifth])
    assert result["status"] == "complete" and result["ticks"] == 4


def test_false_closeout_and_unverified_complete_fail_closed():
    false_five = tick_result("complete", 5, 5, gather_job_closed_at_five=True,
                             gather_job_closeout=closeout()[:-1])
    result, _ = drive([false_five])
    assert result["status"] == "failed"
    assert "closeout" in result["reason"]
    duplicate = closeout()
    duplicate[4]["run_id"] = duplicate[3]["run_id"]
    repeated_run = tick_result("complete", 5, 5,
                               gather_job_closed_at_five=True,
                               gather_job_closeout=duplicate)
    result, _ = drive([repeated_run])
    assert result["status"] == "failed"
    unverified = tick_result("complete", 1, 0, gather_job_journaled_this_tick=False)
    result, _ = drive([unverified])
    assert result["status"] == "failed"
    assert "VERIFIED" in result["reason"]


@pytest.mark.parametrize("code,status,journaled", [
    (0, "failed", True),
    (4, "complete", True),
    (0, "complete", False),
])
def test_terminal_closeout_requires_successful_journaled_tick(code, status, journaled):
    forged = tick_result(
        status, 5, 5, gather_job_closed_at_five=True,
        gather_job_journaled_this_tick=journaled,
        gather_job_closeout=closeout(),
    )
    result, _ = drive([(code, forged[1])])
    assert result["status"] == "failed"
    assert "journaled tick" in result["reason"]
    if status == "failed":
        recovered = drive_job(
            lambda: (code, forged[1]), job_id=JOB, max_ticks=1, max_idle_ticks=0,
            idle_delay_seconds=0, settle_seconds=0,
            validate_closed=lambda _: True,
        )
        assert recovered["status"] == "failed"


def test_reobserve_is_bounded_and_does_not_issue_an_approval():
    reobserve = (3, tick_result("reobserve", 1, 0)[1])
    result, sleeps = drive([reobserve, reobserve, reobserve, reobserve])
    assert result["status"] == "suspended"
    assert result["ticks"] == 4
    assert sleeps == [0.5, 0.5, 0.5]
    args = build_parser().parse_args([
        "--gather-job", "workspace/jobs/one.json", "--task-id", "task",
        "--character-id", "char", "--resource-type", "FOOD",
    ])
    command = _tick_command(args, ATTESTATION_SHA)
    assert "--gather-job" in command
    assert command[command.index("--startup-attestation-sha256") + 1] == ATTESTATION_SHA
    assert "--run-id" not in command
    assert "--approve-current-troop-selection" not in command


def test_need_decision_or_skipped_verified_count_stops():
    needs_decision = (3, tick_result("needs_decision", 1, 0)[1])
    result, _ = drive([needs_decision])
    assert result["status"] == "suspended"
    skipped = [tick_result("running", 1, 0), tick_result("running", 1, 2)]
    result, _ = drive(skipped)
    assert result["status"] == "failed"
    assert "skipped" in result["reason"]


def test_subprocess_typed_error_survives_missing_job_metadata(monkeypatch):
    error = {"type": "ValueError", "message": "first slot rejects numeric queue"}
    envelope = {"status": "failed", "error": error}
    # A fatal stderr envelope must also outrank earlier stdout tick output.
    completed = SimpleNamespace(
        returncode=2, stdout=json.dumps(tick_result("running", 1, 0)[1]),
        stderr="diagnostic preamble\n" + json.dumps(envelope) + "\n",
    )
    monkeypatch.setattr(driver.subprocess, "run", lambda *_, **__: completed)
    tick = driver._subprocess_tick(["offline-fixture"])
    assert tick == (2, envelope)
    result, sleeps = drive([tick])
    assert result["status"] == "failed"
    assert result["reason"] == (
        "tick execution failed (exit code 2): ValueError: first slot rejects numeric queue"
    )
    assert result["verified_marches"] is None and result["closeout"] is None
    assert result["history"] == [{"status": "failed", "exit_code": 2, "error": error}]
    assert sleeps == []


@pytest.mark.parametrize("stdout,stderr", [
    ("{malformed JSON" + "x" * 5000, "traceback" + "y" * 5000),
    ("", "native process failed"),
    ("[]\n42\nnull\n", ""),
])
def test_subprocess_without_json_preserves_bounded_failure_output(monkeypatch, stdout, stderr):
    completed = SimpleNamespace(returncode=7, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(driver.subprocess, "run", lambda *_, **__: completed)
    tick = driver._subprocess_tick(["offline-fixture"])
    result, sleeps = drive([tick])
    assert result["status"] == "failed"
    assert result["reason"] == "tick execution failed (exit code 7): tick emitted no JSON result"
    record = result["history"][0]
    assert record["exit_code"] == 7
    for stream, source in (("stdout", stdout), ("stderr", stderr)):
        assert record[stream] == source[-4096:]
        assert len(record[stream]) <= 4096
        assert record[stream + "_truncated"] is (len(source) > 4096)
    assert result["verified_marches"] is None and sleeps == []


@pytest.mark.parametrize("status,error", [("running", None), ("failed", {"type": "ValueError", "message": "bad"})])
def test_normal_payload_wrong_job_remains_rejected(status, error):
    code, payload = tick_result(status, 1, 0, gather_job_id="other-job", error=error)
    result, sleeps = drive([(code, payload)])
    assert result["status"] == "failed"
    assert result["reason"] == "tick job identity changed"
    assert result["verified_marches"] is None and sleeps == []


def test_unbound_error_cannot_mint_run_progress_or_closeout():
    error = {"type": "RuntimeError", "message": "write failed"}
    forged = tick_result("complete", 5, 5,
                         gather_job_closed_at_five=True, gather_job_closeout=closeout())[1]
    forged.pop("gather_job_id")
    forged.update(status="failed", error=error)
    result, sleeps = drive([tick_result("running", 2, 1), (2, forged)])
    assert result["status"] == "failed" and result["verified_marches"] == 1
    assert result["closeout"] is None
    assert result["history"][-1] == {"status": "failed", "exit_code": 2, "error": error}
    assert sleeps == []


def test_live_arm_reaches_only_traced_tick_and_legacy_job_is_denied(monkeypatch, capsys):
    unarmed = build_parser().parse_args([
        "--gather-job", "workspace/jobs/job.json", "--task-id", "task",
        "--character-id", "char", "--resource-type", "GOLD",
    ])
    armed = build_parser().parse_args([
        "--gather-job", "workspace/jobs/job.json", "--task-id", "task",
        "--character-id", "char", "--resource-type", "GOLD", "--arm-live",
    ])
    trace = Path("workspace/evidence/trace.json")
    assert "--arm-live" not in _tick_command(unarmed, ATTESTATION_SHA, run_id="run", host_trace_path=trace)
    assert "--arm-live" in _tick_command(armed, ATTESTATION_SHA, run_id="run", host_trace_path=trace)
    assert "--arm-live" not in _tick_command(armed, ATTESTATION_SHA)
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="legacy-live-denied", task_id="task", character_id="char",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("tick must not run"))
        assert driver.main([
            "--gather-job", str(artifact), "--task-id", "task",
            "--character-id", "char", "--resource-type", "FOOD",
            "--resource-level", "5", "--arm-live",
        ]) == 2
    assert "schema-v2" in capsys.readouterr().err


def test_job_host_recorder_runs_without_per_tick_prompt_and_validates_before_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    recovery = tmp_path / "workspace" / "evidence" / "recovery.json"
    recovery.parent.mkdir(parents=True)
    recovery.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(operator_confirms_quiescent=True,
                           host_session_id="windows-session-1", recovery_evidence=recovery)
    job = SimpleNamespace(job_id="job-host-1")
    client = GatherClientBinding.from_window({
        "hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe",
    })
    calls = []

    def passive_record(**kwargs):
        calls.append(kwargs)
        return {"run_id": kwargs["run_id"], "assessment": {"ready": True}}

    def validate(path, **kwargs):
        assert path.is_file()
        assert kwargs["expected_client"] == client
        assert kwargs["expected_run_id"] == "run-1"
        return {"ready": True}

    monkeypatch.setattr(host_recorder, "record", passive_record)
    monkeypatch.setattr(driver, "validate_gather_job_host_trace", validate)
    trace = driver._record_job_host_trace(
        args, job, run_id="run-1", client=client, attempt_sequence=1, tick_index=1,
    )
    assert trace.is_file() and len(calls) == 1
    assert calls[0]["focus_delay_seconds"] == 0.0
    assert calls[0]["operator_confirms_quiescent"] is True
    with pytest.raises(ValueError, match="already exists"):
        driver._record_job_host_trace(
            args, job, run_id="run-1", client=client, attempt_sequence=1, tick_index=1,
        )
    assert len(calls) == 1


def test_job_host_recorder_failure_denies_before_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    recovery = tmp_path / "workspace" / "evidence" / "recovery.json"
    recovery.parent.mkdir(parents=True)
    recovery.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(operator_confirms_quiescent=True,
                           host_session_id="windows-session-1", recovery_evidence=recovery)
    job = SimpleNamespace(job_id="job-host-1")
    client = GatherClientBinding.from_window({
        "hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe",
    })
    monkeypatch.setattr(host_recorder, "record",
                        lambda **_: (_ for _ in ()).throw(ValueError("synthetic recorder failure")))
    monkeypatch.setattr(driver, "validate_gather_job_host_trace",
                        lambda *_, **__: pytest.fail("invalid recorder must not validate"))
    with pytest.raises(ValueError, match="synthetic recorder failure"):
        driver._record_job_host_trace(
            args, job, run_id="run-1", client=client, attempt_sequence=1, tick_index=1,
        )


def test_driver_requires_canonical_attestation_before_attempt_or_tick(monkeypatch, capsys):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="missing-startup-record", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("no tick allowed"))
        reports = root / "reports"
        assert driver.main([
            "--gather-job", str(artifact), "--task-id", "task",
            "--character-id", "character", "--resource-type", "FOOD",
            "--resource-level", "5", "--report-root", str(reports),
        ]) == 2
        assert "canonical startup attestation is missing" in capsys.readouterr().err
        assert not list(reports.rglob("attempt-*.start.json"))


def test_driver_cannot_change_pinned_attestation_on_resume():
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="pin-on-resume", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        job = load_gather_job_authority(
            artifact, canonical_actions=frozenset(scope["allowed_actions"]),
            expected_catalog_digest=scope["catalog_digest"],
        )
        reports = root / "reports"
        first_path, first = driver._write_attempt_start(reports, job, ATTESTATION_SHA)
        assert first["startup_attestation_sha256"] == ATTESTATION_SHA
        with pytest.raises(ValueError, match="differs across attempts"):
            driver._write_attempt_start(reports, job, "b" * 64)
        assert first_path.is_file()
        assert not list(reports.rglob("attempt-000002.start.json"))


@pytest.mark.parametrize("failure", ["missing", "changed_digest"])
def test_terminal_recovery_checks_startup_attestation_before_audit(
    monkeypatch, capsys, failure,
):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="terminal-preflight", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        job = load_gather_job_authority(
            artifact, canonical_actions=frozenset(scope["allowed_actions"]),
            expected_catalog_digest=scope["catalog_digest"],
        )
        reports = root / "reports"
        start_path, _ = driver._write_attempt_start(reports, job, ATTESTATION_SHA)
        result_path = start_path.with_name("attempt-000001.result.json")
        result_path.write_text(json.dumps({
            "status": "complete", "attempt_sequence": 1, "job_id": job.job_id,
        }), encoding="utf-8")
        if failure == "changed_digest":
            monkeypatch.setattr(driver, "validate_canonical_startup_attestation",
                                lambda *a, **k: "b" * 64)
        monkeypatch.setattr(driver, "_audit_closeout",
                            lambda *a: pytest.fail("terminal audit must not run"))
        assert driver.main([
            "--gather-job", str(artifact), "--task-id", "task",
            "--character-id", "character", "--resource-type", "FOOD",
            "--resource-level", "5", "--report-root", str(reports),
        ]) == 2
        error = capsys.readouterr().err
        assert ("canonical startup attestation is missing" if failure == "missing"
                else "terminal attestation differs") in error
        assert not list(reports.rglob("attempt-000002.start.json"))


def test_driver_stop_report_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver.time, "time_ns", lambda: 123)
    root = tmp_path / "workspace" / "evidence" / "gather" / "job-drives"
    payload = {"job_id": JOB, "status": "suspended", "reason": "idle bound"}
    path = driver._write_report(root, payload)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        driver._write_report(root, payload)
    assert path.read_bytes() == original


def test_driver_consumes_canonical_cli_waiting_result_without_game(monkeypatch):
    """The real one-tick CLI result keeps one slot ID during a bounded wait."""
    class FakeRunner:
        def __init__(self, compiled, tool, store, **kwargs):
            self.tool = tool

        def tick(self, context):
            return MissionTickResult(
                CheckpointStatus.WAITING,
                MissionCheckpoint(context.mission_id, context.task_id, context.run_id, 0,
                                  status=CheckpointStatus.WAITING),
                reason="offline waiting fixture; no capture or input",
            )

    monkeypatch.setattr(run_gather_tick, "MissionRunner", FakeRunner)
    monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                        lambda *a, **k: ATTESTATION_SHA)
    monkeypatch.setattr(run_gather_tick, "WindowsHumanInputActuator", lambda: object())
    monkeypatch.setattr(run_gather_tick, "build_gather_tick_evidence", lambda **kwargs: {"runtime": {}})
    monkeypatch.setattr(run_gather_tick, "save_gather_tick_evidence",
                        lambda root, record: Path(root) / "offline-driver-wiring.json")
    now = datetime.now(timezone.utc)
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", root / "ledger")
        artifact = root / "job.json"
        scope = build_artifact(
            job_id="driver-cli-job", task_id="one-character", character_id="char-one",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact.write_text(json.dumps(scope), encoding="utf-8")
        job = load_gather_job_authority(
            artifact, canonical_actions=frozenset(scope["allowed_actions"]),
            expected_catalog_digest=scope["catalog_digest"],
        )

        def canonical_tick():
            output = StringIO()
            with redirect_stdout(output):
                code = run_gather_tick.main([
                    "--gather-job", str(artifact), "--task-id", "one-character",
                    "--character-id", "char-one", "--resource-type", "FOOD",
                    "--resource-level", "5",
                ])
            return code, json.loads(output.getvalue())

        result = drive_job(canonical_tick, job_id=job.job_id, max_ticks=3,
                           max_idle_ticks=0, idle_delay_seconds=0, settle_seconds=0,
                           sleeper=lambda _: None)
    assert result["status"] == "suspended"
    assert result["ticks"] == 2
    assert result["verified_marches"] == 0
    assert [tick["run_id"] for tick in result["history"]] == [gather_slot_run_id(job, 1)] * 2


@pytest.mark.parametrize("crash_phase,arm_live", [
    ("none", False), ("before_result", False), ("after_result", False),
    ("none", True),
    ("journal_mid", False), ("journal_fifth", False),
])
def test_driver_launch_spec_drives_five_real_canonical_ticks_and_journal(
    monkeypatch, capsys, crash_phase, arm_live,
):
    """Only observation and actuation are synthetic; CLI, runner and journal are real."""
    window = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}
    precondition = "troop/commander selection policy is valid for this mission"
    actions = []
    tick_calls = []
    attestation_checks = []
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        ledger_root = root / "ledger"
        checkpoint_root = root / "checkpoints"
        evidence_root = root / "evidence"
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", ledger_root)
        monkeypatch.setattr(driver, "GATHER_JOB_STORE_ROOT", ledger_root)
        monkeypatch.setattr(driver, "GATHER_CHECKPOINT_ROOT", checkpoint_root)
        monkeypatch.setattr(driver, "GATHER_EVIDENCE_ROOT", evidence_root)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="five-cli-job", task_id="five-task", character_id="five-character",
            resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        launch = write_launch_spec(
            root / "job.launch.json", driver.ROOT / "workspace", artifact,
            resource_level=5,
        )
        job = load_gather_job_authority(
            artifact, canonical_actions=frozenset(scope["allowed_actions"]),
            expected_catalog_digest=scope["catalog_digest"],
        )

        def synthetic_attestation(*_args, **kwargs):
            assert kwargs.get("expected_sha256") in (None, ATTESTATION_SHA)
            assert "profile_path" not in kwargs
            attestation_checks.append(kwargs.get("expected_sha256"))
            return ATTESTATION_SHA

        monkeypatch.setattr(driver, "validate_canonical_startup_attestation",
                            synthetic_attestation)
        monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                            synthetic_attestation)
        binding = GatherClientBinding.from_window(window)
        monkeypatch.setattr(driver, "_attested_client", lambda *_: binding)
        monkeypatch.setattr(run_gather_tick, "_attested_job_client", lambda *_: binding)
        host_traces = []

        def synthetic_host_trace(_args, _job, *, run_id, client, attempt_sequence, tick_index):
            assert client == binding
            path = root / f"host-{attempt_sequence}-{tick_index}.json"
            path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
            host_traces.append((run_id, path))
            return path

        def synthetic_host_validation(path, *, expected_run_id, expected_client, **_kwargs):
            assert expected_client == binding
            assert (expected_run_id, path) in host_traces
            return {"ready": True, "trace_path": str(path), "run_id": expected_run_id,
                    "input_telemetry": "recorder_self_report_only"}

        monkeypatch.setattr(driver, "_record_job_host_trace", synthetic_host_trace)
        monkeypatch.setattr(run_gather_tick, "validate_gather_job_host_trace",
                            synthetic_host_validation)
        ledger = JsonGatherJobStore(ledger_root)
        ledger.bind_client(job, window)
        assert ledger.progress(job).verified_marches == 0

        class SyntheticTool:
            def __init__(self, sequence):
                self.sequence = sequence
                self.observations = 0
                # Keep synthetic frames current even on a slow Windows test
                # run; the next slot gets a new tool after the prior tick.
                self.start = datetime.now(timezone.utc).timestamp() - 0.01

            def observe(self, context):
                self.observations += 1
                if self.observations == 1:
                    image_hash = f"{self.sequence:064x}"
                    facts = {"character_id": job.character_id, "window": window,
                             "image_sha256": image_hash, "new_troop_formation_ready": True,
                             "new_troop_formation_source":
                                 "same_frame_new_troop_ocr_and_pixels_1366x768",
                             "new_troop_formation_frame_id": f"before-{self.sequence}",
                             "new_troop_formation_image_sha256": image_hash,
                             "precondition_evidence": {precondition: True},
                             "gather_job_id": job.job_id}
                    if self.sequence > 1:
                        facts["completion_baseline"] = {
                            "predicate_id": "march_queue_used_increased",
                            "counter_fact": "march_queue_used", "counter_value": self.sequence - 1,
                            "capacity": 5, "source_frame_id": f"baseline-{self.sequence}",
                            "source": "visible_ocr_queue_anchor", "character_id": job.character_id,
                            "source_timestamp": self.start,
                        }
                    return ToolSnapshot(
                        context.mission_id, context.task_id, f"before-{self.sequence}",
                        "NEW_TROOP_SETUP",
                        facts=facts,
                        allowed_actions=(AllowedAction("MARCH_WITH_CURRENT_SELECTION", True,
                                                       ("TROOP_MARCH",)),),
                        target_ids=("TROOP_MARCH",), observed_at=self.start,
                    )
                if self.observations == 2:
                    return ToolSnapshot(
                        context.mission_id, context.task_id, f"after-{self.sequence}",
                        "WORLD_MAP_VIEW",
                        facts={"march_queue_used": self.sequence, "march_queue_capacity": 5,
                               "march_queue_source": "visible_ocr_queue_anchor",
                               "character_id": job.character_id, "window": window,
                               "image_sha256": f"{self.sequence + 100:064x}"},
                        observed_at=self.start + 0.001,
                    )
                raise AssertionError("unexpected extra observation")

            def execute(self, context, before, choice):
                reservation = ledger.reserve_dispatch(
                    job, run_id=context.run_id, frame_id=before.frame_id,
                    action=choice.action_id,
                )
                actions.append((context.run_id, choice.action_id))
                return ToolFeedback(True, "DISPATCHED", facts={
                    "gather_job_id": job.job_id,
                    "gather_job_dispatch_sequence": reservation.sequence,
                    "receipt": {"action_id": choice.action_id, "target_id": choice.target_id,
                                "before_frame_id": before.frame_id,
                                "bounded_arguments": dict(choice.arguments),
                                "character_id": job.character_id,
                                "non_interference_confirmed": True},
                })

        def synthetic_tool(*_args, **_kwargs):
            return SyntheticTool(ledger.progress(job).verified_marches + 1)

        monkeypatch.setattr(run_gather_tick, "BoundedMissionTool", synthetic_tool)
        monkeypatch.setattr(run_gather_tick, "WindowsHumanInputActuator", lambda: object())
        monkeypatch.setattr(run_gather_tick, "WindowsLiveObservationProvider", lambda *a, **k: object())

        def canonical_tick(command):
            tick_calls.append(tuple(command))
            output = StringIO()
            error = StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                code = run_gather_tick.main(command[2:] + [
                    "--checkpoint-root", str(checkpoint_root),
                    "--evidence-root", str(evidence_root),
                ])
            assert output.getvalue(), (code, error.getvalue())
            payload = json.loads(output.getvalue())
            assert payload["startup_attestation_sha256"] == ATTESTATION_SHA
            return code, payload

        monkeypatch.setattr(driver, "_subprocess_tick", canonical_tick)
        live_flag = ["--arm-live"] if arm_live else []
        first_code = driver.main([
            "--launch-spec", str(launch), "--report-root", str(root / "reports"),
            "--max-ticks", "2", "--idle-delay-seconds", "0", "--settle-seconds", "0",
        ] + live_flag)
        first = json.loads(capsys.readouterr().out)
        assert first_code == 3 and first["status"] == "suspended", (first_code, first)
        assert first["verified_marches"] == 2 and first["ticks"] == 2
        assert first["audit_status"] is None
        original_write = driver._write_report
        original_audit = driver._audit_closeout
        if crash_phase in {"journal_mid", "journal_fifth"}:
            import harness.gather_job_store as store_module
            original_replace = store_module.os.replace
            failed_append = []
            def fail_one_journal_replace(source, destination):
                if Path(destination) == ledger._path(job):
                    state = json.loads(Path(source).read_text())
                    target = 3 if crash_phase == "journal_mid" else 5
                    if len(state["verifications"]) == target and not failed_append:
                        failed_append.append(target)
                        raise PermissionError(5, "one-shot Windows journal replace denial")
                return original_replace(source, destination)
            monkeypatch.setattr(store_module.os, "replace", fail_one_journal_replace)
        if crash_phase == "before_result":
            def interrupt_result(path, result):
                if result.get("attempt_sequence") == 2:
                    raise OSError("synthetic crash after fifth persisted tick")
                return original_write(path, result)
            monkeypatch.setattr(driver, "_write_report", interrupt_result)
        elif crash_phase == "after_result":
            def interrupt_audit(job, result, report):
                if result.get("attempt_sequence") == 2:
                    raise OSError("synthetic crash after terminal result")
                return original_audit(job, result, report)
            monkeypatch.setattr(driver, "_audit_closeout", interrupt_audit)
        second_code = driver.main([
            "--launch-spec", str(launch), "--report-root", str(root / "reports"),
            "--max-ticks", "3", "--idle-delay-seconds", "0", "--settle-seconds", "0",
        ] + live_flag)
        second_output = capsys.readouterr()
        if crash_phase != "none":
            if crash_phase.startswith("journal_"):
                assert second_code == 4
                assert json.loads(second_output.out)["reason"] == "job verification failed"
                assert failed_append
            else:
                assert second_code == 2 and "synthetic crash" in second_output.err
            if crash_phase == "journal_mid":
                old_count = ledger.progress(job).verified_marches
                old_actions = list(actions)
                with pytest.raises(ValueError, match="under workspace"):
                    driver._reconcile_verified_journal(job, root.parent.parent / "external", ATTESTATION_SHA)
                assert ledger.progress(job).verified_marches == old_count and actions == old_actions
                ledger_bytes = ledger._path(job).read_bytes()
                with monkeypatch.context() as clock_patch:
                    class ExpiredClock:
                        @staticmethod
                        def now(_timezone):
                            return job.expires_at
                    clock_patch.setattr(driver, "datetime", ExpiredClock)
                    with pytest.raises(ValueError, match="outside job time scope"):
                        driver._reconcile_verified_journal(job, root / "reports", ATTESTATION_SHA)
                assert ledger._path(job).read_bytes() == ledger_bytes and actions == old_actions
                original_progress = JsonGatherJobStore.progress
                with monkeypatch.context() as revoked_patch:
                    def revoked_progress(store, authority):
                        return replace(original_progress(store, authority), revoked=True)
                    revoked_patch.setattr(JsonGatherJobStore, "progress", revoked_progress)
                    with pytest.raises(ValueError, match="job revoked"):
                        driver._reconcile_verified_journal(job, root / "reports", ATTESTATION_SHA)
                assert ledger._path(job).read_bytes() == ledger_bytes and actions == old_actions
                from harness.mission_runtime import MissionContext
                context = MissionContext(job.mission_id, job.task_id, gather_slot_run_id(job, 3))
                checkpoint_path = JsonMissionStore(checkpoint_root)._path(context)
                checkpoint_bytes = checkpoint_path.read_bytes()
                raw_checkpoint = json.loads(checkpoint_bytes)
                raw_checkpoint["checkpoint"]["verified_transition"] = None
                checkpoint_path.write_text(json.dumps(raw_checkpoint))
                with pytest.raises((ValueError, TypeError)):
                    driver._reconcile_verified_journal(job, root / "reports", ATTESTATION_SHA)
                checkpoint_path.write_bytes(checkpoint_bytes)
                assert ledger.progress(job).verified_marches == old_count and actions == old_actions
                bad_client = GatherClientBinding.from_window({**window, "hwnd": 1002})
                original_client_reader = driver._attested_client
                monkeypatch.setattr(driver, "_attested_client", lambda *_: bad_client)
                with pytest.raises(ValueError, match="client mismatch"):
                    driver._reconcile_verified_journal(job, root / "reports", ATTESTATION_SHA)
                monkeypatch.setattr(driver, "_attested_client", original_client_reader)
                assert ledger.progress(job).verified_marches == old_count and actions == old_actions
                original_receipt_writer = driver._write_recovery_record
                def deny_intent(path, record):
                    raise PermissionError(5, "ongoing recovery I/O denial")
                monkeypatch.setattr(driver, "_write_recovery_record", deny_intent)
                for _ in range(2):
                    with pytest.raises(PermissionError, match="ongoing recovery I/O denial"):
                        driver._reconcile_verified_journal(job, root / "reports", ATTESTATION_SHA)
                    assert ledger.progress(job).verified_marches == old_count and actions == old_actions
                monkeypatch.setattr(driver, "_write_recovery_record", original_receipt_writer)
                def deny_commit(path, record):
                    if record.get("kind") == "journal_recovery_commit":
                        raise PermissionError(5, "receipt commit denied")
                    original_receipt_writer(path, record)
                monkeypatch.setattr(driver, "_write_recovery_record", deny_commit)
                prior_actions = list(actions)
                denied = driver.main(["--launch-spec", str(launch), "--report-root", str(root / "reports"),
                                      "--max-ticks", "3", "--idle-delay-seconds", "0", "--settle-seconds", "0"])
                assert denied == 2 and "receipt commit denied" in capsys.readouterr().err
                assert actions == prior_actions
                assert ledger.progress(job).verified_marches == 3
                attempts = root / "reports" / hashlib.sha256(job.job_id.encode()).hexdigest()[:20]
                assert not (attempts / "attempt-000003.start.json").exists()
                monkeypatch.setattr(driver, "_write_recovery_record", original_receipt_writer)
            if crash_phase == "after_result":
                monkeypatch.setattr(driver, "_audit_closeout", original_audit)
            code = driver.main([
                "--launch-spec", str(launch), "--report-root", str(root / "reports"),
                "--max-ticks", "3" if crash_phase == "journal_mid" else "1", "--idle-delay-seconds", "0", "--settle-seconds", "0",
            ] + live_flag)
            recovered_output = capsys.readouterr()
            assert recovered_output.out, recovered_output.err
            result = json.loads(recovered_output.out)
            if crash_phase in {"before_result", "journal_fifth"}:
                assert result["reason"] == "durable five-march closeout recovered"
                assert result["ticks"] == 1
            elif crash_phase == "journal_mid":
                assert result["reason"] == "five VERIFIED marches closed"
                assert result["ticks"] == 2
            else:
                assert result["reason"] == "five VERIFIED marches closed"
                assert result["ticks"] == 3
                assert not (Path(result["report_path"]).parent / "attempt-000003.start.json").exists()
        else:
            code = second_code
            result = json.loads(second_output.out)
            assert result["ticks"] == 3
        assert code == 0 and result["status"] == "complete"
        assert result["verified_marches"] == 5
        assert result["audit_status"] == "OFFLINE_REPLAY_PASS"
        run_ids = [gather_slot_run_id(job, sequence) for sequence in range(1, 6)]
        assert [item["run_id"] for item in first["history"]] == run_ids[:2]
        if crash_phase == "none":
            assert [item["run_id"] for item in result["history"]] == run_ids[2:]
        assert [item["run_id"] for item in result["closeout"]] == run_ids
        assert [item["after_count"] for item in ledger.verifications(job)] == [1, 2, 3, 4, 5]
        assert actions == [(run_id, "MARCH_WITH_CURRENT_SELECTION") for run_id in run_ids]
        assert attestation_checks.count(None) == (2 if crash_phase == "none" else 4 if crash_phase == "journal_mid" else 3)
        assert attestation_checks.count(ATTESTATION_SHA) >= len(tick_calls) * 2
        assert all(command[command.index("--startup-attestation-sha256") + 1]
                   == ATTESTATION_SHA for command in tick_calls)
        assert [item[0] for item in host_traces] == run_ids
        assert len({item[1] for item in host_traces}) == 5
        traced_commands = [command for command in tick_calls
                           if "--input-isolation-evidence" in command]
        assert len(traced_commands) == 5
        assert all(("--arm-live" in command) is arm_live for command in traced_commands)
        assert [command[command.index("--resource-type") + 1] for command in traced_commands] == list(job.resource_schedule)
        if crash_phase == "none":
            assert [item["resource_type"] for item in first["history"] + result["history"]] == list(job.resource_schedule)
        assert all(command[command.index("--input-isolation-evidence") + 1]
                   == str(host_traces[index][1])
                   for index, command in enumerate(traced_commands))
        if crash_phase == "after_result":
            assert len(tick_calls) == 5
        assert Path(result["report_path"]).is_file()
        assert Path(result["verdict_path"]).is_file()
        already_code = driver.main([
            "--launch-spec", str(launch), "--report-root", str(root / "reports"),
            "--max-ticks", "1", "--idle-delay-seconds", "0", "--settle-seconds", "0",
        ] + live_flag)
        assert already_code == 2
        assert "immutable FIRST DONE verdict" in capsys.readouterr().err
        assert ledger.progress(job).dispatched_marches == 5
        assert len(actions) == 5
        if crash_phase.startswith("journal_"):
            from scripts.audit_first_done_job import audit_first_done_job, _recovery_path
            sequence = 3 if crash_phase == "journal_mid" else 5
            recovery_path = _recovery_path(evidence_root, job, sequence)
            original_receipt = json.loads(recovery_path.read_text())
            report_path = Path(result["report_path"])
            original_report = json.loads(report_path.read_text())
            from scripts.audit_first_done_job import _recovery_origin
            source_path = Path(original_receipt["source_path"])
            source_record = json.loads(source_path.read_text())
            wrong_origin = report_path.parent / "attempt-000001.start.json"
            with pytest.raises(ValueError, match="different originating attempt"):
                _recovery_origin(report_path.parent, source_record, job, source_path, sequence, wrong_origin)
            def audit_recovery():
                return audit_first_done_job(job, ledger, JsonMissionStore(checkpoint_root),
                                            original_report, evidence_root, attempt_root=report_path.parent)
            assert audit_recovery()["status"] == "OFFLINE_REPLAY_PASS"
            recovery_path.unlink()
            assert audit_recovery()["status"] == "BLOCKED"
            for field, damaged in [("source_sha256", "0" * 64), ("checkpoint_sha256", "0" * 64),
                                   ("startup_attestation_sha256", "0" * 64),
                                   ("attempt_start_path", str(root / "unrelated.start.json")),
                                   ("reservation", {}), ("journal_entry", {})]:
                recovery_path.write_text(json.dumps({**original_receipt, field: damaged}))
                assert audit_recovery()["status"] == "BLOCKED", field
            recovery_path.write_text(json.dumps(original_receipt))
            assert audit_recovery()["status"] == "OFFLINE_REPLAY_PASS"
        if crash_phase == "none":
            # The closeout must reject a persisted slot artifact that now claims
            # a different resource, even though its 1/5..5/5 chain still exists.
            from scripts.audit_first_done_job import audit_first_done_job
            report_path = Path(result["report_path"])
            recorded_report = json.loads(report_path.read_text(encoding="utf-8"))
            slot_three = Path(result["history"][0]["evidence_path"])
            recorded_tick = json.loads(slot_three.read_text(encoding="utf-8"))
            recorded_tick["runtime"]["gather_job"]["resource_type"] = "FOOD"
            slot_three.write_text(json.dumps(recorded_tick), encoding="utf-8")
            tampered = audit_first_done_job(
                job, ledger, JsonMissionStore(checkpoint_root), recorded_report,
                evidence_root, attempt_root=report_path.parent,
            )
            assert tampered["status"] == "BLOCKED"


def test_launch_spec_rejects_changed_artifact_before_tick(monkeypatch):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="digest-job", task_id="task", character_id="character",
            resource_type="WOOD", resource_level=4,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        launch = write_launch_spec(
            root / "job.launch.json", driver.ROOT / "workspace", artifact,
            resource_type="WOOD", resource_level=4,
        )
        artifact.write_text(artifact.read_text(encoding="utf-8") + " ", encoding="utf-8")
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("no tick allowed"))
        assert driver.main(["--launch-spec", str(launch)]) == 2


def test_mixed_launch_rejects_changed_schedule_and_tick_refuses_wrong_slot(monkeypatch):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="mixed-refusal", task_id="task", character_id="character",
            resource_level=5, starts_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        launch = write_launch_spec(root / "job.launch.json", driver.ROOT / "workspace",
                                   artifact, resource_level=5)
        args, job = driver._validated_launch(build_parser().parse_args(["--launch-spec", str(launch)]))
        assert job.resource_for_slot(1) == "GOLD"
        assert job.resource_for_slot(3) == "WOOD"
        spec = json.loads(launch.read_text(encoding="utf-8"))
        spec["resource_schedule"][2] = "FOOD"
        launch.write_text(json.dumps(spec), encoding="utf-8")
        with pytest.raises(ValueError, match="schedule"):
            driver._validated_launch(build_parser().parse_args(["--launch-spec", str(launch)]))
        monkeypatch.setattr(run_gather_tick, "validate_canonical_startup_attestation",
                            lambda *a, **k: ATTESTATION_SHA)
        monkeypatch.setattr(run_gather_tick, "GATHER_JOB_STORE_ROOT", root / "ledger")
        out = StringIO()
        with redirect_stderr(out):
            code = run_gather_tick.main([
                "--gather-job", str(artifact), "--task-id", "task",
                "--character-id", "character", "--resource-type", "WOOD",
                "--resource-level", "5",
            ])
        assert code != 0
        assert "scheduled slot" in out.getvalue()


def test_launch_spec_rejects_resource_change_even_with_intact_artifact(monkeypatch):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="resource-job", task_id="task", character_id="character",
            resource_type="WOOD", resource_level=4,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        launch = write_launch_spec(
            root / "job.launch.json", driver.ROOT / "workspace", artifact,
            resource_type="WOOD", resource_level=4,
        )
        spec = json.loads(launch.read_text(encoding="utf-8"))
        spec["resource_type"] = "FOOD"
        launch.write_text(json.dumps(spec), encoding="utf-8")
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("no tick allowed"))
        assert driver.main(["--launch-spec", str(launch)]) == 2


@pytest.mark.parametrize("deny", [False, True])
@pytest.mark.parametrize("reserved", [0, 1])
def test_pending_resume_reuses_open_start_only_after_preflight(monkeypatch, deny, reserved):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(job_id="pending-open", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5, starts_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=20))
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        job = load_gather_job_authority(artifact, canonical_actions=frozenset(scope["allowed_actions"]),
                                       expected_catalog_digest=scope["catalog_digest"])
        monkeypatch.setattr(driver, "GATHER_JOB_STORE_ROOT", root / "ledger")
        monkeypatch.setattr(driver, "GATHER_CHECKPOINT_ROOT", root / "checkpoints")
        monkeypatch.setattr(driver, "GATHER_EVIDENCE_ROOT", root / "evidence")
        path, start = driver._write_attempt_start(root / "reports", job, ATTESTATION_SHA)
        original = path.read_bytes()
        from harness.gather_job_authority import GatherJobProgress
        monkeypatch.setattr(JsonGatherJobStore, "progress",
                            lambda *_: GatherJobProgress(job.job_id, reserved, verified_marches=0))
        checks = []
        def admission(checked_job, ledger, checkpoints, attempt_root, evidence_root):
            checks.append((checked_job, attempt_root, evidence_root))
            assert ledger.root == root / "ledger"
            if deny:
                raise ValueError("invalid pending proof")
        monkeypatch.setattr(auditor, "preflight_attempt_chain", admission)
        if deny:
            with pytest.raises(ValueError, match="invalid pending proof"):
                driver._write_attempt_start(root / "reports", job, ATTESTATION_SHA)
        else:
            resumed_path, resumed_start = driver._write_attempt_start(root / "reports", job, ATTESTATION_SHA)
            assert resumed_path == path and resumed_start == start
        assert checks == [(job, path.parent, root / "evidence")]
        assert path.read_bytes() == original
        assert list(path.parent.glob("attempt-*.json")) == [path]
        with pytest.raises(ValueError, match="attestation differs"):
            driver._write_attempt_start(root / "reports", job, "f" * 64)
        assert path.read_bytes() == original


@pytest.mark.parametrize("authority", ["expired", "revoked"])
def test_open_unchanged_attempt_requires_active_authority(monkeypatch, tmp_path, authority):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(job_id="open-authority", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5, starts_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=20))
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        job = load_gather_job_authority(artifact, canonical_actions=frozenset(scope["allowed_actions"]),
                                       expected_catalog_digest=scope["catalog_digest"])
        monkeypatch.setattr(driver, "GATHER_JOB_STORE_ROOT", root / "ledger")
        path, start = driver._write_attempt_start(root / "reports", job, ATTESTATION_SHA)
        original = path.read_bytes()
        from harness.gather_job_authority import GatherJobProgress
        monkeypatch.setattr(JsonGatherJobStore, "progress", lambda *_: GatherJobProgress(
            job.job_id, 0, revoked=authority == "revoked", verified_marches=0))
        if authority == "expired":
            class ExpiredClock(datetime):
                @staticmethod
                def now(_):
                    return job.expires_at
            monkeypatch.setattr(driver, "datetime", ExpiredClock)
        monkeypatch.setattr(auditor, "preflight_attempt_chain", lambda *_: pytest.fail("inactive admission"))
        with pytest.raises(ValueError, match="outside active job authority"):
            driver._write_attempt_start(root / "reports", job, ATTESTATION_SHA)
        assert path.read_bytes() == original
        assert list(path.parent.glob("attempt-*.json")) == [path]


def test_attempt_preflight_failure_never_launches_a_tick(monkeypatch, capsys):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="preflight-block-job", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        monkeypatch.setattr(driver, "GATHER_JOB_STORE_ROOT", root / "ledger")
        monkeypatch.setattr(driver, "validate_canonical_startup_attestation",
                            lambda *a, **k: ATTESTATION_SHA)
        monkeypatch.setattr(auditor, "preflight_attempt_chain",
                            lambda *_: (_ for _ in ()).throw(ValueError("damaged prior attempt")))
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("no tick allowed"))
        code = driver.main([
            "--gather-job", str(artifact), "--task-id", "task",
            "--character-id", "character", "--resource-type", "FOOD",
            "--resource-level", "5", "--report-root", str(root / "reports"),
        ])
        assert code == 2
        assert "damaged prior attempt" in capsys.readouterr().err


def test_automatic_blocked_audit_is_non_success_and_write_once(monkeypatch, capsys):
    with TemporaryDirectory(dir=driver.ROOT / "workspace") as folder:
        root = Path(folder)
        now = datetime.now(timezone.utc)
        scope = build_artifact(
            job_id="audit-block-job", task_id="task", character_id="character",
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        monkeypatch.setattr(driver, "GATHER_JOB_STORE_ROOT", root / "ledger")
        monkeypatch.setattr(driver, "GATHER_CHECKPOINT_ROOT", root / "checkpoints")
        monkeypatch.setattr(driver, "GATHER_EVIDENCE_ROOT", root / "evidence")
        monkeypatch.setattr(driver, "validate_canonical_startup_attestation",
                            lambda *a, **k: ATTESTATION_SHA)
        monkeypatch.setattr(driver, "drive_job", lambda *_, **__: {
            "status": "complete", "reason": "synthetic false closeout",
            "job_id": scope["job_id"], "ticks": 0, "verified_marches": 5,
            "history": [], "closeout": [],
        })
        monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("no tick allowed"))
        args = [
            "--gather-job", str(artifact), "--task-id", "task",
            "--character-id", "character", "--resource-type", "FOOD",
            "--resource-level", "5", "--report-root", str(root / "reports"),
        ]
        assert driver.main(args) == 4
        output = json.loads(capsys.readouterr().out)
        assert output["audit_status"] == "BLOCKED"
        verdict_path = Path(output["verdict_path"])
        original = verdict_path.read_bytes()
        assert json.loads(original)["status"] == "BLOCKED"
        assert driver.main(args) == 2
        assert "immutable FIRST DONE verdict" in capsys.readouterr().err
        assert verdict_path.read_bytes() == original
