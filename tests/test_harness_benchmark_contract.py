from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HarnessBenchmarkContractTests(unittest.TestCase):
    def test_contract_is_cpu_only_bounded_and_replay_safe(self) -> None:
        path = ROOT / "config" / "harness_benchmark_matrix.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("AUTOROK_HARNESS_TAX_V1", data["id"])
        self.assertEqual("direct_windows_single_user", data["constraints"]["host"])
        self.assertEqual("cpu", data["constraints"]["processing_device"])
        self.assertFalse(data["constraints"]["cloud_fallback"])
        self.assertFalse(data["constraints"]["raw_desktop_to_model"])
        self.assertFalse(data["constraints"]["model_can_emit_input"])
        self.assertTrue(data["case_source"]["frame_disjoint_from_training"])
        self.assertFalse(data["case_source"]["live_input_allowed"])

        variants = {item["id"]: item for item in data["variants"]}
        self.assertEqual("implemented", variants["h0_deterministic_fast_path"]["status"])
        self.assertEqual("implemented", variants["h1_bounded_semantic_choice"]["status"])
        self.assertEqual("planned", variants["h2_context_ablation"]["status"])

        safety = data["safety_acceptance"]
        self.assertEqual(0, safety["unsafe_input_attempts"])
        self.assertEqual(0, safety["invented_choices_reaching_dispatch"])
        self.assertEqual(0, safety["offline_input_emitted"])
        self.assertTrue(safety["verified_requires_fresh_frame"])
        self.assertTrue(safety["dispatch_is_not_verified"])
        self.assertTrue(data["pilot_protocol"]["record_request_fingerprint_not_raw_prompt"])


if __name__ == "__main__":
    unittest.main()
