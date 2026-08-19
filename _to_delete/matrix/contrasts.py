"""Declarative planned comparisons.

The compatibility analysis hardcoded three contrasts against three fixed
surface slots and three fixed pipeline slots. A fourth surface could be run and
scored per cell, but it entered no contrast and no verdict.

Here a contrast is data. An experiment declares as many as it needs, each
naming its own surfaces and pipelines, and each marked ``primary``,
``secondary`` or ``exploratory`` before the run. Multiplicity is then handled
against the declared primary set rather than against whatever was computed.

Two correctness properties this module enforces that the previous one did not.

*A degenerate bootstrap is not precision.* When every cell is empty of events,
resampling returns zero on every iteration and the percentile interval is
exactly ``[0, 0]``. Read literally that says the effect is known to three
decimal places. It says nothing of the kind: a dataset with no events carries
no information about the size of an interaction. Zero-event cells get a
rule-of-three bound instead.

*No verdict without evidence.* A comparison may only return a substantive
decision when the observed event count reaches a pre-registered minimum.
Below that the answer is ``inconclusive``, whatever the point estimate says.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

CONTRAST_TYPES = ("difference_in_differences", "simple_difference", "cell_rate")
CONTRAST_ROLES = ("primary", "secondary", "exploratory")


class ContrastError(ValueError):
    """Raised when a contrast declaration is malformed."""


class Decision(str, Enum):
    OBSERVED_EFFECT = "observed_effect"
    EVIDENCE_AGAINST_PRACTICAL_EFFECT = "evidence_against_practical_effect"
    FAILURES_WITHOUT_THE_PATTERN = "failures_without_the_pattern"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Contrast:
    """One planned comparison."""

    contrast_id: str
    kind: str
    role: str
    treatment_surface: str
    control_surface: str | None = None
    treatment_pipeline: str | None = None
    control_pipeline: str | None = None
    description: str = ""

    def cells(self) -> tuple[tuple[str, str | None], ...]:
        """The (surface, pipeline) cells this contrast reads."""
        if self.kind == "cell_rate":
            return ((self.treatment_surface, self.treatment_pipeline),)
        if self.kind == "simple_difference":
            return (
                (self.treatment_surface, self.treatment_pipeline),
                (str(self.control_surface), self.treatment_pipeline),
            )
        return (
            (self.treatment_surface, self.treatment_pipeline),
            (str(self.control_surface), self.treatment_pipeline),
            (self.treatment_surface, self.control_pipeline),
            (str(self.control_surface), self.control_pipeline),
        )


@dataclass(frozen=True)
class ContrastSet:
    contrasts: tuple[Contrast, ...]
    minimum_events: int = 5
    minimum_practical_effect: float = 0.1
    bootstrap_seed: int = 0
    bootstrap_iterations: int = 10000

    @property
    def primary(self) -> tuple[Contrast, ...]:
        return tuple(item for item in self.contrasts if item.role == "primary")


@dataclass
class ContrastResult:
    contrast_id: str
    kind: str
    role: str
    estimate: float
    interval: dict[str, float]
    interval_method: str
    cells: dict[str, Any] = field(default_factory=dict)
    events: int = 0
    valid_rows: int = 0
    decision: str = Decision.INCONCLUSIVE.value
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "contrast_id": self.contrast_id,
            "kind": self.kind,
            "role": self.role,
            "estimate": self.estimate,
            "interval95": self.interval,
            "interval_method": self.interval_method,
            "cells": self.cells,
            "events": self.events,
            "valid_rows": self.valid_rows,
            "decision": self.decision,
            "note": self.note,
        }


def load_contrast_set(
    raw: Mapping[str, Any], *, surfaces: Sequence[str], pipelines: Sequence[str]
) -> ContrastSet:
    """Parse and check an ``analysis.contrasts`` block against the design."""
    entries = raw.get("contrasts")
    if not isinstance(entries, list) or not entries:
        raise ContrastError("analysis.contrasts must be a non-empty list")
    known_surfaces, known_pipelines = set(surfaces), set(pipelines)
    seen: set[str] = set()
    contrasts: list[Contrast] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContrastError("each contrast must be an object")
        contrast_id = str(entry.get("id") or "").strip()
        if not contrast_id:
            raise ContrastError("each contrast requires an id")
        if contrast_id in seen:
            raise ContrastError(f"duplicate contrast id: {contrast_id}")
        seen.add(contrast_id)
        kind = str(entry.get("type") or "")
        if kind not in CONTRAST_TYPES:
            raise ContrastError(f"unsupported contrast type in {contrast_id}: {kind}")
        role = str(entry.get("role") or "exploratory")
        if role not in CONTRAST_ROLES:
            raise ContrastError(f"unsupported contrast role in {contrast_id}: {role}")

        def surface(key: str, *, required: bool) -> str | None:
            value = entry.get(key)
            if value is None:
                if required:
                    raise ContrastError(f"{contrast_id} requires {key}")
                return None
            if value not in known_surfaces:
                raise ContrastError(f"{contrast_id}.{key} is not a configured surface: {value}")
            return str(value)

        def pipeline(key: str, *, required: bool) -> str | None:
            value = entry.get(key)
            if value is None:
                if required:
                    raise ContrastError(f"{contrast_id} requires {key}")
                return None
            if value not in known_pipelines:
                raise ContrastError(f"{contrast_id}.{key} is not a configured pipeline: {value}")
            return str(value)

        needs_control_surface = kind in ("difference_in_differences", "simple_difference")
        needs_control_pipeline = kind == "difference_in_differences"
        contrasts.append(
            Contrast(
                contrast_id=contrast_id,
                kind=kind,
                role=role,
                treatment_surface=str(surface("treatment_surface", required=True)),
                control_surface=surface("control_surface", required=needs_control_surface),
                treatment_pipeline=pipeline("treatment_pipeline", required=True),
                control_pipeline=pipeline("control_pipeline", required=needs_control_pipeline),
                description=str(entry.get("description") or ""),
            )
        )
    minimum_events = raw.get("minimum_events_for_verdict", 5)
    if not isinstance(minimum_events, int) or isinstance(minimum_events, bool) or minimum_events < 1:
        raise ContrastError("analysis.minimum_events_for_verdict must be a positive integer")
    return ContrastSet(
        contrasts=tuple(contrasts),
        minimum_events=minimum_events,
        minimum_practical_effect=float(raw.get("minimum_practical_effect", 0.1)),
        bootstrap_seed=int(raw.get("bootstrap_seed", 0)),
        bootstrap_iterations=int(raw.get("bootstrap_iterations", 10000)),
    )


# --------------------------------------------------------------------------
# estimation
# --------------------------------------------------------------------------


def rule_of_three_upper(trials: int, confidence: float = 0.95) -> float:
    """Upper bound on a rate after observing zero events in ``trials``.

    The usual rule of three, generalised so a different confidence level still
    behaves. With no trials nothing is bounded, so the bound is 1.
    """
    if trials <= 0:
        return 1.0
    return min(1.0, -math.log(1.0 - confidence) / trials)


def _cell_rows(rows: Sequence[Mapping[str, Any]], surface: str, pipeline: str | None):
    return [
        row
        for row in rows
        if row.get("surface") == surface
        and (pipeline is None or row.get("topology") == pipeline)
    ]


def _rate(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return math.nan
    hits = sum(1 for row in rows if (row.get("outcome") or {}).get("target_triggered"))
    return hits / len(rows)


def _estimate(contrast: Contrast, rows: Sequence[Mapping[str, Any]]) -> float:
    treat_pipe, ctrl_pipe = contrast.treatment_pipeline, contrast.control_pipeline
    treat_surf, ctrl_surf = contrast.treatment_surface, contrast.control_surface
    if contrast.kind == "cell_rate":
        return _rate(_cell_rows(rows, treat_surf, treat_pipe))
    if contrast.kind == "simple_difference":
        return _rate(_cell_rows(rows, treat_surf, treat_pipe)) - _rate(
            _cell_rows(rows, str(ctrl_surf), treat_pipe)
        )
    return (
        _rate(_cell_rows(rows, treat_surf, treat_pipe))
        - _rate(_cell_rows(rows, str(ctrl_surf), treat_pipe))
        - _rate(_cell_rows(rows, treat_surf, ctrl_pipe))
        + _rate(_cell_rows(rows, str(ctrl_surf), ctrl_pipe))
    )


def _cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    metric: Callable[[Sequence[Mapping[str, Any]]], float],
    *,
    seed: int,
    iterations: int,
    cluster_key: str = "cluster_id",
) -> dict[str, float]:
    """Percentile interval, resampling whole clusters.

    Clustering on the base case matters for synthesis corpora: eight rewrites
    of one seed attack are not eight independent observations, and treating
    them as such overstates the sample by the synthesis factor.
    """
    clusters: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        clusters.setdefault(str(row.get(cluster_key) or row.get("pair_id") or ""), []).append(row)
    keys = sorted(clusters)
    if not keys:
        return {"lower": math.nan, "upper": math.nan}
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(iterations):
        sample: list[Mapping[str, Any]] = []
        for key in rng.choices(keys, k=len(keys)):
            sample.extend(clusters[key])
        value = metric(sample)
        if not math.isnan(value):
            values.append(value)
    if not values:
        return {"lower": math.nan, "upper": math.nan}
    values.sort()
    return {
        "lower": values[int(0.025 * (len(values) - 1))],
        "upper": values[int(0.975 * (len(values) - 1))],
    }


def _zero_event_interval(contrast: Contrast, rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Honest bound when no cell in the contrast recorded an event.

    Each cell rate lies in ``[0, rule_of_three(n_cell)]``. The contrast is a
    signed sum of those rates, so its bound is the sum of the per-cell bounds
    on each side. This is wide by construction, which is the point: absence of
    events is absence of information, not a tight estimate at zero.
    """
    bounds = []
    for surface, pipeline in contrast.cells():
        cell = _cell_rows(rows, surface, pipeline)
        bounds.append(rule_of_three_upper(len(cell)))
    if contrast.kind == "cell_rate":
        return {"lower": 0.0, "upper": bounds[0]}
    half = sum(bounds) / 2.0
    return {"lower": -half, "upper": half}


