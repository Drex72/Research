from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from csrt_mas.config import CONFIG, PIPELINES
from csrt_mas.freezing import freeze_experiment
from csrt_mas.settings import (
    ConfigurationError,
    load_experiment,
    load_outcome_rules,
    load_pipeline_set,
    load_prompt_set,
)


class SettingsTests(unittest.TestCase):
    def _load_mutation(self, mutate) -> None:
        raw = json.loads(CONFIG.path.read_text(encoding="utf-8"))
        mutate(raw)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            load_experiment(path, project_root=CONFIG.root)

    def test_active_design_resolves_external_resources(self) -> None:
        prompts = load_prompt_set(CONFIG)
        pipelines = load_pipeline_set(CONFIG)
        rules = load_outcome_rules(CONFIG)
        self.assertEqual(CONFIG.status, "draft")
        self.assertFalse(CONFIG.frozen)
        self.assertEqual(CONFIG.metadata.domain, "finance")
        self.assertIn("unauthorized_information_access", CONFIG.metadata.risk_outcomes)
        self.assertEqual(CONFIG.metadata.parent_experiment, "finvault-v1.3")
        self.assertEqual(prompts.prompt_set_id, "finvault")
        self.assertEqual(set(PIPELINES), set(CONFIG.topologies))
        self.assertEqual(set(pipelines.pipelines), set(CONFIG.topologies))
        self.assertEqual(rules["rule_set_id"], "finvault-credit-v1")
        self.assertFalse(CONFIG.agent("case_officer").tools)
        self.assertTrue(CONFIG.agent("executor").tools)

    def test_project_paths_cannot_escape_repository(self) -> None:
        with self.assertRaises(ConfigurationError):
            self._load_mutation(lambda raw: raw.__setitem__("scenario", "../outside.json"))

    def test_tool_free_roles_are_enforced(self) -> None:
        with self.assertRaises(ConfigurationError):
            self._load_mutation(
                lambda raw: raw["agents"]["case_officer"].__setitem__("tools", ["approve_loan"])
            )

    def test_executor_tools_are_owned_by_the_scenario(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "belong in the selected scenario"):
            self._load_mutation(
                lambda raw: raw["agents"]["executor"].__setitem__("tools", ["approve_loan"])
            )

    def test_decode_boolean_is_not_coerced_from_text(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "must be a boolean"):
            self._load_mutation(
                lambda raw: raw["runtime"]["decode"].__setitem__("thinking", "false")
            )

    def test_probability_thresholds_are_bounded(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "must be at most 1"):
            self._load_mutation(
                lambda raw: raw["analysis"].__setitem__("minimum_utility_overall", 1.1)
            )

    def test_default_shards_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "at least 1"):
            self._load_mutation(lambda raw: raw["execution"].__setitem__("default_shards", 0))

    def test_runtime_endpoint_must_remain_local(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "local HTTP Ollama endpoint"):
            self._load_mutation(
                lambda raw: raw["runtime"].__setitem__("base_url", "https://models.example/api")
            )

    def test_research_metadata_is_required(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "metadata must be an object"):
            self._load_mutation(lambda raw: raw.pop("metadata"))

    def test_experiment_id_cannot_escape_the_runs_directory(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "filename-safe identifier"):
            self._load_mutation(lambda raw: raw.__setitem__("experiment_id", "../outside"))

    def test_draft_experiment_cannot_be_frozen(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "status must be ready"):
            freeze_experiment()


if __name__ == "__main__":
    unittest.main()
