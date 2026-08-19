"""Scenario-independent experiment matrix.

This package adds the pieces the compatibility runner never had:

``surfaces``   language-surface definitions for an arbitrary number of
               languages, with per-language detection so Latin-script
               languages can be told apart.
``corpus``     a scenario-independent case corpus built from the FinVault
               catalog, with synthesis variants clustered on their base case.
``contrasts``  declarative planned comparisons, replacing the three fixed
               analysis slots, with intervals that behave correctly when the
               event count is zero.
``outcomes``   the run-outcome vocabulary: how a unit terminated, whether the
               executor refused, and why a legitimate task failed.

Nothing here imports a specific scenario, surface id, or pipeline id.
"""

from __future__ import annotations

from .adapters import (
    AdapterFactory,
    AdapterResolutionError,
    SandboxAdapter,
    available_tools_for,
    scenario_of,
    terminal_tools_for,
)
from .contrasts import (
    Contrast,
    ContrastResult,
    ContrastSet,
    Decision,
    evaluate_contrasts,
    load_contrast_set,
    rule_of_three_upper,
)
from .corpus import CorpusBuilderError, CorpusRow, build_corpus, corpus_coverage
from .outcomes import (
    REFUSAL_TOOL,
    TerminationReason,
    UtilityFailure,
    classify_termination,
    is_refusal,
)
from .surfaces import (
    DetectorSet,
    SurfaceError,
    SurfaceSpec,
    describe_languages,
    load_detectors,
    load_surface_specs,
    validate_surface_text,
)

__all__ = [
    "AdapterFactory",
    "AdapterResolutionError",
    "Contrast",
    "ContrastResult",
    "ContrastSet",
    "CorpusBuilderError",
    "CorpusRow",
    "Decision",
    "DetectorSet",
    "REFUSAL_TOOL",
    "SandboxAdapter",
    "available_tools_for",
    "scenario_of",
    "terminal_tools_for",
    "SurfaceError",
    "SurfaceSpec",
    "TerminationReason",
    "UtilityFailure",
    "build_corpus",
    "classify_termination",
    "corpus_coverage",
    "describe_languages",
    "evaluate_contrasts",
    "is_refusal",
    "load_contrast_set",
    "load_detectors",
    "load_surface_specs",
    "rule_of_three_upper",
    "validate_surface_text",
]
