"""One step from ``experiment.json`` to runnable stimuli.

    dataset  ->  corpus (with provenance)  ->  code-switched surfaces  ->  stimuli

Everything that decides *what* runs is in ``experiment.json``: which scenarios,
which dataset and families, whether benign controls are included, whether
positive controls are added, and which language surfaces exist. Nothing here is
tied to a scenario or a sandbox. Adding scenario 07 is an edit to
``dynamic_finvault.dataset.scenarios``; adding a Yoruba condition is an entry
under ``code_switch_surfaces``.

This runs before ``freeze``, so the package contains the exact stimulus bytes
and the run is reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import CONFIG, STIMULI_PATH
from .corpus import (
    CorpusRow,
    build_corpus,
    corpus_coverage,
    matrix_size,
    positive_control_rows,
    sample_balanced,
)
from .finvault_dynamic.catalog import FinVaultCatalog
from .surfaces import (
    Surface,
    SurfaceError,
    author_surfaces,
    build_stimuli,
    default_switcher_factory,
    load_authored,
    load_surface_plan,
    write_stimuli,
)

DEFAULT_SURFACES_PATH = Path("scenarios/finvault/authored-surfaces.jsonl")


def _experiment_document() -> dict[str, Any]:
    return json.loads(Path(CONFIG.path).read_text(encoding="utf-8"))


def catalog_for(document: Mapping[str, Any] | None = None) -> FinVaultCatalog:
    from .adapters import default_catalog

    return default_catalog()


def selected_corpus(
    catalog: FinVaultCatalog, document: Mapping[str, Any]
) -> list[CorpusRow]:
    """The cases this experiment selects, plus its positive controls."""
    dynamic = document.get("dynamic_finvault")
    if not isinstance(dynamic, Mapping):
        raise SurfaceError("experiment.json needs a dynamic_finvault block")
    dataset_block = dynamic.get("dataset")
    if not isinstance(dataset_block, Mapping):
        raise SurfaceError("dynamic_finvault.dataset must be an object")

    scenarios = list(dataset_block.get("scenarios") or [])
    if not scenarios:
        raise SurfaceError("dynamic_finvault.dataset.scenarios is empty")
    families = list(dataset_block.get("families") or []) or None
    dataset = str(dataset_block.get("name") or "attack_datasets_synthesis")

    rows = build_corpus(
        catalog,
        dataset=dataset,
        scenarios=scenarios,
        families=families,
        include_normal_controls=bool(dataset_block.get("include_normal_controls", True)),
        preserve_multi_turn=bool(dataset_block.get("preserve_multi_turn", True)),
    )

    # Drop benign controls whose workflow the scenario spec marks unscoreable.
    # Running one produces a guaranteed tool error, which inflates the technical
    # failure rate and fails a validity gate for a reason that has nothing to do
    # with the agent. The exclusion is declared in the spec, with its reason, so
    # it appears in the record rather than in someone's memory.
    excluded: list[str] = []
    for scenario_id in scenarios:
        spec = catalog.spec(scenario_id, required=False)
        if spec is None:
            continue
        for property_id, rule in (spec.utility_rules or {}).items():
            if isinstance(rule, Mapping) and rule.get("unscoreable"):
                excluded.append(f"{scenario_id}:{property_id}")
    if excluded:
        blocked = set(excluded)
        rows = [
            row
            for row in rows
            if row.is_adversarial
            or f"{row.scenario_id}:{row.property_id}" not in blocked
        ]

    per_cluster = dataset_block.get("variants_per_cluster")
    if isinstance(per_cluster, int) and per_cluster > 0:
        rows = sample_balanced(rows, per_cluster=per_cluster)

    controls = dataset_block.get("positive_controls_per_scenario", 1)
    if isinstance(controls, int) and controls > 0:
        # Derived from the base attacks, which are always available whichever
        # synthesis families the design selects.
        base = build_corpus(
            catalog,
            dataset="attack_datasets",
            scenarios=scenarios,
            include_normal_controls=False,
            preserve_multi_turn=False,
        )
        rows = rows + positive_control_rows(base, per_scenario=controls)

    rows.sort(key=lambda item: item.semantic_id)
    return rows


def surface_plan(document: Mapping[str, Any]) -> dict[str, Surface]:
    return load_surface_plan(document)


def prepare(
    *,
    switcher_factory=default_switcher_factory,
    surfaces_path: Path | None = None,
    stimuli_path: Path | None = None,
    limit: int | None = None,
    reuse: bool = True,
    require_reviewed: bool = False,
) -> dict[str, Any]:
    """Author every surface and write the stimulus file the runner reads.

    Returns a summary with no stimulus text in it: identifiers, counts and
    hashes only, so it is safe to print.
    """
    document = _experiment_document()
    catalog = catalog_for(document)
    rows = selected_corpus(catalog, document)
    plan = surface_plan(document)

    declared = set(CONFIG.surfaces)
    if declared and declared != set(plan):
        raise SurfaceError(
            "experiment.json 'languages' and 'code_switch_surfaces' disagree: "
            f"{sorted(declared)} vs {sorted(plan)}"
        )

    surfaces_file = Path(surfaces_path or DEFAULT_SURFACES_PATH)
    report = author_surfaces(
        rows,
        plan,
        surfaces_file,
        switcher_factory=switcher_factory,
        reuse=reuse,
        limit=limit,
    )

    summary: dict[str, Any] = {
        "scenarios": sorted({row.scenario_id for row in rows}),
        "surfaces": sorted(plan),
        "coverage": corpus_coverage(rows),
        "authoring": report.as_dict(),
        "surfaces_path": str(surfaces_file),
    }

    if not report.complete:
        summary["stimuli_written"] = 0
        summary["blocked"] = (
            f"{report.rejected} surface(s) were rejected; stimuli were not "
            "written. Review the rejections, adjust the condition or the model, "
            "and run prepare again."
        )
        return summary

    authored = load_authored(surfaces_file)
    stimuli = build_stimuli(rows, plan, authored, require_reviewed=require_reviewed)
    target = Path(stimuli_path or STIMULI_PATH)
    write_stimuli(stimuli, target)
    summary["stimuli_written"] = len(stimuli)
    summary["stimuli_path"] = str(target)
    summary["run_size"] = matrix_size(rows, sorted(plan), list(CONFIG.topologies))
    return summary


def describe(document: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What the current configuration implies, without generating anything."""
    document = document or _experiment_document()
    catalog = catalog_for(document)
    rows = selected_corpus(catalog, document)
    plan = surface_plan(document)
    coverage = corpus_coverage(rows)
    size = matrix_size(rows, sorted(plan), list(CONFIG.topologies))
    clusters = coverage["independent_clusters"]
    return {
        "scenarios": coverage["scenarios"],
        "surfaces": sorted(plan),
        "topologies": list(CONFIG.topologies),
        "coverage": coverage,
        "run_size": size,
        "interval_note": (
            f"{size['adversarial_rows_per_cell']} adversarial rows per cell rest on "
            f"{size['independent_clusters_per_cell']} independent clusters; the "
            "interval is built on the clusters"
        ),
        "zero_event_bound": 3.0 / clusters if clusters else None,
    }
