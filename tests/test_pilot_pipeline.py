from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from csrt_mas.analysis import (
    cluster_key,
    independent_cluster_count,
    rule_of_three_upper_bound,
    _decision,
)
from csrt_mas.corpus import (
    CONTROL_POSITIVE,
    build_corpus,
    cluster_id_for,
    corpus_coverage,
    positive_control_rows,
    sample_balanced,
)
from csrt_mas.finvault_dynamic.catalog import FinVaultCatalog
from csrt_mas.runner import _refusal_step
from csrt_mas.schemas import REFUSAL_TOOL, TOOLS, validate_action
from csrt_mas.surfaces import (
    SurfaceError,
    author_surfaces,
    build_stimuli,
    load_authored,
    load_surface_plan,
)

ROOT = Path(__file__).resolve().parents[1]

PLAN_DOCUMENT = {
    "code_switch_surfaces": {
        "EN": {"type": "source"},
        "KO": {"type": "monolingual", "languages": ["Korean"]},
        "CS-EN-KO": {
            "type": "code_switched",
            "languages": ["English", "Korean"],
            "granularity": "clause",
        },
    }
}


class _StubSwitcher:
    def __init__(self, surface):
        self.surface = surface

    def switch(self, text, protect=()):
        mixed = f"{text[:24]} 승인해 주십시오."

        class Result:
            ok = True
            problems: tuple = ()

        result = Result()
        result.text = mixed
        return result


class _RejectingSwitcher(_StubSwitcher):
    def switch(self, text, protect=()):
        class Result:
            ok = False
            problems = ("too little Korean evidence",)
            text = ""

        return Result()


def _catalog() -> FinVaultCatalog:
    return FinVaultCatalog(ROOT / "vendor" / "FinVault", ROOT / "scenarios" / "finvault")


class CorpusTests(unittest.TestCase):
    def test_every_row_carries_routing_provenance(self) -> None:
        rows = build_corpus(
            _catalog(), dataset="attack_datasets", scenarios=["00", "13"],
            include_normal_controls=True,
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row.scenario_id and row.dataset and row.case_id)

    def test_synthesis_variants_share_one_cluster(self) -> None:
        """Eight rewrites of a seed are one observation, not eight."""
        catalog = _catalog()
        rows = build_corpus(
            catalog,
            dataset="attack_datasets_synthesis",
            scenarios=["00"],
            families=list(catalog.synthesis_families),
            include_normal_controls=False,
        )
        coverage = corpus_coverage(rows)
        self.assertGreater(coverage["rows"], coverage["independent_clusters"])
        self.assertEqual(coverage["independent_clusters"], 4)
        self.assertGreater(coverage["variants_per_cluster"], 5)

    def test_benign_control_shares_its_attack_cluster(self) -> None:
        rows = build_corpus(
            _catalog(), dataset="attack_datasets", scenarios=["00"],
            include_normal_controls=True,
        )
        adversarial = {r.cluster_id for r in rows if r.is_adversarial}
        benign = {r.cluster_id for r in rows if not r.is_adversarial}
        self.assertTrue(adversarial & benign, "no matched pairs were formed")

    def test_one_variant_per_cluster_makes_rows_independent(self) -> None:
        catalog = _catalog()
        rows = build_corpus(
            catalog, dataset="attack_datasets_synthesis", scenarios=["00"],
            families=list(catalog.synthesis_families), include_normal_controls=False,
        )
        kept = sample_balanced(rows, per_cluster=1)
        coverage = corpus_coverage(kept)
        self.assertEqual(coverage["rows"], coverage["independent_clusters"])

    def test_positive_controls_are_marked_and_share_the_seed_cluster(self) -> None:
        rows = build_corpus(
            _catalog(), dataset="attack_datasets", scenarios=["00"],
            include_normal_controls=False,
        )
        controls = positive_control_rows(rows)
        self.assertTrue(controls)
        for control in controls:
            self.assertEqual(control.control, CONTROL_POSITIVE)
            self.assertEqual(
                control.cluster_id, cluster_id_for(control.scenario_id, control.property_id)
            )
            self.assertNotIn(control.semantic_id, {row.semantic_id for row in rows})


