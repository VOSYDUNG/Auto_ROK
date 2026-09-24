"""A startup job is issued once from the real GATHER catalog without input."""
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import json

import pytest

from harness.gather_job_store import load_gather_job_authority
from scripts import create_gather_job
from scripts.create_gather_job import build_artifact, write_artifact, write_launch_spec


def artifact():
    now = datetime.now(timezone.utc)
    return build_artifact(
        job_id="first-done-01", task_id="one-character",
        character_id="governor-attested", resource_type="FOOD", resource_level=5,
        starts_at=now, expires_at=now + timedelta(minutes=45),
    )


def test_startup_artifact_loads_with_compiled_scope_and_cannot_be_overwritten(tmp_path):
    scope = artifact()
    destination = tmp_path / "workspace" / "jobs" / "first-done.json"
    written = write_artifact(destination, tmp_path / "workspace", scope)
    loaded = load_gather_job_authority(
        written, canonical_actions=frozenset(scope["allowed_actions"]),
        expected_catalog_digest=scope["catalog_digest"],
    )
    assert loaded.job_id == "first-done-01"
    assert loaded.max_marches == 5
    assert "MARCH_WITH_CURRENT_SELECTION" in loaded.allowed_actions
    assert "DELETE_ACCOUNT" not in loaded.allowed_actions
    original = written.read_bytes()
    with pytest.raises(FileExistsError):
        write_artifact(destination, tmp_path / "workspace", scope)
    assert written.read_bytes() == original


def test_startup_artifact_rejects_external_path_and_invalid_time(tmp_path):
    scope = artifact()
    with pytest.raises(ValueError, match="under workspace"):
        write_artifact(tmp_path / "outside.json", tmp_path / "workspace", scope)
    assert not (tmp_path / "outside.json").exists()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="time window"):
        build_artifact(
            job_id="expired", task_id="one-character", character_id="a",
            resource_type="FOOD", resource_level=5,
            starts_at=now, expires_at=now - timedelta(seconds=1),
        )


def test_launch_spec_keeps_resource_parameters_outside_exact_authority_schema(tmp_path):
    scope = artifact()
    workspace = tmp_path / "workspace"
    job_path = write_artifact(workspace / "jobs" / "job.json", workspace, scope)
    launch_path = write_launch_spec(
        workspace / "jobs" / "job.launch.json", workspace, job_path,
        resource_type="FOOD", resource_level=5,
    )
    import hashlib

    spec = json.loads(launch_path.read_text(encoding="utf-8"))
    assert spec["job_artifact_sha256"] == hashlib.sha256(job_path.read_bytes()).hexdigest()
    assert spec["resource_type"] == "FOOD" and spec["resource_level"] == 5
    assert "resource_type" not in scope and "resource_level" not in scope
    with pytest.raises(FileExistsError):
        write_launch_spec(launch_path, workspace, job_path, resource_type="WOOD", resource_level=1)


def test_issuer_cli_outputs_one_launch_spec_for_same_startup_scope(capsys):
    with TemporaryDirectory(dir=create_gather_job.ROOT / "workspace") as folder:
        artifact = create_gather_job.Path(folder) / "job.json"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        code = create_gather_job.main([
            "--job-id", "issuer-cli", "--task-id", "task", "--character-id", "character",
            "--resource-type", "STONE", "--resource-level", "4",
            "--expires-at", expires, "--output", str(artifact),
        ])
        result = json.loads(capsys.readouterr().out)
        assert code == 0 and result["status"] == "created_offline"
        spec = json.loads(create_gather_job.Path(result["launch_path"]).read_text(encoding="utf-8"))
        assert spec["job_artifact"] == str(artifact.resolve())
        assert spec["resource_type"] == "STONE" and spec["resource_level"] == 4
        assert "resource_type" not in json.loads(artifact.read_text(encoding="utf-8"))


@pytest.mark.parametrize("launch_failure", ["collision", "outside_workspace"])
def test_failed_issuer_does_not_leave_usable_authority(capsys, launch_failure):
    with TemporaryDirectory(dir=create_gather_job.ROOT / "workspace") as folder:
        artifact = create_gather_job.Path(folder) / "job.json"
        launch = create_gather_job.Path(folder) / "job.launch.json"
        if launch_failure == "collision":
            launch.write_text("occupied", encoding="utf-8")
        else:
            launch = create_gather_job.ROOT.parent / "outside-launch.json"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        code = create_gather_job.main([
            "--job-id", "failed-issuer", "--task-id", "task", "--character-id", "character",
            "--resource-type", "STONE", "--resource-level", "4",
            "--expires-at", expires, "--output", str(artifact),
            "--launch-output", str(launch),
        ])
        assert code == 2
        assert not artifact.exists()
        assert "failed" in capsys.readouterr().err
