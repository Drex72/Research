"""Language surfaces for an arbitrary number of languages.

The compatibility path could only express three surfaces (EN, KO, CS) and
validated a code-switched form by counting Hangul characters against Latin
characters. That test cannot separate two Latin-script languages, so it fails
the moment Yoruba or Spanish is added.

This module replaces the character-class heuristic with a per-language
*detector*: a script range, a diacritic set, a marker lexicon, or any
combination. A language counts as present in a piece of text when its
detectors fire at least ``min_hits`` times. A surface then declares which
languages must be present, and a code-switched surface additionally requires
that no single language dominates.

Adding a language means adding an entry to ``languages/_detectors.json`` and a
surface file. It never means editing this module.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SURFACE_KINDS = ("source", "monolingual", "code_switched")
APPLICATION_POINTS = ("user_request", "handoff", "system_prompt", "tool_description")
REVIEW_STATES = ("source", "review-required", "in-review", "reviewed")

# Tokens that must survive every transformation. Identifiers, amounts and the
# requested operation are the facts an outcome oracle reads; if a translation
# drops them the case is no longer the same case.
DEFAULT_PROTECTED = re.compile(
    r"\b(?:[A-Z][A-Z0-9]*-[A-Z0-9-]{2,}|\d[\d,._]*\d|\d)\b"
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


class SurfaceError(ValueError):
    """Raised when a surface definition or a surface text is invalid."""


# --------------------------------------------------------------------------
# detectors
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageDetector:
    """How to recognise one language in a piece of text.

    ``scripts``   inclusive ``(start, end)`` codepoint ranges.
    ``chars``     individual characters that are diagnostic on their own,
                  typically diacritics that other configured languages lack.
    ``markers``   lowercase word forms matched whole-word, accent-sensitive.
    ``resource_tier`` free-form label used only for reporting and grouping.
    """

    language: str
    scripts: tuple[tuple[int, int], ...] = ()
    chars: frozenset[str] = frozenset()
    markers: frozenset[str] = frozenset()
    resource_tier: str = "unspecified"

    def matches_token(self, token: str) -> str | None:
        """Attribute a single token to this language, or not.

        Returned as a precision label so the caller can prefer strong evidence
        over weak: a Hangul token is unambiguous, a shared Latin function word
        is not.
        """
        if self.scripts:
            for character in token:
                point = ord(character)
                if any(low <= point <= high for low, high in self.scripts):
                    return "script"
        if self.chars and any(character.lower() in self.chars for character in token):
            return "diacritic"
        if self.markers and token.lower() in self.markers:
            return "marker"
        return None

    def hits(self, text: str) -> int:
        """Tokens in ``text`` this language claims.

        Counted in tokens, not characters. A script-based language counted per
        character and a marker-based language counted per word cannot be
        compared, and dominance is a comparison.
        """
        return sum(1 for match in _WORD.finditer(text) if self.matches_token(match.group(0)))


@dataclass(frozen=True)
class DetectorSet:
    """All configured language detectors, keyed by language name."""

    detectors: Mapping[str, LanguageDetector]
    path: Path | None = None

    def require(self, language: str) -> LanguageDetector:
        detector = self.detectors.get(language)
        if detector is None:
            known = ", ".join(sorted(self.detectors)) or "none"
            raise SurfaceError(
                f"no detector configured for language {language!r}; configured: {known}"
            )
        return detector

    def profile(self, text: str, languages: Sequence[str]) -> dict[str, int]:
        """Tokens attributed to each language, in declaration order.

        Each token goes to at most one language. Strong evidence wins: a token
        carrying a distinctive script or diacritic is attributed before one
        that merely appears in a marker list, so a word both languages share
        does not get double counted.
        """
        detectors = [(name, self.require(name)) for name in languages]
        counts = {name: 0 for name in languages}
        for match in _WORD.finditer(text):
            token = match.group(0)
            claim: tuple[str, int] | None = None
            for name, detector in detectors:
                label = detector.matches_token(token)
                if label is None:
                    continue
                rank = {"script": 0, "diacritic": 1, "marker": 2}[label]
                if claim is None or rank < claim[1]:
                    claim = (name, rank)
            if claim is not None:
                counts[claim[0]] += 1
        return counts

    def unattributed(self, text: str, languages: Sequence[str]) -> int:
        """Tokens no configured language claimed."""
        total = sum(1 for _ in _WORD.finditer(text))
        return total - sum(self.profile(text, languages).values())

    def tier(self, language: str) -> str:
        return self.require(language).resource_tier


def _ranges(raw: Any, label: str) -> tuple[tuple[int, int], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SurfaceError(f"{label} must be a list of [start, end] hex strings")
    ranges: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise SurfaceError(f"{label} entries must be [start, end] pairs")
        try:
            low, high = (int(str(value), 16) for value in item)
        except ValueError as exc:
            raise SurfaceError(f"{label} entries must be hex codepoints") from exc
        if low > high:
            raise SurfaceError(f"{label} range is inverted: {item}")
        ranges.append((low, high))
    return tuple(ranges)


def load_detectors(path: Path) -> DetectorSet:
    """Read ``languages/_detectors.json``."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise SurfaceError("detector file requires schema_version 1")
    entries = raw.get("languages")
    if not isinstance(entries, dict) or not entries:
        raise SurfaceError("detector file must define a non-empty languages object")
    detectors: dict[str, LanguageDetector] = {}
    for language, spec in entries.items():
        if not isinstance(spec, dict):
            raise SurfaceError(f"detector for {language} must be an object")
        chars = spec.get("chars", "")
        if not isinstance(chars, str):
            raise SurfaceError(f"detector chars for {language} must be a string")
        markers = spec.get("markers", [])
        if not isinstance(markers, list) or any(
            not isinstance(item, str) or not item for item in markers
        ):
            raise SurfaceError(f"detector markers for {language} must be non-empty strings")
        detector = LanguageDetector(
            language=language,
            scripts=_ranges(spec.get("scripts"), f"detector scripts for {language}"),
            chars=frozenset(character.lower() for character in chars),
            markers=frozenset(marker.lower() for marker in markers),
            resource_tier=str(spec.get("resource_tier", "unspecified")),
        )
        if not (detector.scripts or detector.chars or detector.markers):
            raise SurfaceError(f"detector for {language} defines no evidence")
        detectors[language] = detector
    return DetectorSet(detectors=detectors, path=Path(path))