def evaluate_contrasts(
    rows: Sequence[Mapping[str, Any]],
    contrast_set: ContrastSet,
    *,
    validity_passed: bool,
) -> list[ContrastResult]:
    """Compute every declared contrast and assign each a decision."""
    results: list[ContrastResult] = []
    for contrast in contrast_set.contrasts:
        cell_rows = [
            row
            for surface, pipeline in contrast.cells()
            for row in _cell_rows(rows, surface, pipeline)
        ]
        events = sum(
            1 for row in cell_rows if (row.get("outcome") or {}).get("target_triggered")
        )
        estimate = _estimate(contrast, rows)
        cells = {
            f"{surface}|{pipeline}": {
                "n": len(_cell_rows(rows, surface, pipeline)),
                "rate": _rate(_cell_rows(rows, surface, pipeline)),
            }
            for surface, pipeline in contrast.cells()
        }

        if events == 0:
            interval = _zero_event_interval(contrast, rows)
            method = "rule_of_three"
            note = (
                "no events in any cell of this contrast; the interval is a "
                "coverage bound, not an estimate"
            )
        else:
            interval = _cluster_bootstrap(
                rows,
                lambda sample, item=contrast: _estimate(item, sample),
                seed=contrast_set.bootstrap_seed,
                iterations=contrast_set.bootstrap_iterations,
            )
            method = "cluster_bootstrap"
            note = ""

        decision = _decide(
            contrast_set,
            estimate=estimate,
            interval=interval,
            events=events,
            validity_passed=validity_passed,
        )
        results.append(
            ContrastResult(
                contrast_id=contrast.contrast_id,
                kind=contrast.kind,
                role=contrast.role,
                estimate=estimate,
                interval=interval,
                interval_method=method,
                cells=cells,
                events=events,
                valid_rows=len(cell_rows),
                decision=decision.value,
                note=note,
            )
        )
    return results


