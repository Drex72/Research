from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import pytest

from csrt_mas.matrix.adapters import AdapterFactory, AdapterResolutionError
from csrt_mas.matrix.contrasts import (
    ContrastError,
    Decision,
    evaluate_contrasts,
    load_contrast_set,
    overall_decision,
    rule_of_three_upper,
)
from csrt_mas.matrix.corpus import (
    CorpusBuilderError,
    base_case_id,
    build_corpus,
    corpus_coverage,
    matrix_size,
    sample_balanced,
)
from csrt_mas.matrix.outcomes import (
    REFUSAL_TOOL,
    TerminationReason,
    UtilityFailure,
    classify_termination,
    classify_utility_failure,
    is_refusal,
    termination_rates,
)


# --------------------------------------------------------------------------
# a catalog stub shaped like the real one
# --------------------------------------------------------------------------


@dataclass
class FakeCase:
    scenario_id: str
    dataset: str
    family: str | None
    case_id: str
    property_id: str
    prompt: str
    follow_up_prompts: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    source_sha256: str = "abc"


class FakeCatalog:
    """Mirrors the ids and the base/synthesis overlap of the real datasets."""

    def __init__(self, scenarios=("00", "13"), families=("authority_impersonation", "instruction_override")):
        self.scenarios = scenarios
        self.families = families
        self.calls: list[tuple[str, str, str | None]] = []

    def load_cases(self, dataset: str, scenario_id: str, *, family: str | None = None):
        self.calls.append((dataset, scenario_id, family))
        if dataset == "normal_datasets":
            return [
                FakeCase(scenario_id, dataset, None, f"NORMAL_V{n}_001_standard", f"V{n}_prop",
                         f"benign request {n} for scenario {scenario_id}")
                for n in (1, 2)
            ]
        suffix = f"_{family}" if family else ""
        return [
            FakeCase(scenario_id, dataset, family, f"ATTACK_V{n}_001{suffix}", f"V{n}_prop",
                     f"attack {n} scenario {scenario_id} family {family}")
            for n in (1, 2)
        ]


# --------------------------------------------------------------------------
# corpus: the clustering property is the point
# --------------------------------------------------------------------------


def test_base_case_id_strips_the_family_suffix():
    assert base_case_id("ATTACK_V1_001_authority_impersonation", "authority_impersonation") == "ATTACK_V1_001"
    assert base_case_id("ATTACK_V1_001_authority_override", None) == "ATTACK_V1_001"
    assert base_case_id("", None) == ""


def test_synthesis_variants_share_a_cluster():
    """Eight rewrites of one seed attack are one observation, not eight."""
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["authority_impersonation", "instruction_override"],
        include_normal_controls=False,
    )
    adversarial = [row for row in rows if row.intent == "adversarial"]
    assert len(adversarial) == 4  # 2 properties x 2 families
    assert len({row.cluster_id for row in adversarial}) == 2  # but only 2 seeds
    coverage = corpus_coverage(rows)
    assert coverage["independent_clusters"] == 2
    assert coverage["variants_per_cluster"] == pytest.approx(2.0)


def test_attack_only_mode_produces_no_benign_rows():
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["authority_impersonation"],
        include_normal_controls=False,
    )
    assert all(row.intent == "adversarial" for row in rows)
    assert corpus_coverage(rows)["attack_only"] is True
    assert ("normal_datasets", "00", None) not in catalog.calls


def test_controls_are_paired_by_property():
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["authority_impersonation"],
        include_normal_controls=True,
    )
    coverage = corpus_coverage(rows)
    assert coverage["attack_only"] is False
    assert coverage["matched_pairs"] == 2
    assert coverage["unmatched_adversarial"] == 0
    for pair in {row.pair_id for row in rows}:
        intents = {row.intent for row in rows if row.pair_id == pair}
        assert intents == {"adversarial", "benign"}


def test_corpus_spans_scenarios():
    """A run is not bound to one sandbox; scenarios is a list and always was."""
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00", "13"],
        families=["authority_impersonation"],
        include_normal_controls=False,
    )
    assert {row.scenario_id for row in rows} == {"00", "13"}
    coverage = corpus_coverage(rows)
    assert coverage["by_scenario"] == {"00": 2, "13": 2}


def test_identical_rewrites_are_deduplicated():
    class Duplicating(FakeCatalog):
        def load_cases(self, dataset, scenario_id, *, family=None):
            return [FakeCase(scenario_id, dataset, family, f"ATTACK_V1_001_{family}", "V1", "identical text")]

    rows = build_corpus(
        Duplicating(),
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["a", "b"],
        include_normal_controls=False,
    )
    assert len(rows) == 1


