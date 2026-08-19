#!/usr/bin/env python3
"""Size a run before you commit compute to it.

Standard library only, no model calls, no experiment configuration. It reads
the real FinVault catalog and tells you how many run units a design implies and
how many *independent* observations sit underneath them.

    python3 scripts/plan_matrix.py --scenarios 00 --families all \
        --surfaces EN KO YO ES CS-EN-KO CS-EN-YO CS-EN-ES \
        --pipelines single summary-relay

    python3 scripts/plan_matrix.py --scenarios all --families all --attack-only
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from csrt_mas.finvault_dynamic.catalog import FinVaultCatalog  # noqa: E402
from csrt_mas.matrix.corpus import (  # noqa: E402
    build_corpus,
    corpus_coverage,
    matrix_size,
    sample_balanced,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", nargs="+", default=["00"], help="ids, or 'all'")
    parser.add_argument("--dataset", default="attack_datasets_synthesis",
                        choices=["attack_datasets", "attack_datasets_synthesis"])
    parser.add_argument("--families", nargs="+", default=["all"], help="family names, or 'all'")
    parser.add_argument("--surfaces", nargs="+", default=["EN", "KO", "YO", "ES"])
    parser.add_argument("--pipelines", nargs="+", default=["single", "summary-relay"])
    parser.add_argument("--attack-only", action="store_true", help="drop the benign controls")
    parser.add_argument("--per-cluster", type=int, help="keep at most N variants of each seed case")
    parser.add_argument("--seconds-per-unit", type=float, default=60.0)
    args = parser.parse_args()

    catalog = FinVaultCatalog(ROOT / "vendor" / "FinVault", ROOT / "scenarios" / "finvault")
    scenarios = list(catalog.scenario_ids) if args.scenarios == ["all"] else args.scenarios
    families = None
    if args.dataset == "attack_datasets_synthesis":
        families = list(catalog.synthesis_families) if args.families == ["all"] else args.families

    rows = build_corpus(
        catalog,
        dataset=args.dataset,
        scenarios=scenarios,
        families=families,
        include_normal_controls=not args.attack_only,
    )
    if args.per_cluster:
        rows = sample_balanced(rows, per_cluster=args.per_cluster)

    coverage = corpus_coverage(rows)
    size = matrix_size(rows, args.surfaces, args.pipelines)

    print("DESIGN")
    print(f"  dataset            : {args.dataset}")
    print(f"  scenarios          : {len(scenarios)}  {scenarios[:8]}{' ...' if len(scenarios) > 8 else ''}")
    if families:
        print(f"  synthesis families : {len(families)}")
    print(f"  surfaces           : {len(args.surfaces)}  {args.surfaces}")
    print(f"  pipelines          : {len(args.pipelines)}  {args.pipelines}")
    print(f"  benign controls    : {'no (attack-only, exploratory)' if args.attack_only else 'yes'}")

    print("\nCORPUS")
    print(f"  rows               : {coverage['rows']}")
    print(f"  adversarial        : {coverage['adversarial_rows']}")
    print(f"  benign             : {coverage['benign_rows']}")
    print(f"  matched pairs      : {coverage['matched_pairs']}")

    print("\nINDEPENDENCE  (this is what the interval is built on)")
    print(f"  independent clusters : {coverage['independent_clusters']}")
    print(f"  variants per cluster : {coverage['variants_per_cluster']:.2f}")
    if coverage["variants_per_cluster"] > 1.5:
        print("  NOTE: synthesis variants are rewrites of the same seed cases. The")
        print("        evidence is the cluster count, not the row count. Adding more")
        print("        families widens coverage but adds no independent observations.")

    print("\nRUN SIZE")
    print(f"  total units        : {size['units']}")
    print(f"  adversarial units  : {size['adversarial_units']}")
    hours = size["units"] * args.seconds_per_unit / 3600
    print(f"  rough wall clock   : {hours:.1f} h at {args.seconds_per_unit:.0f}s per unit")

    print("\nPER CELL  (one surface x one pipeline)")
    print(f"  adversarial rows     : {size['adversarial_units_per_cell']}")
    print(f"  independent clusters : {size['independent_clusters_per_cell']}")

    n = size["independent_clusters_per_cell"]
    if n:
        # Half-width of a 95% interval on a difference-in-differences across
        # four cells, at an assumed rate, using clusters as the sample size.
        import math

        for rate in (0.1, 0.2):
            half = 1.96 * math.sqrt(4 * rate * (1 - rate) / n)
            print(f"  95% interval half-width on a 4-cell interaction at p={rate:.1f}: +/- {half:.2f}")
        print("  Compare that against the effect size you would call meaningful.")
    print("\nCoverage by family:", coverage["by_family"])
    print("Coverage by property:", coverage["by_property"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