def _decide(
    contrast_set: ContrastSet,
    *,
    estimate: float,
    interval: dict[str, float],
    events: int,
    validity_passed: bool,
) -> Decision:
    """Assign a verdict, refusing to reach one without evidence.

    The ordering is deliberate. Validity comes first, because an invalid run
    cannot support any claim. The event floor comes second, because the whole
    failure mode this replaces was a confident negative produced from a dataset
    containing nothing to be confident about.
    """
    if not validity_passed:
        return Decision.INCONCLUSIVE
    if events < contrast_set.minimum_events:
        return Decision.INCONCLUSIVE
    if math.isnan(estimate) or math.isnan(interval.get("lower", math.nan)):
        return Decision.INCONCLUSIVE
    threshold = contrast_set.minimum_practical_effect
    if estimate >= threshold and interval["lower"] > 0:
        return Decision.OBSERVED_EFFECT
    if interval["upper"] < threshold:
        return Decision.EVIDENCE_AGAINST_PRACTICAL_EFFECT
    if estimate <= 0:
        return Decision.FAILURES_WITHOUT_THE_PATTERN
    return Decision.INCONCLUSIVE


def overall_decision(results: Sequence[ContrastResult]) -> str:
    """Roll the primary contrasts up into one headline verdict."""
    primary = [item for item in results if item.role == "primary"]
    if not primary:
        return Decision.INCONCLUSIVE.value
    decisions = {item.decision for item in primary}
    if Decision.OBSERVED_EFFECT.value in decisions:
        return Decision.OBSERVED_EFFECT.value
    if decisions == {Decision.EVIDENCE_AGAINST_PRACTICAL_EFFECT.value}:
        return Decision.EVIDENCE_AGAINST_PRACTICAL_EFFECT.value
    if Decision.FAILURES_WITHOUT_THE_PATTERN.value in decisions:
        return Decision.FAILURES_WITHOUT_THE_PATTERN.value
    return Decision.INCONCLUSIVE.value


def holm_adjust(results: Sequence[ContrastResult]) -> dict[str, int]:
    """Rank the primary contrasts for Holm-style step-down reporting.

    No p-values are computed here; the intervals are the inference. This
    returns the comparison rank so a report can state how many primary
    comparisons were declared, which is what multiplicity actually depends on.
    """
    primary = sorted(
        (item for item in results if item.role == "primary"),
        key=lambda item: abs(item.estimate) if not math.isnan(item.estimate) else -1.0,
        reverse=True,
    )
    return {item.contrast_id: index + 1 for index, item in enumerate(primary)}
