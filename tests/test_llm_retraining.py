"""Change detection, and the line the model may not cross.

SRS LLM-008: a retraining signal names what changed AND the frame that proves
it; missing either is not a signal.
SRS LLM-009: the model proposes knowledge, the operator writes it. Enforced
here by code that refuses, not by a convention in a document.
"""
from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from autorok.llm.retraining import (
    PROTECTED_DIRECTORY,
    ChangeTrigger,
    KnowledgeProposal,
    ProposalLog,
    ProposalStatus,
    RetrainingError,
    RetrainingSignal,
    from_persistent_degradation,
    proposal_path,
    self_proposed_share,
    write_proposal,
)
from autorok.mission.ladder import Ladder

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def _signal(**kwargs) -> RetrainingSignal:
    payload = {
        "trigger": ChangeTrigger.CONTROL_ABSENT,
        "what_changed": "the USE button is gone from the item detail panel",
        "evidence_frame_id": "frame-8821",
        "observed_at": NOW,
    }
    payload.update(kwargs)
    return RetrainingSignal(**payload)


def _proposal(**kwargs) -> KnowledgeProposal:
    payload = {
        "proposal_id": "prop-001",
        "signal": _signal(),
        "target_knowledge_file": "gathering_continuity_2026-09-19.yaml",
        "entry": {"control": "USE", "status": "ABSENT_SINCE_2026-09-20"},
        "rationale": "the documented item path no longer has its confirm control",
    }
    payload.update(kwargs)
    return KnowledgeProposal(**payload)


class SignalContractTests(unittest.TestCase):
    def test_a_signal_without_what_changed_cannot_be_built(self):
        for blank in ("", "   "):
            with self.assertRaises(RetrainingError):
                _signal(what_changed=blank)

    def test_a_signal_without_a_frame_cannot_be_built(self):
        for blank in ("", "   "):
            with self.assertRaises(RetrainingError):
                _signal(evidence_frame_id=blank)

    def test_a_naive_timestamp_is_refused(self):
        with self.assertRaises(RetrainingError):
            _signal(observed_at=datetime(2026, 9, 20, 9, 0))

    def test_a_valid_signal_carries_both_halves_into_its_summary(self):
        summary = _signal().summarise()
        self.assertEqual("frame-8821", summary["evidence_frame_id"])
        self.assertIn("USE button", summary["what_changed"])

    def test_a_signal_has_nowhere_to_put_a_guessed_replacement(self):
        """The spec forbids guessing a substitute target; there is no field."""
        fields = set(RetrainingSignal.__dataclass_fields__)
        self.assertEqual(
            {"trigger", "what_changed", "evidence_frame_id", "observed_at", "knowledge_ref"},
            fields,
        )

    def test_the_trigger_list_is_closed(self):
        with self.assertRaises(RetrainingError):
            _signal(trigger="SOMETHING_ELSE")


class DegradationTriggerTests(unittest.TestCase):
    def test_a_short_degradation_raises_nothing(self):
        ladder = Ladder()
        ladder.demote("one scarce search", at=NOW - timedelta(minutes=5))
        self.assertIsNone(
            from_persistent_degradation(ladder, NOW, evidence_frame_id="f-1")
        )

    def test_hours_below_the_top_becomes_a_reportable_signal(self):
        ladder = Ladder()
        ladder.demote("search returned no node", at=NOW - timedelta(hours=3))
        signal = from_persistent_degradation(ladder, NOW, evidence_frame_id="f-1")
        self.assertIsNotNone(signal)
        self.assertIs(ChangeTrigger.PLAN_PERSISTENTLY_DEGRADED, signal.trigger)
        self.assertIn("10800s", signal.what_changed)
        self.assertIn("search returned no node", signal.what_changed)
        self.assertEqual("f-1", signal.evidence_frame_id)

    def test_a_recovered_ladder_raises_nothing(self):
        ladder = Ladder()
        ladder.demote("scarce", at=NOW - timedelta(hours=3))
        ladder.promote("nodes are back", at=NOW - timedelta(minutes=1))
        self.assertIsNone(
            from_persistent_degradation(ladder, NOW, evidence_frame_id="f-1")
        )


