"""What a code-switched surface should look like.

A ``CodeSwitchSpec`` is the full description of one mixing condition: which
languages, in what order, in what proportion, at what unit size, and which
kinds of information sit in which language. It is data, declared in a language
profile, so a new condition is a new file rather than new code.

The five granularities follow the code-switching literature's unit hierarchy,
from largest switched unit to smallest, plus tag switching which is a distinct
phenomenon rather than a point on that scale.

``sentence``       each sentence is wholly in one language
``clause``         languages change between clauses inside a sentence
``phrase``         noun, verb and descriptive phrases take different languages
``word``           individual words alternate
``tag``            one matrix language throughout, with short tags borrowed
``semantic_role``  language is chosen by what the span *means*, not its size

Semantic-role allocation composes with the others: when roles are declared and
the granularity is not ``semantic_role``, the roles pin those spans and the
granularity governs everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

GRANULARITIES = ("sentence", "clause", "phrase", "word", "tag", "semantic_role")

# The information types a request can be decomposed into. Each may be assigned
# to any configured language. These are deliberately about meaning, not syntax:
# "the negation" and "the safety constraint" are the spans whose loss or
# mistranslation would change what the request actually asks for.
SEMANTIC_ROLES = (
    "background_context",
    "main_intent",
    "urgency",
    "negation",
    "safety_constraint",
    "requested_action",
    "tool_parameters",
)

# Categories of tag, for tag switching.
TAG_CATEGORIES = (
    "confirmation",
    "politeness",
    "discourse_marker",
    "question_tag",
    "emotional",
)


class CodeSwitchSpecError(ValueError):
    """Raised when a code-switching declaration is malformed."""


@dataclass(frozen=True)
class CodeSwitchSpec:
    """One mixing condition."""

    surface_id: str
    languages: tuple[str, ...]
    matrix_language: str
    granularity: str
    language_order: tuple[str, ...]
    dominance: Mapping[str, float]
    semantic_roles: Mapping[str, str]
    tag_categories: tuple[str, ...]
    generator: str = "llm"
    model_profile: str | None = None
    switch_rate: float | None = None
    preserve: tuple[str, ...] = ()
    notes: str = ""

    @property
    def embedded_languages(self) -> tuple[str, ...]:
        return tuple(name for name in self.languages if name != self.matrix_language)

    def dominance_for(self, language: str) -> float:
        return float(self.dominance.get(language, 0.0))

    def describe(self) -> str:
        """One line a human can check against the generated text."""
        order = " > ".join(self.language_order)
        shares = ", ".join(
            f"{name} {self.dominance_for(name):.0%}" for name in self.language_order
        )
        detail = f"{self.granularity} switching; order {order}; {shares}"
        if self.granularity == "tag" and self.tag_categories:
            detail += f"; tags: {', '.join(self.tag_categories)}"
        if self.semantic_roles:
            roles = ", ".join(f"{role}={lang}" for role, lang in self.semantic_roles.items())
            detail += f"; roles: {roles}"
        return detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "languages": list(self.languages),
            "matrix_language": self.matrix_language,
            "granularity": self.granularity,
            "language_order": list(self.language_order),
            "dominance": dict(self.dominance),
            "semantic_roles": dict(self.semantic_roles),
            "tag_categories": list(self.tag_categories),
            "generator": self.generator,
            "model_profile": self.model_profile,
            "switch_rate": self.switch_rate,
            "notes": self.notes,
        }


def _normalised_dominance(
    raw: Any, languages: Sequence[str], surface_id: str
) -> dict[str, float]:
    """Read declared shares, or spread evenly when none are given."""
    if raw is None:
        share = 1.0 / len(languages)
        return {name: share for name in languages}
    if not isinstance(raw, Mapping):
        raise CodeSwitchSpecError(f"{surface_id}: dominance must be an object")
    unknown = set(raw) - set(languages)
    if unknown:
        raise CodeSwitchSpecError(
            f"{surface_id}: dominance names languages not in the surface: {sorted(unknown)}"
        )
    values: dict[str, float] = {}
    for name in languages:
        value = raw.get(name, 0.0)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise CodeSwitchSpecError(f"{surface_id}: dominance for {name} must be a non-negative number")
        values[name] = float(value)
    total = sum(values.values())
    if total <= 0:
        raise CodeSwitchSpecError(f"{surface_id}: dominance values sum to zero")
    return {name: value / total for name, value in values.items()}


def load_code_switch_spec(
    surface_id: str, languages: Sequence[str], raw: Mapping[str, Any] | None
) -> CodeSwitchSpec | None:
    """Build a spec from a language profile's ``code_switching`` block."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise CodeSwitchSpecError(f"{surface_id}: code_switching must be an object")
    if len(languages) < 2:
        raise CodeSwitchSpecError(f"{surface_id}: code switching needs at least two languages")

    granularity = str(raw.get("granularity") or "clause")
    if granularity not in GRANULARITIES:
        raise CodeSwitchSpecError(
            f"{surface_id}: unsupported granularity {granularity!r}; "
            f"expected one of {', '.join(GRANULARITIES)}"
        )

    order = raw.get("language_order") or list(languages)
    if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
        raise CodeSwitchSpecError(f"{surface_id}: language_order must be a list of language names")
    if set(order) != set(languages):
        raise CodeSwitchSpecError(
            f"{surface_id}: language_order must contain exactly the surface languages"
        )

    matrix = raw.get("matrix_language") or order[0]
    if matrix not in languages:
        raise CodeSwitchSpecError(f"{surface_id}: matrix_language {matrix!r} is not in the surface")

    roles_raw = raw.get("semantic_roles") or {}
    if not isinstance(roles_raw, Mapping):
        raise CodeSwitchSpecError(f"{surface_id}: semantic_roles must be an object")
    roles: dict[str, str] = {}
    for role, language in roles_raw.items():
        if role not in SEMANTIC_ROLES:
            raise CodeSwitchSpecError(
                f"{surface_id}: unknown semantic role {role!r}; "
                f"expected one of {', '.join(SEMANTIC_ROLES)}"
            )
        if language not in languages:
            raise CodeSwitchSpecError(
                f"{surface_id}: semantic role {role} assigned to {language!r}, "
                "which is not a surface language"
            )
        roles[role] = str(language)
    if granularity == "semantic_role" and not roles:
        raise CodeSwitchSpecError(
            f"{surface_id}: semantic_role granularity requires a semantic_roles map"
        )

    tags = raw.get("tag_categories") or list(TAG_CATEGORIES)
    if not isinstance(tags, list) or any(item not in TAG_CATEGORIES for item in tags):
        raise CodeSwitchSpecError(
            f"{surface_id}: tag_categories must be drawn from {', '.join(TAG_CATEGORIES)}"
        )
    if granularity == "tag" and not tags:
        raise CodeSwitchSpecError(f"{surface_id}: tag granularity requires at least one tag category")

    switch_rate = raw.get("switch_rate")
    if switch_rate is not None:
        if not isinstance(switch_rate, (int, float)) or isinstance(switch_rate, bool):
            raise CodeSwitchSpecError(f"{surface_id}: switch_rate must be a number")
        if not 0.0 < float(switch_rate) <= 1.0:
            raise CodeSwitchSpecError(f"{surface_id}: switch_rate must be in (0, 1]")

    model_profile = raw.get("model_profile")
    if model_profile is not None and not isinstance(model_profile, str):
        raise CodeSwitchSpecError(f"{surface_id}: model_profile must be a path string")

    return CodeSwitchSpec(
        surface_id=surface_id,
        languages=tuple(languages),
        matrix_language=str(matrix),
        granularity=granularity,
        language_order=tuple(str(item) for item in order),
        dominance=_normalised_dominance(raw.get("dominance"), list(languages), surface_id),
        semantic_roles=roles,
        tag_categories=tuple(tags),
        generator=str(raw.get("generator") or "llm"),
        model_profile=model_profile,
        switch_rate=float(switch_rate) if switch_rate is not None else None,
        preserve=tuple(raw.get("preserve") or ()),
        notes=str(raw.get("notes") or ""),
    )


