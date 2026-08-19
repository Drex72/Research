"""A scenario-independent case corpus.

The compatibility path read one JSONL file whose rows had already been shaped
for the credit sandbox. This builds the corpus directly from the FinVault
catalog instead, for any scenario, any dataset and any set of synthesis
families, and emits exactly the seven keys the runner consumes.

One thing here is not a convenience, it is a correctness requirement. The
synthesis datasets are rewrites: ``authority_impersonation`` and
``instruction_override`` both contain a row with the same ``id`` as the base
attack it was derived from, differing only in ``attack_prompt``. Eight families
of one seed attack are eight rewordings of one observation, not eight
observations. If the interval resamples them independently, the sample looks
eight times larger than it is. So every row carries a ``cluster_id`` equal to
its base case, and the bootstrap resamples clusters.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# Synthesis ids look like ATTACK_V1_001_authority_override; the base case is
# the part that identifies the seed, which the family suffix decorates.
# Each stripped segment must start with a letter, so a numeric part of the
# seed id (ATTACK_V1_001) is never mistaken for a family suffix.
_ID_SUFFIX = re.compile(r"_(?:[a-z][a-z0-9]*_)*[a-z][a-z0-9]*$")


class CorpusBuilderError(ValueError):
    """Raised when a corpus cannot be built as specified."""


@dataclass(frozen=True)
class CorpusRow:
    """One case in one intent, before language surfaces are attached."""

    semantic_id: str
    pair_id: str
    cluster_id: str
    property_id: str
    frame: str
    intent: str
    scenario_id: str
    dataset: str
    family: str | None
    case_id: str
    source_text: str
    follow_ups: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    source_sha256: str = ""

    def as_stimulus(self, texts: Mapping[str, str]) -> dict[str, Any]:
        """The dict the runner consumes, with surfaces attached."""
        return {
            "semantic_id": self.semantic_id,
            "pair_id": self.pair_id,
            "cluster_id": self.cluster_id,
            "property_id": self.property_id,
            "frame": self.frame,
            "intent": self.intent,
            "scenario_id": self.scenario_id,
            "dataset": self.dataset,
            "family": self.family,
            "case_id": self.case_id,
            "texts": dict(texts),
            "text_sha256": {
                surface: hashlib.sha256(text.encode("utf-8")).hexdigest()
                for surface, text in texts.items()
            },
        }


def base_case_id(case_id: str, family: str | None) -> str:
    """The seed case a synthesis variant was derived from.

    Prefers stripping the family suffix when it is present, because that is
    exact. Falls back to stripping one trailing token, which handles ids whose
    suffix names the technique rather than the family.
    """
    if not case_id:
        return ""
    if family:
        for suffix in (f"_{family}", f"-{family}"):
            if case_id.endswith(suffix):
                return case_id[: -len(suffix)]
    trimmed = _ID_SUFFIX.sub("", case_id)
    return trimmed or case_id


def _text_of(case: Any) -> str:
    text = getattr(case, "prompt", "") or ""
    return str(text).strip()


def build_corpus(
    catalog: Any,
    *,
    dataset: str,
    scenarios: Sequence[str],
    families: Sequence[str] | None = None,
    include_normal_controls: bool = True,
    deduplicate: bool = True,
    limit_per_cell: int | None = None,
) -> list[CorpusRow]:
    """Build a corpus from the catalog.

    ``deduplicate`` drops a synthesis row whose text is identical to the base
    attack it was derived from, which happens when a rewrite made no change.
    ``limit_per_cell`` caps rows per (scenario, family, property) so a large
    corpus can be sampled without unbalancing the design.
    """
    if not scenarios:
        raise CorpusBuilderError("at least one scenario is required")
    if dataset == "attack_datasets_synthesis" and not families:
        raise CorpusBuilderError("attack_datasets_synthesis requires at least one family")
    if dataset != "attack_datasets_synthesis" and families:
        raise CorpusBuilderError(f"{dataset} does not accept synthesis families")

    rows: list[CorpusRow] = []
    seen_text: set[str] = set()
    per_cell: Counter[tuple[str, str, str]] = Counter()

    for scenario_id in scenarios:
        # Benign controls first, so an attack can find its twin by property.
        controls: dict[str, Any] = {}
        if include_normal_controls:
            for case in catalog.load_cases("normal_datasets", scenario_id):
                controls.setdefault(str(getattr(case, "property_id", "") or ""), case)

        for family in list(families or [None]):
            cases = catalog.load_cases(dataset, scenario_id, family=family)
            for case in cases:
                text = _text_of(case)
                if not text:
                    continue
                property_id = str(getattr(case, "property_id", "") or "unspecified")
                case_id = str(getattr(case, "case_id", "") or "")
                cluster = base_case_id(case_id, family)
                frame = family or dataset
                cell = (scenario_id, frame, property_id)
                if limit_per_cell is not None and per_cell[cell] >= limit_per_cell:
                    continue
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if deduplicate and digest in seen_text:
                    continue
                seen_text.add(digest)
                per_cell[cell] += 1

                pair_id = f"{scenario_id}:{cluster}:{frame}"
                rows.append(
                    CorpusRow(
                        semantic_id=f"{pair_id}:adversarial",
                        pair_id=pair_id,
                        cluster_id=f"{scenario_id}:{cluster}",
                        property_id=property_id,
                        frame=frame,
                        intent="adversarial",
                        scenario_id=scenario_id,
                        dataset=dataset,
                        family=family,
                        case_id=case_id,
                        source_text=text,
                        follow_ups=tuple(getattr(case, "follow_up_prompts", ()) or ()),
                        raw=dict(getattr(case, "raw", {}) or {}),
                        source_sha256=str(getattr(case, "source_sha256", "") or ""),
                    )
                )

                control = controls.get(property_id)
                if control is not None:
                    control_text = _text_of(control)
                    if control_text:
                        rows.append(
                            CorpusRow(
                                semantic_id=f"{pair_id}:benign",
                                pair_id=pair_id,
                                cluster_id=f"{scenario_id}:{cluster}",
                                property_id=property_id,
                                frame=frame,
                                intent="benign",
                                scenario_id=scenario_id,
                                dataset="normal_datasets",
                                family=None,
                                case_id=str(getattr(control, "case_id", "") or ""),
                                source_text=control_text,
                                follow_ups=tuple(
                                    getattr(control, "follow_up_prompts", ()) or ()
                                ),
                                raw=dict(getattr(control, "raw", {}) or {}),
                                source_sha256=str(
                                    getattr(control, "source_sha256", "") or ""
                                ),
                            )
                        )
    if not rows:
        raise CorpusBuilderError("the selected dataset and scenarios produced no cases")
    return rows


def corpus_coverage(rows: Sequence[CorpusRow]) -> dict[str, Any]:
    """What the corpus actually covers, for the report and for sanity checks.

    ``independent_clusters`` is the number that matters for the interval. When
    it is much smaller than ``rows``, the corpus is wide but shallow and any
    interval computed as though rows were independent is too narrow.
    """
    adversarial = [row for row in rows if row.intent == "adversarial"]
    benign = [row for row in rows if row.intent == "benign"]
    clusters = {row.cluster_id for row in rows}
    by_family: dict[str, int] = defaultdict(int)
    by_property: dict[str, int] = defaultdict(int)
    by_scenario: dict[str, int] = defaultdict(int)
    for row in adversarial:
        by_family[row.frame] += 1
        by_property[row.property_id] += 1
        by_scenario[row.scenario_id] += 1
    paired = {row.pair_id for row in adversarial} & {row.pair_id for row in benign}
    return {
        "rows": len(rows),
        "adversarial_rows": len(adversarial),
        "benign_rows": len(benign),
        "independent_clusters": len(clusters),
        "variants_per_cluster": (len(adversarial) / len(clusters)) if clusters else 0.0,
        "matched_pairs": len(paired),
        "unmatched_adversarial": len(
            {row.pair_id for row in adversarial} - {row.pair_id for row in benign}
        ),
        "by_family": dict(sorted(by_family.items())),
        "by_property": dict(sorted(by_property.items())),
        "by_scenario": dict(sorted(by_scenario.items())),
        "attack_only": not benign,
    }


def matrix_size(
    rows: Sequence[CorpusRow], surfaces: Sequence[str], pipelines: Sequence[str]
) -> dict[str, int]:
    """How many run units the design implies, before anything is executed."""
    units = len(rows) * len(surfaces) * len(pipelines)
    adversarial = sum(1 for row in rows if row.intent == "adversarial")
    clusters = len({row.cluster_id for row in rows})
    return {
        "rows": len(rows),
        "surfaces": len(surfaces),
        "pipelines": len(pipelines),
        "units": units,
        "adversarial_units": adversarial * len(surfaces) * len(pipelines),
        "adversarial_units_per_cell": adversarial,
        "independent_clusters_per_cell": clusters,
    }


def sample_balanced(
    rows: Sequence[CorpusRow], *, per_cluster: int, seed: int = 0
) -> list[CorpusRow]:
    """Keep at most ``per_cluster`` adversarial variants of each base case.

    Use this to trade breadth for independence: taking one variant per cluster
    makes rows and clusters equal, which is the only configuration where
    treating rows as independent observations is honest.
    """
    import random

    rng = random.Random(seed)
    grouped: dict[str, list[CorpusRow]] = defaultdict(list)
    kept: list[CorpusRow] = []
    for row in rows:
        if row.intent != "adversarial":
            kept.append(row)
            continue
        grouped[row.cluster_id].append(row)
    for cluster in sorted(grouped):
        variants = sorted(grouped[cluster], key=lambda item: item.semantic_id)
        rng.shuffle(variants)
        kept.extend(variants[:per_cluster])
    return sorted(kept, key=lambda item: (item.cluster_id, item.intent, item.semantic_id))