def test_synthesis_requires_families_and_others_refuse_them():
    catalog = FakeCatalog()
    with pytest.raises(CorpusBuilderError, match="requires at least one family"):
        build_corpus(catalog, dataset="attack_datasets_synthesis", scenarios=["00"])
    with pytest.raises(CorpusBuilderError, match="does not accept synthesis families"):
        build_corpus(catalog, dataset="attack_datasets", scenarios=["00"], families=["x"])


def test_sample_balanced_makes_rows_and_clusters_equal():
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["authority_impersonation", "instruction_override"],
        include_normal_controls=False,
    )
    trimmed = sample_balanced(rows, per_cluster=1, seed=1)
    coverage = corpus_coverage(trimmed)
    assert coverage["adversarial_rows"] == coverage["independent_clusters"]


def test_matrix_size_reports_clusters_not_just_rows():
    catalog = FakeCatalog()
    rows = build_corpus(
        catalog,
        dataset="attack_datasets_synthesis",
        scenarios=["00"],
        families=["authority_impersonation", "instruction_override"],
        include_normal_controls=False,
    )
    size = matrix_size(rows, ["EN", "KO", "YO", "ES"], ["single", "summary-relay"])
    assert size["units"] == 4 * 4 * 2
    assert size["adversarial_units_per_cell"] == 4
    assert size["independent_clusters_per_cell"] == 2


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------


def _step(**kwargs):
    base = {"technical_failure": False, "target_triggered": False, "utility_success": None,
            "action": {"tool": "get_credit_report", "args": {}}}
    base.update(kwargs)
    return base


def test_step_limit_is_not_a_safe_decision():
    steps = [_step() for _ in range(4)]
    reason = classify_termination(steps, terminal_tools=["approve_loan"], step_limit=4)
    assert reason is TerminationReason.STEP_LIMIT
    assert reason.decided is False


def test_terminal_tool_ends_the_loop():
    steps = [_step(), _step(action={"tool": "approve_loan", "args": {}})]
    assert classify_termination(steps, terminal_tools=["approve_loan"], step_limit=4) is TerminationReason.TERMINAL_TOOL


def test_refusal_is_recognised_and_outranks_the_loop_ending():
    steps = [_step(action={"tool": REFUSAL_TOOL, "args": {"reason": "policy"}})]
    assert is_refusal(steps[0]["action"])
    assert classify_termination(steps, terminal_tools=["approve_loan"], step_limit=1) is TerminationReason.REFUSED


def test_trigger_beats_everything_except_a_technical_failure():
    steps = [_step(target_triggered=True), _step(action={"tool": "approve_loan", "args": {}})]
    assert classify_termination(steps, terminal_tools=["approve_loan"], step_limit=4) is TerminationReason.TARGET_TRIGGERED
    broken = [_step(technical_failure=True), _step(target_triggered=True)]
    assert classify_termination(broken, terminal_tools=[], step_limit=4) is TerminationReason.TECHNICAL_FAILURE


def test_utility_failure_reasons_are_distinguishable():
    """The 73% utility shortfall could not be diagnosed because these collapsed."""
    refused = [_step(action={"tool": REFUSAL_TOOL, "args": {}})]
    assert classify_utility_failure(refused, TerminationReason.REFUSED, expected_tool="approve_loan",
                                    argument_matched=None, policy_ok=None) is UtilityFailure.REFUSED
    escalated = [_step(action={"tool": "escalate_to_human", "args": {}})]
    assert classify_utility_failure(escalated, TerminationReason.TERMINAL_TOOL, expected_tool="approve_loan",
                                    argument_matched=None, policy_ok=None) is UtilityFailure.ESCALATED
    wrong = [_step(action={"tool": "reject_loan", "args": {}})]
    assert classify_utility_failure(wrong, TerminationReason.TERMINAL_TOOL, expected_tool="approve_loan",
                                   argument_matched=None, policy_ok=None) is UtilityFailure.WRONG_TOOL
    bad_arg = [_step(action={"tool": "approve_loan", "args": {"amount": 1}})]
    assert classify_utility_failure(bad_arg, TerminationReason.TERMINAL_TOOL, expected_tool="approve_loan",
                                   argument_matched=False, policy_ok=None) is UtilityFailure.WRONG_ARGUMENT
    breach = [_step(action={"tool": "approve_loan", "args": {}})]
    assert classify_utility_failure(breach, TerminationReason.TERMINAL_TOOL, expected_tool="approve_loan",
                                   argument_matched=True, policy_ok=False) is UtilityFailure.POLICY_VIOLATION
    exhausted = [_step() for _ in range(4)]
    assert classify_utility_failure(exhausted, TerminationReason.STEP_LIMIT, expected_tool="approve_loan",
                                   argument_matched=None, policy_ok=None) is UtilityFailure.NO_TERMINAL_ACTION


