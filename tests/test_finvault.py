from __future__ import annotations

import json
import unittest

from csrt_mas.finvault import FinVaultAdapter
from csrt_mas.schemas import REFUSAL_TOOL, TOOLS
from tests.helpers import fixture_stimulus


class FinVaultAdapterTests(unittest.TestCase):
    @staticmethod
    def _stable_state(adapter: FinVaultAdapter) -> str:
        def scrub(value):
            if isinstance(value, dict):
                return {
                    key: scrub(item)
                    for key, item in value.items()
                    if key.lower() not in {"timestamp", "episode_id"}
                }
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value

        return json.dumps(scrub(adapter.env.state.to_dict()), sort_keys=True, default=str)

    def test_action_level_oracle_uses_real_environment(self) -> None:
        stimulus = fixture_stimulus()
        adapter = FinVaultAdapter(stimulus, stimulus["texts"]["EN"])
        outcome = adapter.execute(
            {"tool": "approve_loan", "args": {"case_id": stimulus["semantic_id"], "amount": 600000, "rate": 4.0}}
        )
        self.assertTrue(outcome.target_triggered)
        self.assertTrue(outcome.any_triggered)

    def test_fresh_adapter_resets_state(self) -> None:
        stimulus = fixture_stimulus()
        first = FinVaultAdapter(stimulus, stimulus["texts"]["EN"])
        before = self._stable_state(first)
        first.execute(
            {"tool": "approve_loan", "args": {"case_id": stimulus["semantic_id"], "amount": 600000, "rate": 4.0}}
        )
        second = FinVaultAdapter(stimulus, stimulus["texts"]["EN"])
        after_reset = self._stable_state(second)
        self.assertEqual(before, after_reset)

    def test_benign_utility_is_separate(self) -> None:
        stimulus = fixture_stimulus(intent="benign")
        adapter = FinVaultAdapter(stimulus, stimulus["texts"]["EN"])
        outcome = adapter.execute(
            {"tool": "approve_loan", "args": {"case_id": stimulus["semantic_id"], "amount": 300000, "rate": 4.0}}
        )
        self.assertFalse(outcome.target_triggered)
        self.assertTrue(outcome.utility_success)

    def test_environment_exposes_only_selected_tools(self) -> None:
        stimulus = fixture_stimulus()
        adapter = FinVaultAdapter(stimulus, stimulus["texts"]["EN"])
        # REFUSAL_TOOL is an outcome the model can report, not something the
        # sandbox implements, so it is never registered in the environment.
        self.assertEqual(
            set(adapter.env.tool_registry.get_tool_names()), TOOLS - {REFUSAL_TOOL}
        )


if __name__ == "__main__":
    unittest.main()
