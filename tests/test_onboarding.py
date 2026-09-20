"""The six phases, and which one is allowed to stop everything.

SRS ONB-001: all six run in order before any action decision.
SRS ONB-002: only phase 0 may block; phases 1-5 degrade and carry on.
SRS ONB-003: unverified knowledge entries are listed, never silently held.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from autorok.mission.ladder import Ladder, Rung
from autorok.onboarding import (
    BLOCKING_PHASE,
    Onboarding,
    OnboardingError,
    Outcome,
    Phase,
    PhaseFailure,
    PhaseResult,
    scan_unverified,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def _steps(overrides=None):
    calls: list[Phase] = []

    def make(phase: Phase):
        def step():
            calls.append(phase)
            return phase.name
        return step

    steps = {phase: make(phase) for phase in Phase}
    steps.update(overrides or {})
    return steps, calls


def _fail(message: str):
    def step():
        raise PhaseFailure(message)
    return step


class SequenceTests(unittest.TestCase):
    def test_all_six_run_in_order_and_then_deciding_is_permitted(self):
        steps, calls = _steps()
        run = Onboarding()
        results = run.run(steps, now=NOW)
        self.assertEqual(list(Phase), calls)
        self.assertEqual(list(Phase), [item.phase for item in results])
        self.assertTrue(run.may_decide)

    def test_a_missing_step_is_recorded_not_skipped(self):
        steps, _ = _steps()
        del steps[Phase.BUFF_CHECK]
        run = Onboarding()
        run.run(steps, now=NOW)
        buff = run.results[-1]
        self.assertIs(Phase.BUFF_CHECK, buff.phase)
        self.assertIs(Outcome.DEGRADED, buff.outcome)
        self.assertIn("no step supplied", buff.detail)

    def test_deciding_is_forbidden_before_a_run_happens_at_all(self):
        self.assertFalse(Onboarding().may_decide)

    def test_supplying_only_phase_zero_degrades_all_the_way_to_observe_only(self):
        """The five missing phases each cost a rung, which is the real guard.

        ``may_decide`` stays true - ONB-002 says phases 1-5 degrade rather
        than stop - but a run that established nothing lands on the floor,
        where OBSERVE_ONLY emits no input at all. Deciding is permitted; there
        is simply nothing left to decide but to watch.
        """
        ladder = Ladder()
        run = Onboarding(ladder)
        steps, _ = _steps()
        run.run({Phase.LOAD_KNOWLEDGE: steps[Phase.LOAD_KNOWLEDGE]}, now=NOW)
        self.assertEqual(len(Phase), len(run.results))
        self.assertEqual(len(Phase) - 1, len(run.degraded_phases()))
        self.assertTrue(run.may_decide)
        self.assertIs(Rung.OBSERVE_ONLY, ladder.current)
        self.assertFalse(ladder.current.emits_input)

    def test_a_rerun_does_not_inherit_the_previous_attempt(self):
        run = Onboarding()
        steps, _ = _steps()
        run.run(steps, now=NOW)
        self.assertTrue(run.may_decide)
        run.run({Phase.LOAD_KNOWLEDGE: _fail("knowledge/ is unreadable")}, now=NOW)
        self.assertFalse(run.may_decide)
        self.assertEqual(1, len(run.results))


class BlockingTests(unittest.TestCase):
    def test_phase_zero_failing_stops_the_run(self):
        steps, calls = _steps({Phase.LOAD_KNOWLEDGE: _fail("knowledge/ is unreadable")})
        run = Onboarding()
        results = run.run(steps, now=NOW)
        self.assertEqual([Phase.LOAD_KNOWLEDGE], [item.phase for item in results])
        self.assertIs(Outcome.BLOCKED, results[0].outcome)
        self.assertEqual([], calls)
        self.assertTrue(run.blocked)
        self.assertFalse(run.may_decide)

    def test_every_later_phase_degrades_instead_of_stopping(self):
        for phase in Phase:
            if phase is BLOCKING_PHASE:
                continue
            with self.subTest(phase=phase):
                steps, _ = _steps({phase: _fail(f"{phase.name} unreadable")})
                run = Onboarding()
                results = run.run(steps, now=NOW)
                self.assertEqual(len(Phase), len(results))
                self.assertFalse(run.blocked)
                self.assertEqual((phase,), run.degraded_phases())

    def test_a_degraded_phase_costs_exactly_one_rung(self):
        ladder = Ladder()
        steps, _ = _steps({Phase.SURVEY_CHARACTER: _fail("no profile and no client")})
        Onboarding(ladder).run(steps, now=NOW)
        self.assertIs(Rung.DEFAULT_FARM, ladder.current)
        self.assertEqual(1, len(ladder.history))
        self.assertIn("SURVEY_CHARACTER", ladder.history[0].reason)

    def test_two_degraded_phases_cost_two_rungs_not_a_jump(self):
        ladder = Ladder()
        steps, _ = _steps({
                Phase.SURVEY_CHARACTER: _fail("no profile"),
                Phase.BUFF_CHECK: _fail("buff panel did not open"),
            }
        )
        Onboarding(ladder).run(steps, now=NOW)
        self.assertIs(Rung.SCARCITY_FILL, ladder.current)

    def test_a_degraded_run_still_permits_deciding(self):
        """Knowing less is not the same as being unable to act."""
        steps, _ = _steps({Phase.BUFF_CHECK: _fail("buff panel did not open")})
        run = Onboarding()
        run.run(steps, now=NOW)
        self.assertTrue(run.may_decide)

    def test_no_phase_other_than_zero_can_even_be_marked_blocked(self):
        with self.assertRaises(OnboardingError):
            PhaseResult(
                phase=Phase.FLEET_STATE,
                outcome=Outcome.BLOCKED,
                detail="troop table unreadable",
                at=NOW,
            )
        # And phase 0 may.
        self.assertIs(
            Outcome.BLOCKED,
            PhaseResult(
                phase=Phase.LOAD_KNOWLEDGE,
                outcome=Outcome.BLOCKED,
                detail="knowledge/ is unreadable",
                at=NOW,
            ).outcome,
        )


class PhaseResultContractTests(unittest.TestCase):
    def test_a_result_without_a_detail_cannot_be_built(self):
        for blank in ("", "   "):
            with self.assertRaises(OnboardingError):
                PhaseResult(Phase.LOCATE, Outcome.COMPLETE, blank, NOW)

    def test_a_naive_timestamp_is_refused(self):
        with self.assertRaises(OnboardingError):
            PhaseResult(
                Phase.LOCATE, Outcome.COMPLETE, "ok", datetime(2026, 9, 20, 7, 0)
            )

    def test_the_value_a_phase_established_is_carried_forward(self):
        steps, _ = _steps({Phase.LOCATE: lambda: {"character_id": "char-3"}})
        run = Onboarding()
        run.run(steps, now=NOW)
        located = next(item for item in run.results if item.phase is Phase.LOCATE)
        self.assertEqual({"character_id": "char-3"}, located.value)


class UnverifiedScanTests(unittest.TestCase):
    def test_the_real_knowledge_tree_declares_what_it_is_unsure_of(self):
        entries = scan_unverified(ROOT / "knowledge")
        self.assertTrue(entries)
        files = {item.source_file for item in entries}
        self.assertIn("courier_station_2026-09-19.yaml", files)
        self.assertIn("farming_workflow_2026-09-19.yaml", files)
        for item in entries:
            self.assertIn(item.marker, ("UNVERIFIED", "NEEDS_CONFIRMATION"))
            self.assertGreater(item.line, 0)

    def test_unverified_entries_do_not_block_phase_zero(self):
        """Knowing what it does not know is the point, not a failure."""
        steps, _ = _steps({Phase.LOAD_KNOWLEDGE: lambda: scan_unverified(ROOT / "knowledge")}
        )
        run = Onboarding()
        run.run(steps, now=NOW)
        self.assertTrue(run.may_decide)
        self.assertTrue(run.results[0].value)

    def test_a_clean_tree_reports_nothing_rather_than_failing(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "clean.yaml").write_text("schema_version: 1\n", encoding="utf-8")
            self.assertEqual((), scan_unverified(tmp))

    def test_a_missing_directory_is_an_error_not_an_empty_list(self):
        with self.assertRaises(OnboardingError):
            scan_unverified(ROOT / "knowledge_that_does_not_exist")

    def test_the_summary_names_every_phase_and_the_verdict(self):
        steps, _ = _steps({Phase.BUFF_CHECK: _fail("buff panel did not open")})
        run = Onboarding()
        run.run(steps, now=NOW)
        summary = run.summarise()
        self.assertTrue(summary["may_decide"])
        self.assertEqual(len(Phase), len(summary["phases"]))
        self.assertEqual("DEGRADED", summary["phases"][-1]["outcome"])


if __name__ == "__main__":
    unittest.main()
