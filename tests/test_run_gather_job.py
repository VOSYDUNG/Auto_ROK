"""The outer driver consumes canonical tick results without using game input."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from harness.gather_job_coordinator import gather_slot_run_id
from harness.gather_job_store import load_gather_job_authority
from harness.gather_job_store import JsonGatherJobStore
from harness.mission_runner import MissionTickResult
from harness.mission_runtime import AllowedAction, ToolFeedback, ToolSnapshot
from harness.mission_store import CheckpointStatus, MissionCheckpoint
from scripts.create_gather_job import build_artifact, write_artifact, write_launch_spec
from scripts import run_gather_job as driver
from scripts import run_gather_tick
from scripts import audit_first_done_job as auditor
from scripts.run_gather_job import build_parser, drive_job, _tick_command


JOB = "one-startup-job"


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
    command = _tick_command(args)
    assert "--gather-job" in command
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


def test_live_arm_is_rejected_before_any_tick(monkeypatch, capsys):
    monkeypatch.setattr(driver, "_subprocess_tick", lambda _: pytest.fail("tick must not run"))
    code = driver.main([
        "--gather-job", "workspace/jobs/not-read.json", "--task-id", "task",
        "--character-id", "char", "--resource-type", "FOOD", "--arm-live",
    ])
    assert code == 2
    assert "job-scoped preflight" in capsys.readouterr().err


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


@pytest.mark.parametrize("crash_phase", ["none", "before_result", "after_result"])
def test_driver_launch_spec_drives_five_real_canonical_ticks_and_journal(
    monkeypatch, capsys, crash_phase,
):
    """Only observation and actuation are synthetic; CLI, runner and journal are real."""
    window = {"hwnd": 1001, "pid": 2001, "process_path": r"C:\Game\MASS.exe"}
    precondition = "troop/commander selection policy is valid for this mission"
    actions = []
    tick_calls = []
    starts = datetime.now(timezone.utc).timestamp()
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
            resource_type="FOOD", resource_level=5,
            starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=20),
        )
        artifact = write_artifact(root / "job.json", driver.ROOT / "workspace", scope)
        launch = write_launch_spec(
            root / "job.launch.json", driver.ROOT / "workspace", artifact,
            resource_type="FOOD", resource_level=5,
        )
        job = load_gather_job_authority(
            artifact, canonical_actions=frozenset(scope["allowed_actions"]),
            expected_catalog_digest=scope["catalog_digest"],
        )
        ledger = JsonGatherJobStore(ledger_root)
        ledger.bind_client(job, window)
        assert ledger.progress(job).verified_marches == 0

        class SyntheticTool:
            def __init__(self, sequence):
                self.sequence = sequence
                self.observations = 0
                self.start = starts + sequence * 3

            def observe(self, context):
                self.observations += 1
                if self.observations == 1:
                    image_hash = f"{self.sequence:064x}"
                    baseline = {
                        "predicate_id": "march_queue_used_increased",
                        "counter_fact": "march_queue_used", "counter_value": self.sequence - 1,
                        "capacity": 5, "source_frame_id": f"baseline-{self.sequence}",
                        "source": "visible_ocr_queue_anchor", "character_id": job.character_id,
                        "source_timestamp": self.start,
                    }
                    return ToolSnapshot(
                        context.mission_id, context.task_id, f"before-{self.sequence}",
                        "NEW_TROOP_SETUP",
                        facts={"completion_baseline": baseline, "character_id": job.character_id,
                               "window": window, "image_sha256": image_hash,
                               "new_troop_formation_ready": True,
                               "new_troop_formation_source":
                                   "same_frame_new_troop_ocr_and_pixels_1366x768",
                               "new_troop_formation_frame_id": f"before-{self.sequence}",
                               "new_troop_formation_image_sha256": image_hash,
                               "precondition_evidence": {precondition: True}},
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
                        observed_at=self.start + 1,
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
            with redirect_stdout(output):
                code = run_gather_tick.main(command[2:] + [
                    "--checkpoint-root", str(checkpoint_root),
                    "--evidence-root", str(evidence_root),
                ])
            return code, json.loads(output.getvalue())

        monkeypatch.setattr(driver, "_subprocess_tick", canonical_tick)
        first_code = driver.main([
            "--launch-spec", str(launch), "--report-root", str(root / "reports"),
            "--max-ticks", "2", "--idle-delay-seconds", "0", "--settle-seconds", "0",
        ])
        first = json.loads(capsys.readouterr().out)
        assert first_code == 3 and first["status"] == "suspended"
        assert first["verified_marches"] == 2 and first["ticks"] == 2
        assert first["audit_status"] is None
        original_write = driver._write_report
        original_audit = driver._audit_closeout
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
        ])
        second_output = capsys.readouterr()
        if crash_phase != "none":
            assert second_code == 2 and "synthetic crash" in second_output.err
            if crash_phase == "after_result":
                monkeypatch.setattr(driver, "_audit_closeout", original_audit)
            code = driver.main([
                "--launch-spec", str(launch), "--report-root", str(root / "reports"),
                "--max-ticks", "1", "--idle-delay-seconds", "0", "--settle-seconds", "0",
            ])
            recovered_output = capsys.readouterr()
            assert recovered_output.out, recovered_output.err
            result = json.loads(recovered_output.out)
            if crash_phase == "before_result":
                assert result["reason"] == "durable five-march closeout recovered"
                assert result["ticks"] == 1
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
        if crash_phase == "after_result":
            assert len(tick_calls) == 5
        assert Path(result["report_path"]).is_file()
        assert Path(result["verdict_path"]).is_file()
        already_code = driver.main([
            "--launch-spec", str(launch), "--report-root", str(root / "reports"),
            "--max-ticks", "1", "--idle-delay-seconds", "0", "--settle-seconds", "0",
        ])
        assert already_code == 2
        assert "immutable FIRST DONE verdict" in capsys.readouterr().err
        assert ledger.progress(job).dispatched_marches == 5
        assert len(actions) == 5


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
