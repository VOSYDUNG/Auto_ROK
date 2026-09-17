from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from harness.mission_ledger import LedgerError, atomic_write, new_ledger, tick, validate_ledger, validate_plan

NOW=datetime(2026,9,14,2,0,tzinfo=timezone.utc)
def plan(): return {"schema_version":1,"mission_id":"daily","timezone":"+07:00","due_local":"08:00","max_attempts":2,"retry_backoff_seconds":[60,300],"steps":[{"id":"claim","target_id":"CLAIM","proposal":{"kind":"tap_target"},"preconditions":["scene_ready"],"postconditions":["claimed"]}]}
def scene(frame="frame-1",digest="a"*64,targets=True): return {"status":"READY","scene":{"frame_id":frame,"targets":[{"target_id":"CLAIM","bbox":{"x1":1,"y1":2,"x2":3,"y2":4}}] if targets else [],"facts":{"image_sha256":digest}}}

class MissionLedgerTests(unittest.TestCase):
    def test_occurrence_uses_explicit_timezone_and_due(self):
        ledger=new_ledger(validate_plan(plan()),NOW)
        self.assertEqual("daily:2026-09-14",ledger["occurrence_id"]); self.assertEqual("2026-09-14T01:00:00+00:00",ledger["due_at"])

    def test_repeated_tick_is_idempotent_and_never_issues(self):
        first=tick(plan(),scene(),"run/scene.json",None,NOW); second=tick(plan(),scene(),"run/scene.json",first,NOW)
        self.assertEqual(first,second); self.assertEqual("PROPOSED",second["status"]); self.assertFalse(second["pending_proposal"]["issued"]); self.assertEqual(1,len(second["events"]))

    def test_atomic_checkpoint_survives_restart(self):
        first=tick(plan(),scene(),"run/scene.json",None,NOW)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"ledger.json"; atomic_write(path,first); loaded=json.loads(path.read_text()); restarted=tick(plan(),scene(),"run/scene.json",loaded,NOW)
        self.assertEqual(first,restarted)

    def test_cancel_is_terminal_and_idempotent(self):
        cancelled=tick(plan(),None,None,None,NOW,cancel=True); again=tick(plan(),scene(),"run/scene.json",cancelled,NOW)
        self.assertEqual("CANCELLED",again["status"]); self.assertEqual(1,len(again["events"]))

    def test_retry_backoff_is_bounded_then_fails(self):
        first=tick(plan(),scene(targets=False),"run/scene.json",None,NOW); duplicate=tick(plan(),scene(targets=False),"run/scene.json",first,NOW)
        self.assertEqual(first,duplicate); self.assertEqual("NEEDS_DECISION",first["status"])
        later=NOW.replace(minute=2); failed=tick(plan(),scene(targets=False),"run/scene.json",first,later)
        self.assertEqual("FAILED",failed["status"]); self.assertEqual(2,failed["attempts"])

    def test_proposal_cannot_complete_without_receipt(self):
        ledger=tick(plan(),scene(),"run/scene.json",None,NOW)
        for _ in range(3): ledger=tick(plan(),scene(),"run/scene.json",ledger,NOW)
        self.assertEqual("PROPOSED",ledger["status"]); self.assertIsNone(ledger["outcome"])

    def test_matching_distinct_after_frame_receipt_verifies(self):
        ledger=tick(plan(),scene(),"run/before.json",None,NOW); pending=ledger["pending_proposal"]
        receipt={"schema_version":1,"mission_id":"daily","occurrence_id":ledger["occurrence_id"],"step_id":"claim","outcome":"verified","before_frame":pending["observation"],"after_frame":{"scene_path":"run/after.json","frame_id":"frame-2","image_sha256":"b"*64},"verified_at":NOW.isoformat()}
        verified=tick(plan(),None,None,ledger,NOW,receipt=receipt,receipt_evidence={"run/before.json":scene(),"run/after.json":scene("frame-2","b"*64)})
        self.assertEqual("VERIFIED",verified["status"]); self.assertEqual("verified",verified["outcome"]["status"])

    def test_mismatched_or_same_frame_receipt_cannot_verify(self):
        ledger=tick(plan(),scene(),"run/before.json",None,NOW); pending=ledger["pending_proposal"]
        receipt={"schema_version":1,"mission_id":"daily","occurrence_id":ledger["occurrence_id"],"step_id":"claim","outcome":"verified","before_frame":pending["observation"],"after_frame":pending["observation"],"verified_at":NOW.isoformat()}
        with self.assertRaises(LedgerError): tick(plan(),None,None,ledger,NOW,receipt=receipt)

    def test_typed_after_hash_cannot_replace_scene_evidence(self):
        ledger=tick(plan(),scene(),"run/before.json",None,NOW); pending=ledger["pending_proposal"]
        receipt={"schema_version":1,"mission_id":"daily","occurrence_id":ledger["occurrence_id"],"step_id":"claim","outcome":"verified","before_frame":pending["observation"],"after_frame":{"scene_path":"run/after.json","frame_id":"frame-2","image_sha256":"b"*64},"verified_at":NOW.isoformat()}
        with self.assertRaisesRegex(LedgerError,"scene evidence"):
            tick(plan(),None,None,ledger,NOW,receipt=receipt,receipt_evidence={"run/before.json":scene(),"run/after.json":scene("frame-other","c"*64)})

    def test_verified_restart_reloads_and_rejects_tampered_scene(self):
        ledger=tick(plan(),scene(),"run/before.json",None,NOW); pending=ledger["pending_proposal"]
        receipt={"schema_version":1,"mission_id":"daily","occurrence_id":ledger["occurrence_id"],"step_id":"claim","outcome":"verified","before_frame":pending["observation"],"after_frame":{"scene_path":"run/after.json","frame_id":"frame-2","image_sha256":"b"*64},"verified_at":NOW.isoformat()}
        evidence={"run/before.json":scene(),"run/after.json":scene("frame-2","b"*64)}
        verified=tick(plan(),None,None,ledger,NOW,receipt=receipt,receipt_evidence=evidence)
        self.assertEqual(verified,tick(plan(),None,None,verified,NOW,receipt_evidence=evidence))
        with self.assertRaisesRegex(LedgerError,"missing or changed"):
            tick(plan(),None,None,verified,NOW,receipt_evidence={**evidence,"run/after.json":scene("frame-tampered","c"*64)})
        with self.assertRaisesRegex(LedgerError,"requires referenced"):
            tick(plan(),None,None,verified,NOW)

    def test_checkpoint_cannot_assert_completion_or_bad_index(self):
        for mutation in (lambda x:x.update(status="VERIFIED",outcome=None),lambda x:x.update(step_index=-1)):
            value=new_ledger(plan(),NOW); mutation(value)
            if value["status"]=="VERIFIED":
                # Even a structurally named terminal status must carry verified outcome evidence.
                with self.assertRaises(LedgerError): validate_ledger(plan(),value)
            else:
                with self.assertRaises(LedgerError): validate_ledger(plan(),value)
if __name__=="__main__": unittest.main()