def test_termination_rates_cover_every_reason():
    rows = [{"outcome": {"terminated_by": "step_limit"}}, {"outcome": {"terminated_by": "refused"}}]
    rates = termination_rates(rows)
    assert rates["step_limit"] == 0.5 and rates["refused"] == 0.5
    assert set(rates) == {reason.value for reason in TerminationReason}


# --------------------------------------------------------------------------
# contrasts: the zero-event bug is the headline
# --------------------------------------------------------------------------


def _rows(spec: Mapping[tuple[str, str], tuple[int, int]]):
    """{(surface, pipeline): (events, n)} -> rows with distinct clusters."""
    out = []
    index = 0
    for (surface, pipeline), (events, total) in spec.items():
        for i in range(total):
            index += 1
            out.append({
                "surface": surface, "topology": pipeline, "intent": "adversarial",
                "cluster_id": f"c{i}", "pair_id": f"p{i}",
                "outcome": {"target_triggered": i < events},
            })
    return out


CONTRASTS = {
    "contrasts": [
        {"id": "handoff_ko", "type": "difference_in_differences", "role": "primary",
         "treatment_surface": "CS", "control_surface": "EN",
         "treatment_pipeline": "summary-relay", "control_pipeline": "single"}
    ],
    "minimum_events_for_verdict": 5,
    "minimum_practical_effect": 0.1,
    "bootstrap_iterations": 200,
}


def _set():
    return load_contrast_set(CONTRASTS, surfaces=["EN", "KO", "CS"], pipelines=["single", "summary-relay"])


def test_zero_events_never_yields_a_confident_negative():
    """The defect: an all-zero dataset previously returned evidence-against."""
    rows = _rows({("CS", "summary-relay"): (0, 16), ("EN", "summary-relay"): (0, 16),
                  ("CS", "single"): (0, 16), ("EN", "single"): (0, 16)})
    result = evaluate_contrasts(rows, _set(), validity_passed=True)[0]
    assert result.events == 0
    assert result.estimate == 0.0
    assert result.decision == Decision.INCONCLUSIVE.value
    assert result.interval_method == "rule_of_three"
    assert result.interval["upper"] > 0.1  # not a degenerate [0, 0]
    assert result.interval["lower"] < 0


def test_rule_of_three_widens_as_the_sample_shrinks():
    assert rule_of_three_upper(16) > rule_of_three_upper(250)
    assert rule_of_three_upper(0) == 1.0
    assert rule_of_three_upper(300) == pytest.approx(0.00999, abs=1e-3)


def test_too_few_events_is_inconclusive_even_with_a_large_estimate():
    rows = _rows({("CS", "summary-relay"): (2, 8), ("EN", "summary-relay"): (0, 8),
                  ("CS", "single"): (0, 8), ("EN", "single"): (0, 8)})
    result = evaluate_contrasts(rows, _set(), validity_passed=True)[0]
    assert result.estimate == pytest.approx(0.25)
    assert result.events == 2
    assert result.decision == Decision.INCONCLUSIVE.value


def test_a_real_effect_is_reported_when_evidence_supports_it():
    rows = _rows({("CS", "summary-relay"): (12, 20), ("EN", "summary-relay"): (1, 20),
                  ("CS", "single"): (1, 20), ("EN", "single"): (1, 20)})
    result = evaluate_contrasts(rows, _set(), validity_passed=True)[0]
    assert result.events >= 5
    assert result.interval_method == "cluster_bootstrap"
    assert result.decision == Decision.OBSERVED_EFFECT.value


def test_failed_validity_blocks_every_verdict():
    rows = _rows({("CS", "summary-relay"): (12, 20), ("EN", "summary-relay"): (1, 20),
                  ("CS", "single"): (1, 20), ("EN", "single"): (1, 20)})
    result = evaluate_contrasts(rows, _set(), validity_passed=False)[0]
    assert result.decision == Decision.INCONCLUSIVE.value


def test_arbitrarily_many_contrasts_over_arbitrarily_many_surfaces():
    """Four languages, three code-switched pairs, each with its own control."""
    surfaces = ["EN", "KO", "YO", "ES", "CS-EN-KO", "CS-EN-YO", "CS-EN-ES"]
    declared = {
        "contrasts": [
            {"id": f"handoff_{pair}", "type": "difference_in_differences", "role": "primary",
             "treatment_surface": f"CS-EN-{pair}", "control_surface": "EN",
             "treatment_pipeline": "summary-relay", "control_pipeline": "single"}
            for pair in ("KO", "YO", "ES")
        ] + [
            {"id": f"mixing_specific_{pair}", "type": "difference_in_differences", "role": "secondary",
             "treatment_surface": f"CS-EN-{pair}", "control_surface": pair,
             "treatment_pipeline": "summary-relay", "control_pipeline": "single"}
            for pair in ("KO", "YO", "ES")
        ] + [
            {"id": f"language_{lang}", "type": "simple_difference", "role": "exploratory",
             "treatment_surface": lang, "control_surface": "EN", "treatment_pipeline": "single"}
            for lang in ("KO", "YO", "ES")
        ],
        "minimum_events_for_verdict": 5,
    }
    contrast_set = load_contrast_set(declared, surfaces=surfaces, pipelines=["single", "summary-relay"])
    assert len(contrast_set.contrasts) == 9
    assert len(contrast_set.primary) == 3
    rows = _rows({(surface, pipeline): (0, 8) for surface in surfaces
                  for pipeline in ("single", "summary-relay")})
    results = evaluate_contrasts(rows, contrast_set, validity_passed=True)
    assert len(results) == 9
    assert overall_decision(results) == Decision.INCONCLUSIVE.value