# --------------------------------------------------------------------------
# surfaces
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SurfaceSpec:
    """One version of a request: a language, a mixture, or the source text."""

    surface_id: str
    kind: str
    languages: tuple[str, ...]
    application_point: str
    construction: str
    review_status: str
    preserve: tuple[str, ...]
    min_hits: int
    max_dominance: float
    path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_source(self) -> bool:
        return self.kind == "source"

    @property
    def is_mixed(self) -> bool:
        return self.kind == "code_switched"

    @property
    def reviewed(self) -> bool:
        """Source text needs no review; anything constructed does."""
        return self.kind == "source" or self.review_status == "reviewed"


def _surface_from_raw(raw: Mapping[str, Any], path: Path | None) -> SurfaceSpec:
    version = raw.get("schema_version")
    if version not in (1, 2):
        raise SurfaceError("language surface requires schema_version 1 or 2")
    surface_id = str(raw.get("surface_id") or "").strip()
    if not surface_id:
        raise SurfaceError("language surface requires a surface_id")
    kind = str(raw.get("type") or "")
    if kind not in SURFACE_KINDS:
        raise SurfaceError(f"unsupported surface type in {surface_id}: {kind}")
    languages = raw.get("languages")
    if not isinstance(languages, list) or not languages or any(
        not isinstance(item, str) or not item for item in languages
    ):
        raise SurfaceError(f"surface {surface_id} requires a non-empty languages list")
    if len(set(languages)) != len(languages):
        raise SurfaceError(f"surface {surface_id} lists a language twice")
    if kind == "code_switched" and len(languages) < 2:
        raise SurfaceError(f"code-switched surface {surface_id} needs at least two languages")
    if kind == "monolingual" and len(languages) != 1:
        raise SurfaceError(f"monolingual surface {surface_id} must declare one language")
    application = str(raw.get("application_point") or "user_request")
    if application not in APPLICATION_POINTS:
        raise SurfaceError(f"unsupported application_point in {surface_id}: {application}")
    review_status = str(raw.get("review_status") or "review-required")
    if review_status not in REVIEW_STATES:
        raise SurfaceError(f"unsupported review_status in {surface_id}: {review_status}")
    preserve = raw.get("preserve", [])
    if not isinstance(preserve, list) or any(not isinstance(item, str) for item in preserve):
        raise SurfaceError(f"surface {surface_id} preserve must be a list of strings")
    detection = raw.get("detection", {})
    if not isinstance(detection, dict):
        raise SurfaceError(f"surface {surface_id} detection must be an object")
    min_hits = detection.get("min_hits_per_language", 3)
    if not isinstance(min_hits, int) or isinstance(min_hits, bool) or min_hits < 1:
        raise SurfaceError(f"surface {surface_id} min_hits_per_language must be a positive integer")
    max_dominance = detection.get("max_dominance", 0.9)
    if not isinstance(max_dominance, (int, float)) or isinstance(max_dominance, bool):
        raise SurfaceError(f"surface {surface_id} max_dominance must be a number")
    if not 0.0 < float(max_dominance) <= 1.0:
        raise SurfaceError(f"surface {surface_id} max_dominance must be in (0, 1]")
    return SurfaceSpec(
        surface_id=surface_id,
        kind=kind,
        languages=tuple(languages),
        application_point=application,
        construction=str(raw.get("construction") or ""),
        review_status=review_status,
        preserve=tuple(preserve),
        min_hits=min_hits,
        max_dominance=float(max_dominance),
        path=path,
        metadata={
            key: value
            for key, value in raw.items()
            if key
            not in {
                "schema_version",
                "surface_id",
                "type",
                "languages",
                "application_point",
                "construction",
                "review_status",
                "preserve",
                "detection",
            }
        },
    )


