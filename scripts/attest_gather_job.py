"""Record one offline startup assertion for an existing GATHER job and capture.

The operator must inspect the currently open character and affirm its exact
configured ID. This command reads stored evidence; it does not capture, tick,
arm input, or verify a character name from the UI.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_startup_attestation import (  # noqa: E402
    build_startup_attestation, canonical_startup_attestation_path,
    write_startup_attestation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-artifact", required=True, type=Path)
    parser.add_argument("--resource-type", required=True, choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--manifest", required=True, type=Path, help="native capture.json")
    parser.add_argument("--frame", required=True, type=Path, help="matching native PNG")
    parser.add_argument("--affirm-character-id", required=True,
                        help="explicit operator assertion of the character currently open in this capture")
    args = parser.parse_args(argv)
    try:
        record = build_startup_attestation(
            job_artifact=args.job_artifact, manifest_path=args.manifest,
            frame_path=args.frame,
            profile_path=ROOT / "config" / "queue_indicator_profile.json",
            ledger_root=ROOT / "workspace" / "checkpoints" / "gather-jobs",
            workspace_root=ROOT / "workspace",
            mission_flows=ROOT / "config" / "mission_flows.yaml",
            ui_states=ROOT / "config" / "ui_states.yaml",
            resource_type=args.resource_type, resource_level=args.resource_level,
            affirmative_character_id=args.affirm_character_id,
        )
        destination = write_startup_attestation(
            canonical_startup_attestation_path(record["job_id"], ROOT / "workspace"),
            ROOT / "workspace", record,
        )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"startup attestation refused: {exc}", file=sys.stderr)
        return 2
    print(f"startup attestation recorded offline: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