def expand_conditions(raw: Mapping[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    """Expand a factorial declaration into one language-profile body per cell.

    A study that wants every granularity crossed with every language order
    should not hand-write the files. This takes:

    ``{"languages": [...], "granularities": [...], "language_orders": [[...]],
       "dominance_profiles": {"balanced": {...}}}``

    and returns one profile body per combination, with a generated surface id.
    """
    languages = raw.get("languages")
    if not isinstance(languages, list) or len(languages) < 2:
        raise CodeSwitchSpecError("expansion requires at least two languages")
    granularities = raw.get("granularities") or ["clause"]
    orders = raw.get("language_orders") or [list(languages)]
    dominance_profiles = raw.get("dominance_profiles") or {"balanced": None}
    prefix = str(raw.get("surface_prefix") or "CS")
    base = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "languages",
            "granularities",
            "language_orders",
            "dominance_profiles",
            "surface_prefix",
        }
    }
    bodies: list[dict[str, Any]] = []
    for granularity in granularities:
        for order in orders:
            for profile_name, dominance in dominance_profiles.items():
                tag = "-".join(str(item)[:2].upper() for item in order)
                surface_id = f"{prefix}-{tag}-{granularity[:4].upper()}-{profile_name[:3].upper()}"
                body = {
                    "schema_version": 2,
                    "surface_id": surface_id,
                    "type": "code_switched",
                    "languages": list(languages),
                    "application_point": "user_request",
                    "construction": f"generated: {granularity} switching, order {'/'.join(order)}",
                    "review_status": "review-required",
                    "code_switching": {
                        **base,
                        "granularity": granularity,
                        "language_order": list(order),
                        **({"dominance": dominance} if dominance else {}),
                    },
                }
                bodies.append(body)
    return bodies


def write_expanded(bodies: Sequence[Mapping[str, Any]], directory: Path) -> list[Path]:
    """Write expanded profiles to disk, one file per surface."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for body in bodies:
        path = directory / f"{body['surface_id']}.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