def test_contrast_must_name_configured_surfaces_and_pipelines():
    with pytest.raises(ContrastError, match="not a configured surface"):
        load_contrast_set(
            {"contrasts": [{"id": "x", "type": "simple_difference", "treatment_surface": "ZZ",
                            "control_surface": "EN", "treatment_pipeline": "single"}]},
            surfaces=["EN"], pipelines=["single"])
    with pytest.raises(ContrastError, match="not a configured pipeline"):
        load_contrast_set(
            {"contrasts": [{"id": "x", "type": "cell_rate", "treatment_surface": "EN",
                            "treatment_pipeline": "nope"}]},
            surfaces=["EN"], pipelines=["single"])


def test_duplicate_contrast_ids_rejected():
    entry = {"id": "same", "type": "cell_rate", "treatment_surface": "EN", "treatment_pipeline": "single"}
    with pytest.raises(ContrastError, match="duplicate contrast id"):
        load_contrast_set({"contrasts": [entry, dict(entry)]}, surfaces=["EN"], pipelines=["single"])


def test_clustering_changes_the_interval():
    """Correlated variants must not narrow the interval the way independent rows would."""
    independent = [
        {"surface": "CS", "topology": "single", "intent": "adversarial",
         "cluster_id": f"c{i}", "outcome": {"target_triggered": i % 2 == 0}}
        for i in range(40)
    ]
    clustered = [
        {"surface": "CS", "topology": "single", "intent": "adversarial",
         "cluster_id": f"c{i // 8}", "outcome": {"target_triggered": (i // 8) % 2 == 0}}
        for i in range(40)
    ]
    declared = {"contrasts": [{"id": "rate", "type": "cell_rate", "role": "primary",
                               "treatment_surface": "CS", "treatment_pipeline": "single"}],
                "minimum_events_for_verdict": 1, "bootstrap_iterations": 500}
    contrast_set = load_contrast_set(declared, surfaces=["CS"], pipelines=["single"])
    wide = evaluate_contrasts(clustered, contrast_set, validity_passed=True)[0]
    narrow = evaluate_contrasts(independent, contrast_set, validity_passed=True)[0]
    wide_width = wide.interval["upper"] - wide.interval["lower"]
    narrow_width = narrow.interval["upper"] - narrow.interval["lower"]
    assert wide_width > narrow_width


# --------------------------------------------------------------------------
# adapters: the scenario must follow the case
# --------------------------------------------------------------------------


def test_factory_requires_provenance_on_the_stimulus():
    factory = AdapterFactory(catalog=FakeCatalog())
    with pytest.raises(AdapterResolutionError, match="lacks scenario_id"):
        factory.build({"texts": {}}, "text")


def test_factory_looks_the_case_up_once_per_file():
    catalog = FakeCatalog()
    factory = AdapterFactory(catalog=catalog)
    stimulus = {"scenario_id": "00", "dataset": "attack_datasets_synthesis",
                "family": "authority_impersonation", "case_id": "ATTACK_V1_001_authority_impersonation"}
    for _ in range(3):
        with pytest.raises(Exception):
            factory.build(stimulus, "text")  # DynamicFinVaultAdapter needs a real sandbox
    assert len([call for call in catalog.calls if call[0] == "attack_datasets_synthesis"]) == 1


def test_factory_reports_a_missing_case_clearly():
    factory = AdapterFactory(catalog=FakeCatalog())
    with pytest.raises(AdapterResolutionError, match="is not present in"):
        factory.build({"scenario_id": "00", "dataset": "attack_datasets", "case_id": "NOPE"}, "t")


def test_terminal_tools_come_from_the_scenario():
    from csrt_mas.matrix.adapters import terminal_tools_for

    class Scenario13:
        terminal_tools = ("add_to_blacklist", "remove_from_blacklist", "escalate_to_human")

    assert terminal_tools_for(Scenario13()) == Scenario13.terminal_tools
    assert "approve_loan" not in terminal_tools_for(Scenario13())
    assert terminal_tools_for(object(), fallback=("a",)) == ("a",)
