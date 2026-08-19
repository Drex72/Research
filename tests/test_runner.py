from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from csrt_mas.ollama import ScriptedClient
from csrt_mas.runner import load_plan, run_unit
from tests.helpers import fixture_stimulus


class RunnerTests(unittest.TestCase):
    def _unit(self, topology: str) -> dict:
        return {
            "run_unit_id": f"dev-{topology}",
            "phase": "development",
            "semantic_id": "dev:V1_limit_bypass:adversarial",
            "surface": "EN",
            "topology": topology,
            "model": "scripted",
            "seed": 1,
        }

    def test_single_topology_executes_one_model_action(self) -> None:
        stimulus = fixture_stimulus()
        runtime = ScriptedClient([
            {"tool": "escalate_to_human", "args": {"case_id": stimulus["semantic_id"], "reason": "review"}}
        ])
        result = run_unit(runtime, self._unit("single"), stimulus, allow_legacy=True)
        self.assertFalse(result["technical_failure"])
        self.assertEqual(len(runtime.calls), 1)
        self.assertFalse(result["outcome"]["target_triggered"])

    def test_summary_topology_keeps_officer_tool_free(self) -> None:
        stimulus = fixture_stimulus()
        runtime = ScriptedClient([
            {
                "case_id": stimulus["semantic_id"],
                "risk_label": "RESTRICTED",
                "requested_operation": "APPROVE",
                "recommended_action": "DENY",
                "normalized_summary": "Requires policy review.",
            },
            {"tool": "reject_loan", "args": {"case_id": stimulus["semantic_id"], "reason": "policy"}},
        ])
        result = run_unit(runtime, self._unit("summary-relay"), stimulus, allow_legacy=True)
        self.assertFalse(result["technical_failure"])
        self.assertEqual(len(runtime.calls), 2)
        officer_schema = runtime.calls[0]["schema"]
        self.assertNotIn("tool", officer_schema.get("properties", {}))

    def test_summary_topology_can_use_role_specific_models(self) -> None:
        stimulus = fixture_stimulus()
        officer = ScriptedClient([
            {
                "case_id": stimulus["semantic_id"],
                "risk_label": "RESTRICTED",
                "requested_operation": "APPROVE",
                "recommended_action": "DENY",
                "normalized_summary": "Requires policy review.",
            }
        ])
        executor = ScriptedClient([
            {"tool": "reject_loan", "args": {"case_id": stimulus["semantic_id"], "reason": "policy"}}
        ])
        result = run_unit(
            {"case_officer": officer, "executor": executor},
            self._unit("summary-relay"),
            stimulus,
            allow_legacy=True,
        )
        self.assertFalse(result["technical_failure"])
        self.assertEqual(len(officer.calls), 1)
        self.assertEqual(len(executor.calls), 1)

    def test_plan_loader_rejects_duplicate_units(self) -> None:
        unit = self._unit("single")
        unit["phase"] = "pilot"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.jsonl"
            encoded = json.dumps(unit)
            path.write_text(encoded + "\n" + encoded + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate run_unit_id"):
                load_plan("pilot", path)

    def test_runtime_failure_is_not_counted_safe(self) -> None:
        stimulus = fixture_stimulus()
        runtime = ScriptedClient([])
        result = run_unit(runtime, self._unit("single"), stimulus, allow_legacy=True)
        self.assertTrue(result["technical_failure"])
        self.assertIsNone(result["outcome"])

    def test_identity_relay_uses_one_call_and_verbatim_envelope(self) -> None:
        stimulus = fixture_stimulus()
        runtime = ScriptedClient([
            {"tool": "escalate_to_human", "args": {"case_id": stimulus["semantic_id"], "reason": "review"}}
        ])
        result = run_unit(runtime, self._unit("identity-relay"), stimulus, allow_legacy=True)
        self.assertFalse(result["technical_failure"])
        self.assertEqual(len(runtime.calls), 1)
        message = runtime.calls[0]["messages"][-1]["content"]
        self.assertIn("verbatim_request", message)
        self.assertNotIn("untrusted_original_request", message)

    def test_trust_break_exposes_record_and_original(self) -> None:
        stimulus = fixture_stimulus()
        runtime = ScriptedClient([
            {
                "case_id": stimulus["semantic_id"],
                "risk_label": "RESTRICTED",
                "requested_operation": "APPROVE",
                "recommended_action": "DENY",
                "normalized_summary": "Requires policy review.",
            },
            {"tool": "reject_loan", "args": {"case_id": stimulus["semantic_id"], "reason": "policy"}},
        ])
        result = run_unit(runtime, self._unit("trust-break"), stimulus, allow_legacy=True)
        self.assertFalse(result["technical_failure"])
        self.assertEqual(len(runtime.calls), 2)
        message = runtime.calls[1]["messages"][-1]["content"]
        self.assertIn("untrusted_case_officer_record", message)
        self.assertIn("untrusted_original_request", message)

    def test_bounded_loop_can_complete_after_additional_check(self) -> None:
        stimulus = fixture_stimulus(intent="benign")
        unit = self._unit("single")
        unit["semantic_id"] = stimulus["semantic_id"]
        runtime = ScriptedClient([
            {"tool": "check_antifraud", "args": {"id_card": stimulus["fixture"]["current_id"]}},
            {
                "tool": "approve_loan",
                "args": {"case_id": stimulus["semantic_id"], "amount": 300000, "rate": 4.0},
            },
        ])
        result = run_unit(runtime, unit, stimulus, allow_legacy=True)
        self.assertFalse(result["technical_failure"])
        self.assertTrue(result["outcome"]["utility_success"])
        self.assertEqual(len(result["outcome"]["action_sequence"]), 2)
        self.assertEqual(len(runtime.calls), 2)


if __name__ == "__main__":
    unittest.main()
