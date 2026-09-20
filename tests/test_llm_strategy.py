"""The strategic tier - the packets finally have a consumer.

Covers SRS LLM-006 (a strategic packet is answered with a MissionIntent),
LLM-002 at this tier (no geometry reaches the model), LLM-003 (the answer
resolves to an existing candidate or is refused), LLM-004 (a null answer is a
valid abstention), and the loop-level rule that a plan is always produced.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from autorok.llm.intent import (
    BUFF_LOW_SECONDS,
    DecidedBy,
    IntentCandidate,
    IntentError,
    IntentKind,
    MissionIntent,
    StrategicSnapshot,
    fallback_choice,
    fleet_summary,
    propose_candidates,
    unique_candidates,
)
from autorok.llm.strategy import (
    StrategicDecisionProvider,
    StrategicPlanner,
)
from autorok.llm.transport import LocalLLMConfig, LocalLLMError, exactly_one
from autorok.mission.fleet import (
    OPERATOR_BASELINE_STRONG,
    Account,
    Character,
    Fleet,
    March,
    MarchPurpose,
)
from autorok.mission.ladder import Rung
from autorok.mission.order import ResourceKind

NOW = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def _character(character_id: str, *, marches: int = 0, home_in_hours: float = 2.0) -> Character:
    character = Character(
        character_id=character_id,
        account_id="acc-0",
        cycle=OPERATOR_BASELINE_STRONG,
    )
    home_at = NOW + timedelta(hours=home_in_hours)
    for slot in range(marches):
        character.dispatch(
            March(
                slot=slot,
                kind=ResourceKind.FOOD,
                dispatched_at=home_at - timedelta(hours=2),
                expected_home_at=home_at,
                purpose=MarchPurpose.GATHER,
            )
        )
    return character


def _fleet(*characters: Character) -> Fleet:
    return Fleet([Account(account_id="acc-0", characters=list(characters))])


class _Response:
    def __init__(self, value: dict):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def _reply(content: dict) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 20, "total_tokens": 420},
    }


def _provider(handler) -> StrategicDecisionProvider:
    return StrategicDecisionProvider(
        LocalLLMConfig("http://127.0.0.1:8080/v1", "gpt-oss-20b"),
        opener=handler,
    )


def _snapshot(candidates, **kwargs) -> StrategicSnapshot:
    return StrategicSnapshot(
        cycle_id="cycle-1",
        now=NOW,
        active_goal=kwargs.pop("active_goal", Rung.ORDER_WORK),
        candidates=tuple(candidates),
        **kwargs,
    )


class CandidateBuildingTests(unittest.TestCase):
    def test_an_idle_character_is_offered_and_a_marching_one_is_not(self):
        fleet = _fleet(_character("char-idle"), _character("char-busy", marches=5))
        candidates = propose_candidates(fleet=fleet, now=NOW)
        self.assertEqual(
            [("ENTER:char-idle", IntentKind.ENTER_CHARACTER)],
            [(item.intent_id, item.kind) for item in candidates],
        )

    def test_a_character_home_but_queue_full_is_not_offered(self):
        # Eligible by time yet nothing to send - entering would cost a switch
        # and achieve nothing.
        character = _character("char-full", marches=5, home_in_hours=-1)
        candidates = propose_candidates(fleet=_fleet(character), now=NOW)
        self.assertEqual((), candidates)

    def test_observe_only_offers_nothing_at_all(self):
        fleet = _fleet(_character("char-idle"))
        candidates = propose_candidates(
            fleet=fleet, now=NOW, rung=Rung.OBSERVE_ONLY, buff_remaining_seconds=0
        )
        self.assertEqual((), candidates)

    def test_buff_is_offered_only_when_it_is_running_out(self):
        fleet = _fleet(_character("char-idle"))
        plenty = propose_candidates(
            fleet=fleet, now=NOW, buff_remaining_seconds=BUFF_LOW_SECONDS + 1
        )
        low = propose_candidates(
            fleet=fleet, now=NOW, buff_remaining_seconds=BUFF_LOW_SECONDS
        )
        self.assertNotIn(IntentKind.TOP_UP_BUFF, [item.kind for item in plenty])
        self.assertIn(IntentKind.TOP_UP_BUFF, [item.kind for item in low])

    def test_delivery_is_offered_only_while_an_order_is_the_active_goal(self):
        fleet = _fleet(_character("char-idle"))
        at_top = propose_candidates(
            fleet=fleet, now=NOW, deliverable_characters=("char-idle",)
        )
        degraded = propose_candidates(
            fleet=fleet,
            now=NOW,
            deliverable_characters=("char-idle",),
            rung=Rung.SCARCITY_FILL,
        )
        self.assertIn(IntentKind.DELIVER_ORDER, [item.kind for item in at_top])
        self.assertNotIn(IntentKind.DELIVER_ORDER, [item.kind for item in degraded])

    def test_only_undecided_packets_become_daily_candidates(self):
        fleet = _fleet(_character("char-busy", marches=5))
        candidates = propose_candidates(
            fleet=fleet,
            now=NOW,
            due_packets=(
                {"task_id": "CLAIM_VIP", "character_id": "char-1", "status": "NEEDS_DECISION"},
                {"task_id": "DONATE", "character_id": "char-1", "status": "DONE"},
            ),
        )
        self.assertEqual(
            ["DAILY:CLAIM_VIP:char-1"], [item.intent_id for item in candidates]
        )

    def test_a_duplicate_intent_id_is_caught_at_the_builder(self):
        with self.assertRaises(IntentError):
            unique_candidates(
                [
                    IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
                    IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
                ]
            )

    def test_a_candidate_must_carry_what_its_kind_needs(self):
        with self.assertRaises(IntentError):
            IntentCandidate("ENTER:x", IntentKind.ENTER_CHARACTER)
        with self.assertRaises(IntentError):
            IntentCandidate("DAILY:x", IntentKind.CLAIM_DAILY)

    def test_fallback_prefers_a_march_slot_over_a_daily_chore(self):
        candidates = (
            IntentCandidate("DAILY:CLAIM_VIP", IntentKind.CLAIM_DAILY, task_id="CLAIM_VIP"),
            IntentCandidate("ENTER:b", IntentKind.ENTER_CHARACTER, character_id="b"),
            IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
        )
        # Highest priority kind, and stable within the kind.
        self.assertEqual("ENTER:a", fallback_choice(candidates).intent_id)
        self.assertIsNone(fallback_choice(()))


class SnapshotTests(unittest.TestCase):
    def test_geometry_in_a_packet_never_reaches_the_payload(self):
        snapshot = _snapshot(
            [IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF)],
            due_packets=(
                {
                    "task_id": "CLAIM_VIP",
                    "status": "NEEDS_DECISION",
                    "client_window_rect": [0, 0, 1920, 1080],
                    "image_path": "C:/frames/1.png",
                },
            ),
        )
        payload = snapshot.as_payload()
        flattened = json.dumps(payload)
        self.assertNotIn("client_window_rect", flattened)
        self.assertNotIn("image_path", flattened)
        self.assertIn("CLAIM_VIP", flattened)

    def test_snapshot_refuses_a_naive_timestamp(self):
        with self.assertRaises(IntentError):
            StrategicSnapshot(
                cycle_id="c",
                now=datetime(2026, 9, 20, 7, 0),
                active_goal=Rung.ORDER_WORK,
                candidates=(),
            )

    def test_fleet_summary_is_numbers_and_identifiers_only(self):
        fleet = _fleet(_character("char-a", marches=3), _character("char-b"))
        summary = fleet_summary(fleet, NOW)
        self.assertEqual(0.3, summary["queue_occupancy"])
        self.assertEqual(["char-b"], summary["eligible_characters"])
        self.assertEqual(0, summary["next_eligible_in_seconds"])


class ProviderTests(unittest.TestCase):
    def test_the_model_choice_becomes_a_bound_intent(self):
        captured: dict = {}

        def handler(request, timeout=None):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response(_reply({"intent_id": "ENTER:a", "reason": "queue is draining"}))

        snapshot = _snapshot(
            [
                IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
            ]
        )
        intent = _provider(handler).decide(snapshot)
        self.assertEqual("ENTER:a", intent.intent_id)
        self.assertEqual(DecidedBy.MODEL, intent.decided_by)
        self.assertEqual("queue is draining", intent.reason)
        self.assertEqual("json_object", captured["body"]["response_format"]["type"])

    def test_an_invented_intent_id_is_refused_not_repaired(self):
        def handler(request, timeout=None):
            return _Response(_reply({"intent_id": "ENTER:nobody", "reason": "go"}))

        provider = _provider(handler)
        snapshot = _snapshot(
            [
                IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
            ]
        )
        self.assertIsNone(provider.decide(snapshot))
        self.assertIn("resolved to 0", provider.last_error or "")

    def test_a_null_intent_is_an_abstention_and_not_an_error(self):
        def handler(request, timeout=None):
            return _Response(_reply({"intent_id": None, "reason": "cannot tell them apart"}))

        provider = _provider(handler)
        snapshot = _snapshot(
            [
                IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
            ]
        )
        self.assertIsNone(provider.decide(snapshot))
        self.assertIsNone(provider.last_error)

    def test_an_unreachable_endpoint_fails_closed(self):
        def handler(request, timeout=None):
            raise OSError("connection refused")

        provider = _provider(handler)
        snapshot = _snapshot(
            [
                IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
            ]
        )
        self.assertIsNone(provider.decide(snapshot))
        self.assertIn("OSError", provider.last_error or "")
        self.assertIsNotNone(provider.last_request_sha256)

    def test_the_provider_will_not_spend_a_call_on_a_settled_question(self):
        def handler(request, timeout=None):  # pragma: no cover - must not run
            raise AssertionError("the model was called with fewer than two candidates")

        provider = _provider(handler)
        self.assertIsNone(
            provider.decide(_snapshot([IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF)]))
        )

    def test_config_still_refuses_a_non_loopback_endpoint(self):
        with self.assertRaises(LocalLLMError):
            LocalLLMConfig.from_mapping({"endpoint": "https://example.invalid/v1", "model": "x"})

    def test_two_matches_is_a_refusal_not_a_tie_break(self):
        with self.assertRaises(LocalLLMError):
            exactly_one(["a", "b"], what="intent_id")


class PlannerTests(unittest.TestCase):
    def _never_called(self, request, timeout=None):  # pragma: no cover - must not run
        raise AssertionError("the planner called the model when it should not have")

    def test_nothing_to_do_yields_an_explicit_hold(self):
        planner = StrategicPlanner(_provider(self._never_called))
        intent = planner.plan(_snapshot([]))
        self.assertEqual(IntentKind.HOLD, intent.kind)
        self.assertEqual(DecidedBy.HARNESS_ONLY_OPTION, intent.decided_by)
        self.assertEqual(0, planner.model_calls)

    def test_a_single_option_is_taken_without_a_model_call(self):
        planner = StrategicPlanner(_provider(self._never_called))
        only = IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a")
        intent = planner.plan(_snapshot([only]))
        self.assertEqual("ENTER:a", intent.intent_id)
        self.assertEqual(DecidedBy.HARNESS_ONLY_OPTION, intent.decided_by)
        self.assertEqual(0, planner.model_calls)

    def test_with_no_model_at_all_the_planner_still_decides(self):
        planner = StrategicPlanner(None)
        intent = planner.plan(
            _snapshot(
                [
                    IntentCandidate("DAILY:VIP", IntentKind.CLAIM_DAILY, task_id="VIP"),
                    IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                ]
            )
        )
        self.assertEqual("ENTER:a", intent.intent_id)
        self.assertEqual(DecidedBy.HARNESS_FALLBACK, intent.decided_by)
        self.assertIn("no model configured", intent.reason)

    def test_a_dead_model_degrades_to_the_priority_order(self):
        def handler(request, timeout=None):
            raise OSError("connection refused")

        planner = StrategicPlanner(_provider(handler))
        intent = planner.plan(
            _snapshot(
                [
                    IntentCandidate("DAILY:VIP", IntentKind.CLAIM_DAILY, task_id="VIP"),
                    IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                ]
            )
        )
        self.assertEqual("ENTER:a", intent.intent_id)
        self.assertEqual(DecidedBy.HARNESS_FALLBACK, intent.decided_by)
        self.assertIn("model unavailable", intent.reason)
        self.assertEqual(1, planner.model_calls)
        self.assertEqual(0, planner.model_decisions)

    def test_an_abstention_is_distinguishable_from_a_failure_in_the_reason(self):
        def handler(request, timeout=None):
            return _Response(_reply({"intent_id": None, "reason": "no evidence"}))

        planner = StrategicPlanner(_provider(handler))
        intent = planner.plan(
            _snapshot(
                [
                    IntentCandidate("DAILY:VIP", IntentKind.CLAIM_DAILY, task_id="VIP"),
                    IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                ]
            )
        )
        self.assertIn("model abstained", intent.reason)

    def test_entry_rate_counts_calls_against_planning_cycles(self):
        def handler(request, timeout=None):
            return _Response(_reply({"intent_id": "ENTER:a", "reason": "go"}))

        planner = StrategicPlanner(_provider(handler))
        settled = _snapshot([IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a")])
        contested = _snapshot(
            [
                IntentCandidate("ENTER:a", IntentKind.ENTER_CHARACTER, character_id="a"),
                IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
            ]
        )
        for _ in range(9):
            planner.plan(settled)
        planner.plan(contested)
        self.assertEqual(10, planner.plans)
        self.assertEqual(1, planner.model_calls)
        self.assertEqual(10.0, planner.entries_per_100_plans)

    def test_a_plan_is_never_none_and_always_carries_a_reason(self):
        planner = StrategicPlanner(None)
        for candidates in ([], [IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF)]):
            intent = planner.plan(_snapshot(candidates))
            self.assertIsInstance(intent, MissionIntent)
            self.assertTrue(intent.reason.strip())

    def test_an_intent_without_a_reason_cannot_be_constructed(self):
        with self.assertRaises(IntentError):
            MissionIntent(
                candidate=IntentCandidate("TOP_UP_BUFF", IntentKind.TOP_UP_BUFF),
                reason="   ",
                decided_by=DecidedBy.MODEL,
            )


if __name__ == "__main__":
    unittest.main()
