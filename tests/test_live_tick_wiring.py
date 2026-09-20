"""Every sensor the graph calls implemented must be reachable from the tick.

This exists because it happened twice in one day, the same way both times.

``QueueIndicatorObservationProvider`` was written in M3, tested, measured at
0.207 ms, registered in the engineering graph as implemented - and imported
by nothing. The live tick went on reading the queue from whole-frame OCR,
which is precisely the source the template reader was built to replace.
Completion is evidenced by the queue count RISING, so a successful march
could never be proven and the runner kept ticking: 64 wasted ticks across a
day's runs, the largest single bucket.

``--ocr-backend`` defaulted to the PowerShell path while the comment beside
that branch said it was "not for live ticks", so the 93 ms in-process OCR
measured in M3 was never what ran, and neither were the calibrated regions
added on top of it.

Both passed their own tests. Tests prove a component works; they do not
prove anything calls it. That is what this file is for.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TICK = ROOT / "scripts" / "run_gather_tick.py"

#: Providers that must appear in the live observation chain, with the reason
#: each one is load-bearing rather than optional.
REQUIRED_PROVIDERS = {
    "OcrSemanticObservationProvider": "assembles phrases; targets ground from them",
    "QueueIndicatorObservationProvider": "the queue fact completion is proven by",
    "MainViewVisualObservationProvider": "CITY_VIEW",
    "MapCoordinateObservationProvider": "WORLD_MAP_VIEW, which the visual detector cannot carry",
    "ResourceLevelControlObservationProvider": "the level slider, panel-relative",
    "GatherFactObservationProvider": "turns evidence into the facts the engine reads",
}


def _source() -> str:
    return TICK.read_text(encoding="utf-8")


@pytest.mark.parametrize("provider,why", sorted(REQUIRED_PROVIDERS.items()))
def test_the_provider_is_imported_and_called(provider, why):
    source = _source()
    tree = ast.parse(source)

    imported = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == provider for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imported, f"{provider} is not imported by run_gather_tick ({why})"

    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == provider
        for node in ast.walk(tree)
    )
    assert called, (
        f"{provider} is imported but never constructed, so it is not in the "
        f"observation chain ({why}). An unreachable sensor is not a sensor."
    )


def test_the_live_ocr_backend_is_the_in_process_one():
    """The PowerShell path is for replay. The default must not be it."""
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        args = [a for a in node.args if isinstance(a, ast.Constant)]
        if not any(a.value == "--ocr-backend" for a in args):
            continue
        default = next(
            (kw.value.value for kw in node.keywords
             if kw.arg == "default" and isinstance(kw.value, ast.Constant)),
            None,
        )
        assert default == "windows_direct", (
            f"--ocr-backend defaults to {default!r}; the in-process backend is "
            "the one that reads the calibrated regions, and the PowerShell "
            "path is kept only for replaying stored evidence"
        )
        return
    pytest.fail("--ocr-backend argument not found in run_gather_tick")


def test_every_implemented_perception_node_is_reachable_or_declares_why_not():
    """A graph node marked implemented should be wired, or say it is not.

    Not every perception module belongs in the gather tick - viewport_change
    serves the ladder, windows_ocr_direct is called through the observation
    provider rather than directly. Those are legitimate. What is not
    legitimate is a node that looks wired and is not, which is the case this
    catches by forcing each exemption to be written down.
    """
    import yaml

    graph = yaml.safe_load((ROOT / "config" / "engineering_graph.yaml").read_text(encoding="utf-8"))
    source = _source()

    #: Reached by something other than the gather tick, named here on purpose.
    ELSEWHERE = {
        "viewport_change_detector": "feeds the degradation ladder, not the gather flow",
        "windows_ocr_direct": "called by windows_live_observation, not the tick",
        "march_queue_indicator": "wired via QueueIndicatorObservationProvider",
        "map_coordinate_detector": "wired via MapCoordinateObservationProvider",
        "rapidocr_fixed_roi_backend": "experiment backend, opt-in",
        "city_world_visual_detector": "wired via MainViewVisualObservationProvider",
        "main_view_training_profile": "a trained profile, not a runtime component",
        "live_capture": "wired via WindowsLiveObservationProvider",
        "windows_ocr": "the PowerShell replay path",
        "alliance_claim_classifier": "serves run_alliance_claim_tick, a different mission",
    }

    unreachable = []
    for node in graph.get("nodes", []):
        if node.get("kind") != "perception" or node.get("status") != "implemented":
            continue
        node_id = node["id"]
        if node_id in ELSEWHERE:
            continue
        module = Path(str(node.get("path", ""))).stem
        if module and module not in source:
            unreachable.append(node_id)

    assert not unreachable, (
        "these perception nodes are marked implemented but nothing in the live "
        f"tick references them: {unreachable}. Wire them, or add them to "
        "ELSEWHERE with the reason they live somewhere else."
    )