class ProposalContractTests(unittest.TestCase):
    def test_a_proposal_must_carry_the_signal_that_prompted_it(self):
        with self.assertRaises(RetrainingError):
            _proposal(signal="the button vanished")

    def test_a_proposal_must_explain_itself(self):
        with self.assertRaises(RetrainingError):
            _proposal(rationale="  ")

    def test_a_proposal_must_be_empty_of_nothing(self):
        with self.assertRaises(RetrainingError):
            _proposal(entry={})

    def test_a_proposal_is_only_ever_pending(self):
        self.assertEqual(
            ["PENDING_OPERATOR_REVIEW"], [item.value for item in ProposalStatus]
        )
        self.assertIs(ProposalStatus.PENDING_OPERATOR_REVIEW, _proposal().status)

    def test_a_proposal_has_no_method_that_applies_itself(self):
        forbidden = {"apply", "accept", "commit", "merge", "install", "save_to_knowledge"}
        self.assertEqual(set(), forbidden & set(dir(KnowledgeProposal)))

    def test_the_rendered_proposal_shows_the_frame_and_the_target(self):
        rendered = json.loads(_proposal().render())
        self.assertEqual("frame-8821", rendered["signal"]["evidence_frame_id"])
        self.assertEqual(
            "gathering_continuity_2026-09-19.yaml", rendered["target_knowledge_file"]
        )


class WriteBoundaryTests(unittest.TestCase):
    def test_a_proposal_lands_in_the_workspace_not_in_knowledge(self):
        with TemporaryDirectory() as tmp:
            written = write_proposal(_proposal(), tmp)
            self.assertEqual(Path(tmp).resolve() / "workspace" / "proposals" / "prop-001.json", written)
            self.assertIn("USE button", written.read_text(encoding="utf-8"))
            self.assertNotIn(PROTECTED_DIRECTORY, {p.casefold() for p in written.parts})

    def test_writing_into_the_knowledge_tree_is_refused(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "knowledge" / "gathering_continuity_2026-09-19.yaml"
            with self.assertRaises(RetrainingError) as caught:
                write_proposal(_proposal(), tmp, destination=target)
            self.assertIn("the operator writes it", str(caught.exception))
            self.assertFalse(target.exists())

    def test_the_refusal_is_case_insensitive(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "Knowledge" / "anything.yaml"
            with self.assertRaises(RetrainingError):
                write_proposal(_proposal(), tmp, destination=target)

    def test_the_llm_package_contains_no_write_into_knowledge(self):
        """A grep-level guard, so a future edit cannot quietly add one."""
        pattern = re.compile(r"knowledge[/\\][^\"']*\.ya?ml")
        offenders = []
        for path in (ROOT / "autorok" / "llm").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                offenders.append(f"{path.name}: {match.group(0)}")
        self.assertEqual([], offenders)

    def test_no_knowledge_file_is_touched_by_writing_a_proposal(self):
        before = {
            path.name: path.stat().st_mtime for path in (ROOT / "knowledge").glob("*.yaml")
        }
        with TemporaryDirectory() as tmp:
            write_proposal(_proposal(), tmp)
        after = {
            path.name: path.stat().st_mtime for path in (ROOT / "knowledge").glob("*.yaml")
        }
        self.assertEqual(before, after)


class ProposalLogTests(unittest.TestCase):
    def test_the_log_is_append_only_and_rejects_a_repeated_id(self):
        log = ProposalLog()
        log.add(_proposal())
        with self.assertRaises(RetrainingError):
            log.add(_proposal())
        self.assertEqual(1, len(log))

    def test_proposals_can_be_read_back_by_trigger(self):
        log = ProposalLog()
        log.add(_proposal())
        log.add(
            _proposal(
                proposal_id="prop-002",
                signal=_signal(trigger=ChangeTrigger.LABEL_CHANGED),
            )
        )
        self.assertEqual(
            ("prop-002",),
            tuple(item.proposal_id for item in log.by_trigger(ChangeTrigger.LABEL_CHANGED)),
        )
        self.assertEqual(2, len(log.pending()))

    def test_self_proposed_share_is_zero_when_nothing_was_proposed(self):
        self.assertEqual(0.0, self_proposed_share(ProposalLog(), 11))
        self.assertEqual(0.0, self_proposed_share(ProposalLog(), 0))

    def test_self_proposed_share_counts_proposals_against_the_whole_domain(self):
        log = ProposalLog()
        log.add(_proposal())
        log.add(_proposal(proposal_id="prop-002"))
        self.assertEqual(0.2, self_proposed_share(log, 8))

    def test_the_default_path_is_derived_not_guessed(self):
        self.assertEqual(
            Path("root") / "workspace" / "proposals" / "prop-001.json",
            proposal_path("root", _proposal()),
        )


if __name__ == "__main__":
    unittest.main()