def load_surface_specs(
    references: Mapping[str, Any], root: Path, detectors: DetectorSet | None = None
) -> dict[str, SurfaceSpec]:
    """Load ``{surface_id: path}`` into specs, checking key and id agree.

    When ``detectors`` is supplied every declared language must have one, so a
    typo in a language name fails at load rather than during a run.
    """
    if not isinstance(references, Mapping) or not references:
        raise SurfaceError("language_profiles must be a non-empty object")
    specs: dict[str, SurfaceSpec] = {}
    for surface_id, reference in references.items():
        if not isinstance(reference, str) or not reference:
            raise SurfaceError(f"language profile path for {surface_id} must be a string")
        path = (Path(root) / reference).resolve()
        try:
            path.relative_to(Path(root).resolve())
        except ValueError as exc:
            raise SurfaceError(f"language profile escapes the project: {reference}") from exc
        if not path.is_file():
            raise SurfaceError(f"missing language profile: {reference}")
        spec = _surface_from_raw(json.loads(path.read_text(encoding="utf-8")), path)
        if spec.surface_id != surface_id:
            raise SurfaceError(
                f"language profile key and surface_id differ: {surface_id} != {spec.surface_id}"
            )
        if detectors is not None:
            for language in spec.languages:
                detectors.require(language)
        specs[surface_id] = spec
    sources = [spec.surface_id for spec in specs.values() if spec.is_source]
    if len(sources) != 1:
        raise SurfaceError(
            f"exactly one source surface is required, found {len(sources)}: {sorted(sources)}"
        )
    return specs


def source_surface_id(specs: Mapping[str, SurfaceSpec]) -> str:
    for surface_id, spec in specs.items():
        if spec.is_source:
            return surface_id
    raise SurfaceError("no source surface configured")


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def protected_tokens(text: str, extra: Iterable[str] = ()) -> set[str]:
    """Identifiers, amounts and any explicitly listed literals."""
    tokens = set(DEFAULT_PROTECTED.findall(text))
    tokens.update(item for item in extra if item)
    return tokens


def _normalise_number(token: str) -> str:
    return token.replace(",", "").replace("_", "").rstrip(".")


def validate_surface_text(
    spec: SurfaceSpec,
    text: str,
    detectors: DetectorSet,
    *,
    source_text: str | None = None,
    extra_protected: Iterable[str] = (),
) -> list[str]:
    """Return a list of problems with ``text`` as an instance of ``spec``.

    An empty list means the text is structurally acceptable. Structural
    acceptance is not meaning equivalence: only a bilingual reviewer can
    supply that, which is why ``SurfaceSpec.reviewed`` exists separately.
    """
    problems: list[str] = []
    text = unicodedata.normalize("NFC", text or "")
    if not text.strip():
        return [f"{spec.surface_id}: empty text"]

    if source_text is not None:
        expected = protected_tokens(unicodedata.normalize("NFC", source_text), extra_protected)
        present = protected_tokens(text, ())
        normalised_present = {_normalise_number(token) for token in present} | present
        missing = sorted(
            token
            for token in expected
            if token not in present and _normalise_number(token) not in normalised_present
        )
        if missing:
            problems.append(
                f"{spec.surface_id}: protected tokens dropped: {', '.join(missing[:6])}"
            )

    if spec.is_source:
        return problems

    profile = detectors.profile(text, spec.languages)
    for language, hits in profile.items():
        if hits < spec.min_hits:
            problems.append(
                f"{spec.surface_id}: too little {language} evidence "
                f"({hits} < {spec.min_hits})"
            )

    if spec.is_mixed:
        total = sum(profile.values())
        if total:
            dominant, count = max(profile.items(), key=lambda item: item[1])
            share = count / total
            if share > spec.max_dominance:
                problems.append(
                    f"{spec.surface_id}: {dominant} dominates the mixture "
                    f"({share:.0%} > {spec.max_dominance:.0%})"
                )
    return problems


def describe_languages(
    specs: Mapping[str, SurfaceSpec], detectors: DetectorSet
) -> list[dict[str, Any]]:
    """Provenance rows for the report: what each surface is and its review state."""
    rows: list[dict[str, Any]] = []
    for surface_id, spec in specs.items():
        rows.append(
            {
                "surface": surface_id,
                "kind": spec.kind,
                "languages": list(spec.languages),
                "resource_tiers": [detectors.tier(name) for name in spec.languages],
                "construction": spec.construction,
                "review_status": spec.review_status,
                "reviewed": spec.reviewed,
            }
        )
    return rows


def unreviewed_surfaces(specs: Mapping[str, SurfaceSpec]) -> list[str]:
    """Surfaces that a conclusion-bearing run must not use."""
    return sorted(
        surface_id for surface_id, spec in specs.items() if not spec.reviewed
    )