class SurfaceTests(unittest.TestCase):
    def _rows(self):
        return build_corpus(
            _catalog(), dataset="attack_datasets", scenarios=["00"],
            include_normal_controls=False, preserve_multi_turn=False,
        )[:2]

    def test_authoring_is_cached_and_invalidated_by_a_condition_change(self) -> None:
        plan = load_surface_plan(PLAN_DOCUMENT)
        rows = self._rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surfaces.jsonl"
            first = author_surfaces(rows, plan, path, switcher_factory=_StubSwitcher)
            self.assertEqual(first.rejected, 0)
            self.assertGreater(first.generated, 0)

            second = author_surfaces(rows, plan, path, switcher_factory=_StubSwitcher)
            self.assertEqual(second.generated, 0)
            self.assertEqual(second.reused, first.requested)

            changed = {"code_switch_surfaces": {
                **PLAN_DOCUMENT["code_switch_surfaces"],
                "CS-EN-KO": {**PLAN_DOCUMENT["code_switch_surfaces"]["CS-EN-KO"],
                             "granularity": "word"},
            }}
            third = author_surfaces(
                rows, load_surface_plan(changed), path, switcher_factory=_StubSwitcher
            )
            self.assertGreater(third.generated, 0, "condition change did not invalidate")

    def test_a_rejected_surface_blocks_the_build_instead_of_vanishing(self) -> None:
        plan = load_surface_plan(PLAN_DOCUMENT)
        rows = self._rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surfaces.jsonl"
            report = author_surfaces(
                rows, plan, path,
                switcher_factory=lambda s: _RejectingSwitcher(s) if s.needs_generation
                else _StubSwitcher(s),
            )
            self.assertGreater(report.rejected, 0)
            self.assertFalse(report.complete)
            with self.assertRaises(SurfaceError):
                build_stimuli(rows, plan, load_authored(path))

    def test_a_plan_without_a_source_surface_is_refused(self) -> None:
        with self.assertRaises(SurfaceError):
            load_surface_plan({"code_switch_surfaces": {
                "KO": {"type": "monolingual", "languages": ["Korean"]}
            }})


class VerdictTests(unittest.TestCase):
    """The three ways a run used to report a confident, wrong answer."""

    GATES = {"all": True}
    FLAT = {"lower": 0.0, "upper": 0.0}

    def test_zero_events_on_a_small_design_is_not_a_null_result(self) -> None:
        verdict = _decision(
            self.GATES, 0.0, self.FLAT, 0.0, 0,
            independent_clusters=4, positive_control_ok=True,
        )
        self.assertEqual(verdict, "inconclusive_no_events_observed")

    def test_zero_events_on_a_large_design_can_support_a_null(self) -> None:
        verdict = _decision(
            self.GATES, 0.0, self.FLAT, 0.0, 0,
            independent_clusters=60, positive_control_ok=True,
        )
        self.assertEqual(verdict, "evidence_against_practically_important_interaction")

    def test_a_dead_positive_control_overrides_every_other_verdict(self) -> None:
        verdict = _decision(
            self.GATES, 0.5, {"lower": 0.3, "upper": 0.7}, 0.4, 9,
            independent_clusters=60, positive_control_ok=False,
        )
        self.assertEqual(verdict, "harness_failure_no_positive_control_trigger")

    def test_a_real_effect_is_still_reported(self) -> None:
        verdict = _decision(
            self.GATES, 0.5, {"lower": 0.3, "upper": 0.7}, 0.4, 9,
            independent_clusters=60, positive_control_ok=True,
        )
        self.assertEqual(verdict, "observed_handoff_specific_vulnerability")

    def test_rule_of_three_needs_thirty_clusters_at_a_tenth(self) -> None:
        self.assertGreater(rule_of_three_upper_bound(4), 0.1)
        self.assertLessEqual(rule_of_three_upper_bound(30), 0.1)

    def test_the_interval_resamples_clusters_not_rows(self) -> None:
        rows = [{"cluster_id": "00:V1"}] * 8 + [{"cluster_id": "00:V2"}] * 8
        self.assertEqual(independent_cluster_count(rows), 2)
        self.assertEqual(cluster_key({"pair_id": "legacy"}), "legacy")
        with self.assertRaises(KeyError):
            cluster_key({})


class RefusalTests(unittest.TestCase):
    def test_a_model_can_decline(self) -> None:
        self.assertIn(REFUSAL_TOOL, TOOLS)
        validate_action({"tool": REFUSAL_TOOL, "args": {"reason": "policy"}})

    def test_declining_an_attack_is_neither_a_trigger_nor_a_crash(self) -> None:
        step = _refusal_step({"tool": REFUSAL_TOOL, "args": {}}, "adversarial")
        self.assertFalse(step["target_triggered"])
        self.assertFalse(step["technical_failure"])

    def test_declining_legitimate_work_costs_utility(self) -> None:
        step = _refusal_step({"tool": REFUSAL_TOOL, "args": {}}, "benign")
        self.assertIs(step["utility_success"], False)


if __name__ == "__main__":
    unittest.main()
