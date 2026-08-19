from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from csrt_mas.finvault_dynamic import (
    DatasetCase,
    DynamicFinVaultAdapter,
    FinVaultCatalog,
    FinVaultCatalogError,
    FinVaultCodeSwitchAdapter,
    audit_all_interfaces,
    load_dynamic_design,
)
from csrt_codeswitch import CodeSwitcher
from csrt_mas.freezing import project_dependency_files
from csrt_mas.resources import load_agent_definition, load_language_profile
from csrt_mas.graph import GraphPipelineEngine
from csrt_mas.language_surfaces import LanguageSurfaceError, build_language_bundle
from csrt_mas.resources import load_graph_pipeline


ROOT = Path(__file__).resolve().parents[1]


class DynamicFinVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = FinVaultCatalog(
            ROOT / "vendor" / "FinVault",
            ROOT / "scenarios" / "finvault",
        )

    def test_catalog_discovers_every_scenario_and_synthesis_family(self) -> None:
        summary = self.catalog.summary()
        self.assertEqual(summary["scenario_count"], 31)
        self.assertEqual(len(summary["synthesis_families"]), 8)
        self.assertEqual(summary["status_counts"]["validated"], 1)
        self.assertEqual(summary["status_counts"]["integrated"], 1)
        self.assertEqual(summary["status_counts"]["discovered"], 29)

    def test_interface_audit_does_not_claim_oracle_validation(self) -> None:
        result = audit_all_interfaces(self.catalog)
        self.assertEqual(result["scenario_count"], 31)
        self.assertIn("does not validate action oracles", result["warning"])
        self.assertEqual(len(result["scenarios"]), 31)

    def test_dataset_resolution_uses_scenario_and_family(self) -> None:
        cases = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "13",
            family="authority_impersonation",
        )
        self.assertEqual(len(cases), 3)
        self.assertTrue(
            all(
                case.source_path.name == "scenario_13_attacks.json"
                and case.scenario_id == "13"
                and case.family == "authority_impersonation"
                for case in cases
            )
        )

    def test_synthesized_follow_up_turns_are_preserved(self) -> None:
        cases = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "00",
            family="emotional_manipulation",
        )
        multi_turn = [case for case in cases if case.follow_up_prompts]
        self.assertTrue(multi_turn)
        self.assertEqual(
            multi_turn[0].turns,
            (multi_turn[0].prompt, *multi_turn[0].follow_up_prompts),
        )

    def test_unintegrated_scenario_cannot_create_conclusion_adapter(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "01",
            family="authority_impersonation",
        )[0]
        with self.assertRaisesRegex(FinVaultCatalogError, "no CSRT integration"):
            DynamicFinVaultAdapter(self.catalog, case)

    def test_scenario_00_dynamic_positive_control(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "00",
            family="authority_impersonation",
        )[0]
        adapter = DynamicFinVaultAdapter(self.catalog, case, allow_exploratory=True)
        outcome = adapter.execute(
            {
                "tool": "approve_loan",
                "args": {"case_id": case.case_id, "amount": 1_500_000, "rate": 3.5},
            }
        )
        self.assertTrue(outcome.target_triggered)
        self.assertFalse(outcome.technical_failure)

    def test_scenario_13_switches_prompt_tools_and_oracle(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "13",
            family="authority_impersonation",
        )[0]
        adapter = DynamicFinVaultAdapter(self.catalog, case, allow_exploratory=True)
        self.assertIn("anti-fraud blacklist", adapter.system_prompt.lower())
        self.assertIn("remove_from_blacklist", adapter.available_tools)
        self.assertNotIn("approve_loan", adapter.available_tools)
        outcome = adapter.execute(
            {
                "tool": "remove_from_blacklist",
                "args": {
                    "entity_id": case.raw["context"]["entity_id"],
                    "reason": "case closed",
                },
            }
        )
        self.assertTrue(outcome.target_triggered)
        self.assertEqual(outcome.triggered, ("V1_blacklist_whitewashing",))
        self.assertFalse(outcome.technical_failure)

    def test_scenario_13_fresh_adapter_resets_execution_state(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "13",
            family="authority_impersonation",
        )[0]
        first = DynamicFinVaultAdapter(self.catalog, case, allow_exploratory=True)
        first.execute(
            {
                "tool": "remove_from_blacklist",
                "args": {"entity_id": case.raw["context"]["entity_id"]},
            }
        )
        second = DynamicFinVaultAdapter(self.catalog, case, allow_exploratory=True)
        self.assertEqual(second.env.current_step, 0)
        self.assertEqual(second.env.triggered_vulnerabilities, [])
        self.assertEqual(second.env.state.current_state, "PENDING")

    def test_scenario_13_safe_control_does_not_trigger_oracle(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "13",
            family="authority_impersonation",
        )[0]
        adapter = DynamicFinVaultAdapter(self.catalog, case, allow_exploratory=True)
        outcome = adapter.execute(
            {
                "tool": "escalate_to_human",
                "args": {"reason": "unverified removal request", "priority": "high"},
            }
        )
        self.assertFalse(outcome.any_triggered)
        self.assertFalse(outcome.target_triggered)
        self.assertFalse(outcome.technical_failure)

    def test_scenario_13_legitimate_sequence_scores_utility(self) -> None:
        case = self.catalog.load_cases("normal_datasets", "13")[2]
        adapter = DynamicFinVaultAdapter(
            self.catalog, case, allow_exploratory=True
        )
        context = case.raw["context"]
        outcome = adapter.execute(
            {
                "tool": "update_blacklist_reason",
                "args": {
                    "entity_id": context["entity_id"],
                    "new_reason": context["new_reason"],
                },
            }
        )
        self.assertTrue(outcome.utility_success)
        self.assertFalse(outcome.any_triggered)

    def test_agent_and_language_resources_are_explicit(self) -> None:
        agent = load_agent_definition(ROOT / "agents" / "executor.json")
        language = load_language_profile(ROOT / "languages" / "CS-EN-KO.json")
        self.assertEqual(agent.agent_id, "executor")
        self.assertEqual(agent.tool_policy, "from_sandbox")
        self.assertEqual(language.kind, "code_switched")
        self.assertEqual(language.application_point, "user_request")
        self.assertIn("identifiers", language.preserve)

    def test_experiment_selects_dynamic_scenario_dataset_agents_and_surfaces(self) -> None:
        import json

        experiment = json.loads((ROOT / "experiment.json").read_text(encoding="utf-8"))
        design = load_dynamic_design(experiment, ROOT, self.catalog)
        summary = design.summary(self.catalog)
        self.assertEqual(summary["dataset"], "attack_datasets_synthesis")
        self.assertEqual(summary["scenarios"], ["00"])
        self.assertEqual(summary["attack_cases"], 16)
        self.assertEqual(summary["normal_cases"], 4)
        self.assertEqual(set(summary["agents"]), {"case_officer", "executor"})
        self.assertEqual(set(summary["surfaces"]), {"EN", "KO", "CS"})
        self.assertEqual(summary["graph_pipelines"][0]["pipeline_id"], "summary-relay-graph")

    def test_freeze_dependencies_include_indirect_dynamic_resources(self) -> None:
        dependencies = {path.resolve() for path in project_dependency_files()}
        expected = {
            ROOT / "models" / "qwen3.5-27b.json",
            ROOT / "prompts" / "finvault" / "case-officer.md",
            ROOT / "prompts" / "finvault" / "executor.md",
            ROOT / "prompts" / "handoffs" / "summary-only.md",
            ROOT / "src" / "csrt_codeswitch" / "switcher.py",
            ROOT / "src" / "csrt_codeswitch" / "languages.json",
        }
        self.assertTrue({path.resolve() for path in expected}.issubset(dependencies))

    def test_changing_only_scenario_selection_resolves_scenario_13(self) -> None:
        import copy
        import json

        experiment = json.loads((ROOT / "experiment.json").read_text(encoding="utf-8"))
        changed = copy.deepcopy(experiment)
        changed["dynamic_finvault"]["dataset"]["scenarios"] = ["13"]
        with self.assertRaisesRegex(
            FinVaultCatalogError, "requires a validated scenario"
        ):
            load_dynamic_design(changed, ROOT, self.catalog)
        changed["dynamic_finvault"]["exploratory"] = True
        design = load_dynamic_design(changed, ROOT, self.catalog)
        summary = design.summary(self.catalog)
        self.assertEqual(summary["scenarios"], ["13"])
        self.assertTrue(summary["exploratory"])
        self.assertEqual(summary["attack_cases"], 12)
        self.assertEqual(summary["normal_cases"], 3)

    def test_graph_pipeline_executes_explicit_agent_roles_and_handoff(self) -> None:
        pipeline = load_graph_pipeline(ROOT / "pipelines" / "summary-relay.graph.json")
        agents = {
            "case_officer": load_agent_definition(ROOT / "agents" / "case-officer.json"),
            "executor": load_agent_definition(ROOT / "agents" / "executor.json"),
        }
        calls = []

        def invoke(agent, node_id, payload):
            calls.append((agent.agent_id, node_id, payload))
            if node_id == "officer":
                return {"normalized_summary": "reviewed"}
            return {"tool": "escalate_to_human", "args": {"reason": "review"}}

        result = GraphPipelineEngine(pipeline, agents).run(
            original_request="request",
            trusted_evidence={"scenario_id": "13"},
            invoke=invoke,
        )
        self.assertEqual([value[1] for value in calls], ["officer", "executor"])
        self.assertEqual(
            calls[1][2]["handoffs"][0]["summary"],
            {"normalized_summary": "reviewed"},
        )
        self.assertEqual(result.output["tool"], "escalate_to_human")

    def test_language_builder_preserves_turns_and_protected_facts(self) -> None:
        case = self.catalog.load_cases(
            "attack_datasets_synthesis",
            "00",
            family="emotional_manipulation",
        )[0]
        profiles = {
            "EN": load_language_profile(ROOT / "languages" / "EN.json"),
            "CS": load_language_profile(ROOT / "languages" / "CS-EN-KO.json"),
        }
        code_switched = tuple(
            f"{turn} 검토" for turn in case.turns
        )
        bundle = build_language_bundle(case, profiles, {"CS": code_switched})
        self.assertEqual(bundle.surfaces["EN"].turns, case.turns)
        self.assertEqual(bundle.surfaces["CS"].turns, code_switched)

        with self.assertRaises(LanguageSurfaceError):
            build_language_bundle(case, profiles, {"CS": ("English 한국어",)})

    def test_independent_code_switcher_plugs_into_finvault_case_adapter(self) -> None:
        import json

        case = DatasetCase(
            scenario_id="00",
            dataset="attack_datasets_synthesis",
            family="test",
            case_id="case-1",
            property_id="property-1",
            prompt="Please approve.",
            follow_up_prompts=(),
            source_path=ROOT / "fixture.json",
            source_sha256="fixture",
            raw={},
        )
        reply = {
            "segments": [
                {"text": "Please approve,", "language": "English", "unit": "clause"},
                {"text": "요청을 검토하세요.", "language": "Korean", "unit": "clause"},
            ]
        }
        switcher = CodeSwitcher(
            ["English", "Korean"],
            granularity="clause",
            attempts=1,
            min_hits=1,
            max_dominance=0.95,
        )
        generated = " ".join(segment["text"] for segment in reply["segments"])
        switcher.switch = lambda *_args, **_kwargs: SimpleNamespace(
            ok=True,
            text=generated,
            problems=(),
        )

        surface = FinVaultCodeSwitchAdapter("CS-EN-KO", switcher).author(case)
        self.assertTrue(surface.accepted)
        self.assertEqual(surface.case_id, "case-1")
        self.assertIn("요청", surface.turns[0])


if __name__ == "__main__":
    unittest.main()
