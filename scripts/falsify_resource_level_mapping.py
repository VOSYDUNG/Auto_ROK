"""Empirical linear mapping falsification for RESOURCE_SEARCH_PANEL (B002).

Captures live BEFORE frame, verifies SEARCH_LEVEL_CONTROL grounding,
dispatches SET_RESOURCE_LEVEL(N) through GatherScreenMappedActionSurface with
WindowsForegroundInterferenceGuard(armed=True), captures fresh AFTER frame,
and verifies AFTER.selected_search_level == N.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if r"C:\Shin\CEO-OS\Auto_ROK" not in sys.path:
    sys.path.insert(0, r"C:\Shin\CEO-OS\Auto_ROK")

from harness.action_surface import ActionRequest
from harness.gather_facts import GatherFactObservationProvider
from harness.human_io import MouseAction
from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider
from harness.mission_runtime import ActionChoice, MissionContext, ToolSnapshot
from harness.ocr_semantics import OcrSemanticObservationProvider
from harness.resource_level_control import (
    ACTION_ID,
    TARGET_ID,
    GatherScreenMappedActionSurface,
    ResourceLevelControlObservationProvider,
    ResourceLevelProfile,
)
from harness.windows_input import WindowsHumanInputActuator
from harness.windows_interference_guard import WindowsForegroundInterferenceGuard
from harness.windows_live_observation import WindowsLiveObservationProvider


def build_pipeline(
    workspace_root: Path,
    profile_path: Path,
    main_view_profile_path: Path,
    character_id: str = "one-character",
):
    resource_level_profile = ResourceLevelProfile.load(profile_path)
    main_view_profile = MainViewProfile.load(main_view_profile_path)

    provider = WindowsLiveObservationProvider(workspace_root)
    provider = OcrSemanticObservationProvider(provider, ())
    provider = MainViewVisualObservationProvider(provider, main_view_profile)
    provider = ResourceLevelControlObservationProvider(provider, resource_level_profile)
    provider = GatherFactObservationProvider(provider, character_id=character_id)
    return provider, resource_level_profile


def attach_desktop():
    u32 = ctypes.WinDLL("user32")
    hdesk = u32.OpenInputDesktop(0, False, 0x1FF)
    if hdesk:
        u32.SetThreadDesktop(hdesk)


def test_level(
    level: int,
    workspace_root: Path,
    profile_path: Path,
    main_view_profile_path: Path,
    armed: bool = True,
) -> dict:
    attach_desktop()
    provider, profile = build_pipeline(workspace_root, profile_path, main_view_profile_path)
    context_before = MissionContext("GATHER_RESOURCE", "b002-test", f"lvl{level}-before")

    # 1. BEFORE frame
    bundle_before = provider.observe(context_before)
    target = bundle_before.scene.target(TARGET_ID)
    rlc_fact_before = bundle_before.scene.facts.get("resource_level_control", {})
    grounded = target is not None and rlc_fact_before.get("status") == "grounded"
    before_level = bundle_before.scene.facts.get("selected_search_level")

    if not grounded:
        return {
            "level": level,
            "status": "FAIL",
            "reason": f"SEARCH_LEVEL_CONTROL not grounded (missing anchors: {rlc_fact_before.get('missing_anchors')})",
            "before_frame_id": bundle_before.observation.frame_id,
        }

    # 2. Resolve requested level
    surface = GatherScreenMappedActionSurface({}, min_target_confidence=0.90)
    req = ActionRequest(ACTION_ID, TARGET_ID, {"resource_level": level})
    resolved = surface.resolve(req, scene=bundle_before.scene)

    # 3. Guard check
    guard = WindowsForegroundInterferenceGuard(armed=armed)
    snap = ToolSnapshot("GATHER_RESOURCE", "b002-test", bundle_before.observation.frame_id, "RESOURCE_SEARCH_PANEL")
    choice = ActionChoice(ACTION_ID, f"set resource level to {level}")
    check = guard.check(context_before, snap, choice, bundle_before.scene, resolved)

    if not check.allowed:
        return {
            "level": level,
            "status": "FAIL",
            "reason": f"guard rejected actuation: {check.code}",
            "guard_facts": check.facts,
        }

    # 4. Actuate click
    actuator = WindowsHumanInputActuator()
    actuator.perform(MouseAction("click", x=resolved.point[0], y=resolved.point[1], button="left"))
    time.sleep(0.6)

    # 5. AFTER frame
    context_after = MissionContext("GATHER_RESOURCE", "b002-test", f"lvl{level}-after")
    bundle_after = provider.observe(context_after)
    after_level = bundle_after.scene.facts.get("selected_search_level")

    frame_different = bundle_before.observation.frame_id != bundle_after.observation.frame_id
    level_verified = after_level == level

    return {
        "level": level,
        "status": "PASS" if (frame_different and level_verified) else "FAIL",
        "before_frame_id": bundle_before.observation.frame_id,
        "before_level": before_level,
        "resolved_click_point": list(resolved.point),
        "after_frame_id": bundle_after.observation.frame_id,
        "after_level": after_level,
        "frame_different": frame_different,
        "level_verified": level_verified,
        "target_bbox": [target.bbox.x1, target.bbox.y1, target.bbox.x2, target.bbox.y2] if target else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 3, 6])
    parser.add_argument("--profile", default=r"C:\Shin\CEO-OS\Auto_ROK\config\resource_level_profile.json")
    parser.add_argument("--main-view-profile", default=r"C:\Shin\CEO-OS\Auto_ROK\config\main_view_profiles.json")
    parser.add_argument("--workspace-root", default=r"C:\Shin\CEO-OS\Auto_ROK\workspace\runs")
    parser.add_argument("--arm-live", action="store_true", default=True)
    args = parser.parse_args()

    results = []
    for lvl in args.levels:
        print(f"--- Testing level {lvl} ---")
        res = test_level(
            lvl,
            Path(args.workspace_root),
            Path(args.profile),
            Path(args.main_view_profile),
            armed=args.arm_live,
        )
        print(json.dumps(res, indent=2))
        results.append(res)
        time.sleep(0.5)

    all_pass = all(r["status"] == "PASS" for r in results)
    out_file = Path(r"C:\Shin\CEO-OS\Auto_ROK\workspace\evidence\b002_falsification_report.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nFinal result: {'PASS' if all_pass else 'FAIL'} (saved to {out_file})")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
