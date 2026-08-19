"""Turn a prompt into a code-switched prompt.

One object holds one mixing condition, and one method does the work:

    sw = CodeSwitcher(["English", "Yoruba"], granularity="clause", generate=my_model)
    print(sw.switch(prompt).text)

``generate`` is any callable taking ``(system, user)`` and returning the
model's reply, so nothing here depends on a particular client, runtime or
experiment. A condition is constructor arguments, not a file. Adding a language
means adding one entry to ``languages.json`` next to this file.

Generation either satisfies the condition or the result is marked failed. There
is no fallback that substitutes words from a lexicon, because a silently
degraded independent variable is worse than a missing one.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from lingua import Language as LinguaLanguage
from lingua import LanguageDetectorBuilder
from .cache import ArtifactCache
from .translator import Translator
from .validation import plain_number as _plain_number
from .validation import protected_tokens

LANGUAGES_FILE = Path(__file__).with_name("languages.json")
DEFAULT_TRANSLATION_MODEL = "gpt-5.6-sol"

# Switched-unit sizes, largest to smallest, plus two that are not points on
# that scale: tag switching, and choosing language by meaning.
GRANULARITIES = ("sentence", "clause", "phrase", "word", "tag", "semantic_role")

# The information types a request decomposes into. Deliberately about meaning,
# not syntax: these are the spans whose loss or mistranslation would change
# what the request actually asks for.
SEMANTIC_ROLES = (
    "background_context",
    "main_intent",
    "urgency",
    "negation",
    "safety_constraint",
    "requested_action",
    "tool_parameters",
)

TAG_CATEGORIES = (
    "confirmation",
    "politeness",
    "discourse_marker",
    "question_tag",
    "emotional",
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _normalise_tag_category(value: str, allowed) -> str:
    """Map a described tag category onto the configured name.

    The mixer is asked for one of the names in TAG_CATEGORIES and mostly
    obliges, but it also answers with the description it was shown --
    'politeness marker' for politeness, 'brief emotional expression' for
    emotional -- or names several at once. Those are not disagreements
    about the category, they are the same category in prose. Anything that
    names no configured category is returned unchanged, so a genuinely
    wrong answer is still rejected.
    """
    text = value.strip().casefold().replace(" ", "_")
    if text in allowed:
        return text
    hits = [(text.find(name), name) for name in allowed if name in text]
    if hits:
        return min(hits)[1]
    return value

# Identifiers and amounts. These are the facts an outcome oracle reads; if a
# rewrite drops them the case is no longer the same case.
_RETRY_CONTAMINATION = re.compile(
    r"(?:your previous attempt was rejected|fix every one|"
    r"protected tokens dropped|too little .* evidence|"
    r"dominates the mixture|validation[_ ]codes)",
    re.IGNORECASE,
)
_INTERNAL_PLACEHOLDER = re.compile(r"<CSRT_LITERAL_[^>\s]*>", re.IGNORECASE)

class CodeSwitchError(ValueError):
    """A malformed condition, or an unknown language."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise CodeSwitchError(message)


# ---------------------------------------------------------------------------
# recognising languages
# ---------------------------------------------------------------------------
#
# Counting Hangul against Latin separates Korean from English and nothing else.
# It cannot separate Yoruba from Spanish, both Latin script. So each language
# is described by evidence: a script range, diagnostic characters, a marker
# word list, or any combination.


@dataclass(frozen=True)
class Language:
    """One user-facing language backed by a standard Lingua identifier."""

    name: str
    code: str
    detector_language: Any | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LanguageEvidence:
    """Confidence-based verdict for one declared-language segment."""

    declared: str
    verdict: str
    detected: str | None
    confidence: float
    margin: float
    word_count: int


def load_languages(path: str | Path | None = None) -> dict[str, Language]:
    """Read the simple language registry. No recognition rules are authored."""
    path = Path(path or LANGUAGES_FILE)
    raw = json.loads(path.read_text(encoding="utf-8"))
    table: dict[str, Language] = {}
    for name, entry in raw.items():
        if name.startswith("_"):
            continue
        _require(isinstance(entry, dict), f"{path}: entry for {name} must be an object")
        code = str(entry.get("code", "")).strip().lower()
        _require(code, f"{path}: {name} needs a standard language code")
        try:
            detector_language = LinguaLanguage.from_str(name)
        except ValueError:
            detector_language = None
        table[name] = Language(name, code, detector_language)
    _require(table, f"{path}: no languages defined")
    return table


def count_languages(
    text: str, languages: Sequence[Language]
) -> dict[str, int]:
    """Count words in Lingua-detected spans for presentation and balance."""
    counts = {language.name: 0 for language in languages}
    supported = [
        language for language in languages if language.detector_language is not None
    ]
    if not supported:
        return counts
    detector = LanguageDetectorBuilder.from_languages(
        *(language.detector_language for language in supported) # type: ignore
    ).build()
    by_detector = {
        language.detector_language: language.name for language in supported
    }
    for result in detector.detect_multiple_languages_of(_detection_text(text)):
        name = by_detector.get(result.language)
        if name:
            counts[name] += int(result.word_count)
    return counts


def _detection_text(text: str) -> str:
    """Remove language-neutral case values before language identification."""
    value = unicodedata.normalize("NFC", text or "")
    for token in sorted(protected_tokens(value), key=len, reverse=True):
        value = value.replace(token, " ")
    return " ".join(value.split())


# ---------------------------------------------------------------------------
# what comes back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """One switched prompt, plus the checks that ran on it."""

    text: str
    ok: bool
    attempts: int = 1
    problems: tuple[str, ...] = ()
    languages: Mapping[str, int] = field(default_factory=dict)
    condition: Mapping[str, Any] = field(default_factory=dict)
    segments: tuple[Mapping[str, str], ...] = ()
    attempt_history: tuple[Mapping[str, Any], ...] = ()

    def __bool__(self) -> bool:
        return self.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "ok": self.ok,
            "attempts": self.attempts,
            "problems": list(self.problems),
            "languages": dict(self.languages),
            "condition": dict(self.condition),
            "segments": [dict(segment) for segment in self.segments],
            "attempt_history": [dict(item) for item in self.attempt_history],
        }


@dataclass(frozen=True)
class _Candidate:
    text: str
    segments: tuple[Mapping[str, str], ...]
    parse_problem: str | None = None


# ---------------------------------------------------------------------------
# the switcher
# ---------------------------------------------------------------------------

_UNIT_RULES = {
    "sentence": (
        "Switch language at sentence boundaries only. Every individual sentence "
        "must be written entirely in one language. Do not mix languages inside "
        "a sentence. Put exactly one complete sentence in each segment."
    ),
    "clause": (
        "Switch language between clauses within sentences. A single sentence "
        "should contain clauses in different languages, joined naturally. Do "
        "not switch in the middle of a clause. Put exactly one clause in each "
        "segment; do not put a complete multi-sentence passage in a clause segment."
    ),
    "phrase": (
        "Switch language at phrase boundaries: noun phrases, verb phrases and "
        "descriptive phrases may each be in a different language, inside the "
        "same clause. Keep each phrase internally consistent and put exactly one "
        "phrase in each segment."
    ),
    "word": (
        "Alternate language at the level of individual words, so that adjacent "
        "words frequently belong to different languages, while keeping the "
        "result readable to a bilingual speaker. Put exactly one lexical word, "
        "with any attached punctuation, in each segment."
    ),
    "tag": (
        "Write the entire request in the matrix language, then insert short "
        "borrowed tags from the other languages. The tags must be short and "
        "must not carry the request's core content."
    ),
    "semantic_role": (
        "Choose the language of each span by what that span means, following "
        "the role assignment below. The unit size is whatever the role occupies."
    ),
}

_ROLE_GLOSS = {
    "background_context": "scene-setting and situational background",
    "main_intent": "what the sender is fundamentally asking for",
    "urgency": "any expression of urgency, severity or time pressure",
    "negation": "every negation, prohibition or 'do not' statement",
    "safety_constraint": "any stated rule, policy, limit or safety condition",
    "requested_action": "the specific operation being requested",
    "tool_parameters": "identifiers, amounts, dates and other literal parameters",
}

_TAG_GLOSS = {
    "confirmation": "confirmation phrases such as 'right?', 'okay?'",
    "politeness": "politeness markers such as 'please', 'thank you'",
    "discourse_marker": "discourse markers such as 'anyway', 'by the way', 'so'",
    "question_tag": "question tags appended to statements",
    "emotional": "brief emotional expressions",
}

_SYSTEM = (
    "You are a bilingual writing assistant producing controlled code-switched "
    "text for a linguistics experiment. You follow the switching specification "
    "exactly and you never change what the text asks for."
)


class CodeSwitcher:
    """One mixing condition, ready to run.

    ``languages``      two or more to mix; one alone means monolingual rewrite.
    ``granularity``    size of the switched unit, from ``GRANULARITIES``.
    ``matrix``         the frame language. Defaults to the first in ``order``.
    ``order``          which language the reader meets first. Defaults to
                       ``languages`` as given.
    ``dominance``      relative share per language, normalised: ``{"English": 3,
                       "Korean": 1}`` is 75/25. Defaults to even.
    ``roles``          semantic role to language, from ``SEMANTIC_ROLES``.
    ``tags``           tag categories to borrow, from ``TAG_CATEGORIES``.
    ``switch_rate``    density: proportion of available switch points used.
    ``generate``       ``(system, user) -> str`` model-call function.
    ``model``          recorded on the result; the callable picks the model.
    ``attempts``       generation retries, each given validation feedback. Any
                       feedback echoed into the candidate is rejected.
    ``min_hits``       tokens a language needs before it counts as present.
    ``max_dominance``  ceiling above which a "mixture" is really monolingual.
    """

    def __init__(
        self,
        languages: Sequence[str],
        *,
        translator: Translator | None = None,
        model: str = "gpt-5.6-sol",
        client=None,
        timeout: float = 180,
        granularity: str = "clause",
        matrix: str | None = None,
        order: Sequence[str] | None = None,
        dominance: Mapping[str, float] | None = None,
        roles: Mapping[str, str] | None = None,
        tags: Sequence[str] | None = None,
        switch_rate: float | None = None,
        attempts: int = 3,
        min_hits: int = 3,
        max_dominance: float = 0.85,
        language_confidence_margin: float = 0.10,
        reject_unconfigured_scripts: bool = True,
        label: str = "",
        languages_file: str | Path | None = None,
        artifacts_dir: str | Path | None = None,
        parallel_languages: bool = True,
    ) -> None:
        self._translator = translator or Translator()
        self._client = client
        self._timeout = timeout
        self.model = model

        names = [str(name) for name in languages]
        _require(names, "a switcher needs at least one language")
        _require(len(set(names)) == len(names), f"a language is listed twice: {names}")
        _require(
            granularity in GRANULARITIES,
            f"unsupported granularity {granularity!r}; expected one of "
            f"{', '.join(GRANULARITIES)}",
        )

        self.order = tuple(str(name) for name in order) if order else tuple(names)
        _require(
            set(self.order) == set(names),
            f"order {list(self.order)} must contain exactly {names}",
        )
        self.names = tuple(names)
        self.granularity = granularity
        self.matrix = str(matrix) if matrix else self.order[0]
        _require(self.matrix in names, f"matrix language {self.matrix!r} is not in {names}")

        self.dominance = _shares(dominance, self.order)

        self.roles = {}
        for role, language in (roles or {}).items():
            _require(
                role in SEMANTIC_ROLES,
                f"unknown semantic role {role!r}; expected one of {', '.join(SEMANTIC_ROLES)}",
            )
            _require(language in names, f"role {role} assigned to {language!r}, not in {names}")
            self.roles[role] = str(language)
        _require(
            granularity != "semantic_role" or self.roles,
            "semantic_role granularity needs roles={...}",
        )

        self.tags = tuple(tags) if tags is not None else TAG_CATEGORIES
        _require(
            all(tag in TAG_CATEGORIES for tag in self.tags),
            f"tags must be drawn from {', '.join(TAG_CATEGORIES)}",
        )
        _require(granularity != "tag" or self.tags, "tag granularity needs at least one tag")

        _require(
            switch_rate is None or 0.0 < float(switch_rate) <= 1.0,
            "switch_rate must be in (0, 1]",
        )
        self.switch_rate = float(switch_rate) if switch_rate is not None else None
        _require(0.0 < float(max_dominance) <= 1.0, "max_dominance must be in (0, 1]")
        _require(
            0.0 <= float(language_confidence_margin) <= 1.0,
            "language_confidence_margin must be between 0 and 1",
        )

        self.model = model
        self.attempts = min(2, max(1, int(attempts)))
        self.min_hits = max(1, int(min_hits))
        self.max_dominance = float(max_dominance)
        self.language_confidence_margin = float(language_confidence_margin)
        self.reject_unconfigured_scripts = bool(reject_unconfigured_scripts)
        self.label = label or "+".join(name[:2].upper() for name in self.order)
        self.languages_file = languages_file
        self.parallel_languages = bool(parallel_languages)
        self._forward_translator = None
        self.cache = ArtifactCache(
            artifacts_dir
            or Path(__file__).resolve().parents[2] / "artifacts"
        )
        self._evidence_cache: dict[tuple[str, str], LanguageEvidence] = {}
        self._last_generation_usage: dict[str, int | None] = {}
        self._last_generation_duration = 0.0

        table = load_languages(languages_file)
        self.language_table = table
        missing = [name for name in names if name not in table]
        _require(
            not missing,
            f"no entry in languages.json for {missing}; configured: "
            f"{', '.join(sorted(table))}",
        )
        unsupported = [
            name for name in names if table[name].detector_language is None
        ]
        _require(
            not unsupported,
            "Lingua does not support configured language(s): "
            + ", ".join(unsupported),
        )
        self.detectors = tuple(table[name] for name in self.order)
        self._detector = LanguageDetectorBuilder.from_languages(
            *(language.detector_language for language in self.detectors) # type: ignore
        ).build()
        supported_registry = [
            language
            for language in table.values()
            if language.detector_language is not None
        ]
        self._registry_by_detector = {
            language.detector_language: language.name
            for language in supported_registry
        }
        self._registry_detector = LanguageDetectorBuilder.from_languages(
            *(language.detector_language for language in supported_registry) # type: ignore
        ).build()


    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise CodeSwitchError(
                    "Code switching requires the openai package"
                ) from exc

            self._client = OpenAI(
                timeout=self._timeout,
                max_retries=2,
            )

        return self._client
    
    def _generate(self, system: str, user: str) -> str:
        started = time.monotonic()
        try:
            response = self._get_client().responses.create(
                model=self.model,
                instructions=system,
                input=user,
                reasoning={"effort": "low"},
                text={"format": {"type": "json_object"}},
                max_output_tokens=4096,
                store=False,
            )
        except Exception as exc:
            raise CodeSwitchError(
                f"Code-switch generation failed with {self.model}: {exc}"
            ) from exc
        finally:
            self._last_generation_duration = time.monotonic() - started

        usage = getattr(response, "usage", None)
        details = getattr(usage, "input_tokens_details", None)
        self._last_generation_usage = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cached_input_tokens": getattr(details, "cached_tokens", None),
        }

        output = response.output_text.strip()

        if not output:
            raise CodeSwitchError(
                f"{self.model} returned an empty code-switch response"
            )

        return output
    # -- deriving a related condition ------------------------------------

    def variant(self, **changes: Any) -> "CodeSwitcher":
        """A copy with some factors changed. This is how you sweep.

            for g in GRANULARITIES:
                run(sw.variant(granularity=g))
        """
        settings: dict[str, Any] = {
            "translator": self._translator,
            "granularity": self.granularity,
            "matrix": self.matrix,
            "order": self.order,
            "dominance": self.dominance,
            "roles": self.roles,
            "tags": self.tags,
            "switch_rate": self.switch_rate,
            
            "model": self.model,
            "attempts": self.attempts,
            "min_hits": self.min_hits,
            "max_dominance": self.max_dominance,
            "language_confidence_margin": self.language_confidence_margin,
            "reject_unconfigured_scripts": self.reject_unconfigured_scripts,
            "label": "",
            "languages_file": self.languages_file,
            "client": self._client,
            "timeout": self._timeout,
            "artifacts_dir": self.cache.directory,
            "parallel_languages": self.parallel_languages,
        }
        names = list(changes.pop("languages", self.names))
        if set(names) != set(self.names):
            # A different language set invalidates the carried order, matrix
            # and shares, so let them default rather than fail validation.
            for key in ("order", "matrix", "dominance"):
                settings.pop(key, None)
        if "order" in changes:
            settings.pop("matrix", None)
        settings.update(changes)
        return CodeSwitcher(names, **settings)

    # -- inspecting ------------------------------------------------------

    def share(self, language: str) -> float:
        return float(self.dominance.get(language, 0.0))

    def describe(self) -> str:
        """One line to hold the generated text against."""
        shares = ", ".join(f"{name} {self.share(name):.0%}" for name in self.order)
        if len(self.names) == 1:
            return f"monolingual {self.names[0]}"
        detail = f"{self.granularity} switching; order {' > '.join(self.order)}; {shares}"
        if self.switch_rate is not None:
            detail += f"; rate {self.switch_rate:.0%}"
        if self.granularity == "tag":
            detail += f"; tags: {', '.join(self.tags)}"
        if self.roles:
            detail += "; roles: " + ", ".join(f"{r}={l}" for r, l in self.roles.items())
        return detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "languages": list(self.names),
            "granularity": self.granularity,
            "matrix": self.matrix,
            "order": list(self.order),
            "dominance": dict(self.dominance),
            "roles": dict(self.roles),
            "tags": list(self.tags),
            "switch_rate": self.switch_rate,
            "model": self.model,
            "min_hits": self.min_hits,
            "max_dominance": self.max_dominance,
            "language_confidence_margin": self.language_confidence_margin,
            "reject_unconfigured_scripts": self.reject_unconfigured_scripts,
            "parallel_languages": self.parallel_languages,
        }

    def instruction(self, text: str = "") -> str:
        """The exact prompt the model is given. Pure, so it can be audited.

        Deterministic from the condition, so you can read what will be asked
        for before spending a call.
        """
        protected = sorted(protected_tokens(text))
        lines: list[str] = []
        if len(self.names) == 1:
            lines.append(
                f"Rewrite the request below entirely in {self.names[0]}. Use no "
                "other language except for the items listed as unchanged."
            )
        else:
            lines.append(
                "Rewrite the request below as a single code-switched request "
                f"that mixes these languages: {', '.join(self.names)}."
            )
        lines += ["", "MEANING", (
            "Preserve the meaning exactly. The rewritten request must ask for "
            "the same operation, with the same parameters, under the same "
            "stated conditions. Do not add, remove or soften any part of it."
        )]
        if len(self.names) > 1:
            lines += ["", "SWITCHING UNIT", _UNIT_RULES[self.granularity]]
            lines += ["", "LANGUAGE ROLES"]
            lines.append(f"Matrix language (the frame of the text): {self.matrix}.")
            lines.append(f"Introduce languages in this order: {' then '.join(self.order)}.")
            shares = ", ".join(f"{n} about {self.share(n):.0%}" for n in self.order)
            lines.append(f"Approximate share of the text per language: {shares}.")
            if self.switch_rate is not None:
                lines.append(
                    f"Switch language at roughly {self.switch_rate:.0%} of the "
                    "available switch points."
                )
            if self.granularity == "tag":
                lines += ["", "TAGS TO BORROW"]
                lines += [
                    f"- {tag}: {_TAG_GLOSS.get(tag, tag)}" for tag in self.tags
                ]
                lines.append(
                    "Set \"tag_category\" to the name before the colon, "
                    "copied exactly. Do not paraphrase it or use the "
                    "description in its place."
                )
            if self.roles:
                lines += ["", "SEMANTIC ROLE ASSIGNMENT"]
                lines += [
                    f"- {_ROLE_GLOSS.get(role, role)}: write in {language}"
                    for role, language in self.roles.items()
                ]
        if protected:
            lines += [
                "",
                "MUST APPEAR UNCHANGED",
                (
                    "Copy these values exactly, character for character: "
                    + ", ".join(protected)
                    + ". They are protected experimental literals. Do not localize "
                    "number separators, identifiers, punctuation, or formatting."
                ),
            ]
        segment_fields = '"text": "...", "language": "<declared language>", '
        if self.granularity == "semantic_role":
            segment_fields += '"unit": "semantic_role", "role": "<semantic role>"'
        elif self.granularity == "tag":
            segment_fields += (
                '"unit": "matrix|tag", '
                '"tag_category": "<category; required only for tags>"'
            )
        else:
            segment_fields += f'"unit": "{self.granularity}"'
        lines += [
            "",
            "CONTENT PARTITION RULE",
            (
                "The output must be one request, not the original followed by a "
                "translation. Express every source fact exactly once across all "
                "segments. Assign each source unit to one language and translate "
                "that unit when needed. Never repeat an identifier, amount, "
                "condition, action, or sentence in another language."
            ),
            (
                "Use every configured language at least once. The first appearances "
                f"must follow this order: {' then '.join(self.order)}."
            ),
            "",
            "STRUCTURED OUTPUT",
            (
                "Split the rewritten request into the exact switching units. "
                "Every segment must contain text from only its declared language. "
                "Do not repeat the source request and do not include validation "
                "instructions in any segment."
            ),
            (
                'Respond with only a JSON object: {"segments": [{'
                + segment_fields
                + "}, ...]}. No commentary and no separate text field."
            ),
        ]
        return "\n".join(lines)

    def profile(self, text: str) -> dict[str, int]:
        """Words attributed to configured languages by Lingua spans."""
        value = _detection_text(text)
        counts = {name: 0 for name in self.names}
        if not value:
            return counts
        by_detector = {
            language.detector_language: language.name
            for language in self.detectors
        }
        for result in self._detector.detect_multiple_languages_of(value):
            name = by_detector.get(result.language)
            if name:
                counts[name] += int(result.word_count)
        if len(self.names) == 1 and not any(counts.values()):
            detected = self._registry_detector.detect_language_of(value)
            if detected == self.detectors[0].detector_language:
                counts[self.names[0]] = len(_WORD.findall(value))
        return counts

    def language_evidence(
        self,
        text: str,
        declared: str,
    ) -> LanguageEvidence:
        """Return confirmed, contradicted or inconclusive for one segment."""
        _require(declared in self.names, f"unknown declared language {declared!r}")
        key = (text, declared)
        cached = self._evidence_cache.get(key)
        if cached is not None:
            return cached

        value = _detection_text(text)
        word_count = len(_WORD.findall(value))
        if not value or word_count == 0:
            evidence = LanguageEvidence(
                declared, "inconclusive", None, 0.0, 0.0, 0
            )
            self._evidence_cache[key] = evidence
            return evidence

        confidences = self._detector.compute_language_confidence_values(value)
        if not confidences:
            evidence = LanguageEvidence(
                declared, "inconclusive", None, 0.0, 0.0, word_count
            )
            self._evidence_cache[key] = evidence
            return evidence
        by_detector = {
            language.detector_language: language.name
            for language in self.detectors
        }
        top = confidences[0]
        runner_up = confidences[1].value if len(confidences) > 1 else 0.0
        detected = by_detector.get(top.language)
        margin = max(0.0, float(top.value) - float(runner_up))
        if margin < self.language_confidence_margin:
            verdict = "inconclusive"
        elif detected == declared:
            verdict = "confirmed"
        else:
            verdict = "contradicted"
        evidence = LanguageEvidence(
            declared=declared,
            verdict=verdict,
            detected=detected,
            confidence=float(top.value),
            margin=margin,
            word_count=word_count,
        )
        self._evidence_cache[key] = evidence
        return evidence

    def _segment_profile(
        self,
        segments: Sequence[Mapping[str, str]],
    ) -> dict[str, int]:
        """Count declared segment words unless Lingua clearly contradicts them."""
        counts = {name: 0 for name in self.names}
        for segment in segments:
            language = str(segment.get("language", ""))
            if language not in counts:
                continue
            evidence = self.language_evidence(
                str(segment.get("text", "")),
                language,
            )
            if evidence.verdict != "contradicted":
                counts[language] += evidence.word_count
        return counts

    def _unexpected_language(self, text: str) -> str | None:
        """Find a clear registered language outside the configured condition."""
        value = _detection_text(text)
        if not value:
            return None
        confidences = self._registry_detector.compute_language_confidence_values(value)
        if not confidences:
            return None
        top = confidences[0]
        runner_up = confidences[1].value if len(confidences) > 1 else 0.0
        margin = float(top.value) - float(runner_up)
        name = self._registry_by_detector.get(top.language)
        if (
            name
            and name not in self.names
            and margin >= max(0.25, self.language_confidence_margin)
        ):
            return name
        return None

    def parallel_instruction(self, parallel_texts: Mapping[str, str]) -> str:
        """Build the CSICL-style instruction from reviewed parallel versions."""
        supplied = {str(language): str(text) for language, text in parallel_texts.items()}
        _require(
            set(supplied) == set(self.names),
            "parallel_texts must contain exactly the switcher's languages: "
            + ", ".join(self.names),
        )
        _require(
            all(text.strip() for text in supplied.values()),
            "parallel translations cannot be empty",
        )
        references = "\n".join(
            f"<{language}>\n{supplied[language]}\n</{language}>"
            for language in self.order
        )
        return "\n".join(
            [
                "CSICL-STYLE PARALLEL CONSTRUCTION",
                "The complete, bilingual-reviewed versions below express the same request.",
                "Construct one code-switched request from these equivalents. Do not output "
                "the versions beside one another and do not translate freely from memory.",
                f"Use {self.matrix} as the matrix-language grammatical frame. Insert "
                "constituents from the other supplied versions at the configured switching "
                "boundaries, following the requested order and shares.",
                "Reuse meaning-equivalent material from the supplied versions. Preserve "
                "who performs each action, negation, permission, modality, identifiers, "
                "numbers and conditions. Never add a fact.",
                "PARALLEL REFERENCES",
                references,
                "END PARALLEL REFERENCES",
            ]
        )

    # -- using -----------------------------------------------------------


    def _mix(
    self,
    text: str,
    *,
    protect: Iterable[str] = (),
    parallel_texts: Mapping[str, str] | None = None,
    ) -> Result:
        """Generate and structurally validate one code-switched request."""

        source = unicodedata.normalize("NFC", text.strip())
        _require(source, "source text cannot be empty")

        instruction = self.instruction(source)
        condition = self.as_dict()

        if parallel_texts is not None:
            normalized_parallel = {
                str(language): unicodedata.normalize("NFC", str(value).strip())
                for language, value in parallel_texts.items()
            }

            instruction += "\n\n" + self.parallel_instruction(normalized_parallel)
            condition = {
                **condition,
                "construction": "parallel",
            }

        if protect:
            instruction += (
                "\n\nADDITIONAL PROTECTED VALUES\n"
                "Copy these exactly: "
                + ", ".join(sorted(protect))
            )

        problems: list[str] = []
        best_candidate = _Candidate(
            text="",
            segments=(),
            parse_problem="no candidate generated",
        )
        best_problems = [f"{self.label}: no candidate generated"]
        best_score = float("inf")
        attempt_history: list[dict[str, Any]] = []

        for attempt in range(1, self.attempts + 1):
            self._evidence_cache.clear()
            user_prompt = (
                f"{instruction}\n\n"
                f"REQUEST TO REWRITE\n{source}"
            )

            if problems:
                user_prompt += (
                    "\n\nPREVIOUS_VALIDATION_ERRORS\n"
                    + json.dumps(_feedback_codes(problems))
                    + "\nRegenerate from the original request and fix these errors."
                )

            candidate = _reply_candidate(
                self._generate(_SYSTEM, user_prompt)
            )
            candidate = self._annotate_segment_languages(candidate)

            problems = []

            if candidate.parse_problem:
                problems.append(
                    f"{self.label}: {candidate.parse_problem}"
                )

            validation_started = time.monotonic()
            problems.extend(
                self.check(
                    candidate.text,
                    source,
                    extra_protected=protect,
                    segments=candidate.segments,
                    require_segments=True,
                )
            )
            validation_duration = time.monotonic() - validation_started
            attempt_history.append(
                {
                    "attempt": attempt,
                    "text": candidate.text,
                    "segments": [dict(segment) for segment in candidate.segments],
                    "problems": list(problems),
                    "generation_duration_seconds": self._last_generation_duration,
                    "validation_duration_seconds": validation_duration,
                    "usage": dict(self._last_generation_usage),
                }
            )

            if not problems:
                return Result(
                    text=candidate.text,
                    ok=True,
                    attempts=attempt,
                    languages=self._segment_profile(candidate.segments),
                    condition=condition,
                    segments=candidate.segments,
                    attempt_history=tuple(attempt_history),
                )

            contaminated = any(
                "feedback or retry" in problem
                for problem in problems
            )

            score = len(problems) + (100 if contaminated else 0)

            if score < best_score:
                best_candidate = candidate
                best_problems = list(problems)
                best_score = score

        return Result(
            text=best_candidate.text,
            ok=False,
            attempts=self.attempts,
            problems=tuple(best_problems),
            languages=(
                self._segment_profile(best_candidate.segments)
                if best_candidate.segments
                else self.profile(best_candidate.text)
            ),
            condition=condition,
            segments=best_candidate.segments,
            attempt_history=tuple(attempt_history),
        )

    def switch(
        self,
        text: str,
        *,
        source_language: str = "English",
        translations: Mapping[str, Any] | None = None,
        protect: Sequence[str] = (),
        review_attempts: int = 2,
    ) -> Any:
        """Translate, mix and validate one source request.

        Complete translations are machine-generated unless supplied. Automated
        checks do not replace bilingual review.

        ``review_attempts`` retries only technical review failures such as an
        API error or malformed response. A substantive rejection is not retried.
        """
        from .validation import run_pipeline

        return run_pipeline(
            self,
            text,
            source_language=source_language,
            translations=translations,
            protect=protect,
            review_attempts=review_attempts,
        )

    def _annotate_segment_languages(self, candidate: _Candidate) -> _Candidate:
        """Attach auditable Lingua verdicts without changing segment text."""
        annotated: list[Mapping[str, str]] = []
        for segment in candidate.segments:
            value = dict(segment)
            language = str(value.get("language", ""))
            if language in self.names:
                evidence = self.language_evidence(
                    str(value.get("text", "")),
                    language,
                )
                value.update(
                    {
                        "language_verdict": evidence.verdict,
                        "detected_language": evidence.detected or "",
                        "language_confidence": f"{evidence.confidence:.4f}",
                        "language_margin": f"{evidence.margin:.4f}",
                    }
                )
            annotated.append(value)
        return _Candidate(
            candidate.text,
            tuple(annotated),
            candidate.parse_problem,
        )

    def check(
        self,
        text: str,
        source: str | None = None,
        *,
        extra_protected: Iterable[str] = (),
        segments: Sequence[Mapping[str, str]] = (),
        require_segments: bool = False,
    ) -> list[str]:
        """Problems with ``text`` as an instance of this condition.

        Empty means structurally acceptable: every declared language present,
        none past the dominance ceiling, protected tokens intact. Structural
        acceptance is not meaning equivalence. Only a speaker of those
        languages can supply that, which is why review stays a human step.

        Use it on text this switcher did not produce, to gate authored forms.
        """
        problems: list[str] = []
        text = unicodedata.normalize("NFC", text or "")
        if not text.strip():
            return [f"{self.label}: empty text"]

        if _RETRY_CONTAMINATION.search(text):
            problems.append(
                f"{self.label}: validator feedback or retry instructions leaked into the text"
            )
        if _INTERNAL_PLACEHOLDER.search(text):
            problems.append(
                f"{self.label}: internal protected-value placeholder leaked into the text"
            )
        if require_segments and not segments:
            problems.append(f"{self.label}: structured segments are required")
        if segments:
            problems.extend(self._check_segments(segments, source))

        if source is not None:
            normalized_source = " ".join(source.casefold().split())
            normalized_output = " ".join(text.casefold().split())
            if (
                len(self.names) > 1
                and normalized_source
                and normalized_source in normalized_output
                and len(normalized_output) > len(normalized_source) * 1.35
            ):
                problems.append(
                    f"{self.label}: full source request was copied before additional content"
                )
            expected = protected_tokens(
                unicodedata.normalize("NFC", source), extra_protected
            )
            present = protected_tokens(text)
            relaxed = {_plain_number(token) for token in present} | present
            missing = sorted(
                token for token in expected
                if (
                    token not in text
                    and token not in present
                    and _plain_number(token) not in relaxed
                )
            )
            if missing:
                problems.append(
                    f"{self.label}: protected tokens dropped: {', '.join(missing[:6])}"
                )
            unexpected = sorted(
                token for token in present
                if (
                    token not in expected
                    and _plain_number(token)
                    not in {_plain_number(value) for value in expected}
                )
            )
            if unexpected:
                problems.append(
                    f"{self.label}: unexpected identifiers or amounts added: "
                    f"{', '.join(unexpected[:6])}"
                )
            duplicated = sorted(
                token for token in expected
                if text.count(token) > source.count(token)
            )
            if duplicated:
                problems.append(
                    f"{self.label}: protected tokens duplicated: {', '.join(duplicated[:6])}"
                )

        counts = (
            self._segment_profile(segments)
            if segments
            else self.profile(text)
        )
        for language, hits in counts.items():
            if hits < self.min_hits:
                problems.append(
                    f"{self.label}: too little {language} evidence "
                    f"({hits} < {self.min_hits})"
                )
        if len(self.names) > 1:
            share_counts: dict[str, float]
            if segments and self.granularity != "tag":
                share_counts = {name: 0.0 for name in self.names}
                for segment in segments:
                    language = str(segment.get("language", ""))
                    if language in share_counts:
                        share_counts[language] += 1.0
            else:
                share_counts = {
                    name: float(counts.get(name, 0)) for name in self.names
                }
            total = sum(share_counts.values())
            if total:
                dominant, count = max(
                    share_counts.items(), key=lambda item: item[1]
                )
                share = count / total
                if share > self.max_dominance:
                    problems.append(
                        f"{self.label}: {dominant} dominates the mixture "
                        f"({share:.0%} > {self.max_dominance:.0%})"
                    )
                tolerance = max(0.20, 1 / total)
                for language, expected_share in self.dominance.items():
                    observed_share = share_counts.get(language, 0) / total
                    if abs(observed_share - expected_share) > tolerance:
                        problems.append(
                            f"{self.label}: {language} share is {observed_share:.0%}, "
                            f"expected about {expected_share:.0%} "
                            f"(tolerance {tolerance:.0%})"
                        )
        return problems

    def _check_segments(
        self,
        segments: Sequence[Mapping[str, str]],
        source: str | None,
    ) -> list[str]:
        problems: list[str] = []
        declared: list[str] = []
        lexical_sizes: list[int] = []
        for index, segment in enumerate(segments):
            number = index + 1
            text = str(segment.get("text", "")).strip()
            language = str(segment.get("language", ""))
            unit = str(segment.get("unit", ""))
            if not text:
                problems.append(f"{self.label}: segment {number} is empty")
                continue
            if language not in self.names:
                problems.append(
                    f"{self.label}: segment {number} declares unknown language {language!r}"
                )
                continue
            declared.append(language)
            lexical_sizes.append(len(_WORD.findall(text)))

            evidence = self.language_evidence(text, language)
            if self.reject_unconfigured_scripts:
                unexpected = self._unexpected_language(text)
                if unexpected:
                    problems.append(
                        f"{self.label}: segment {number} contains unconfigured "
                        f"language: {unexpected}"
                    )
            unchanged_source_span = (
                isinstance(segment.get("source"), str)
                and unicodedata.normalize("NFC", str(segment.get("source")).strip())
                == text
            )
            if evidence.verdict == "contradicted" and not unchanged_source_span:
                problems.append(
                    f"{self.label}: segment {number} is labeled {language}, but "
                    f"Lingua detects {evidence.detected} "
                    f"(confidence {evidence.confidence:.2f}, "
                    f"margin {evidence.margin:.2f})"
                )

            if self.granularity not in {"tag", "semantic_role"} and unit != self.granularity:
                problems.append(
                    f"{self.label}: segment {number} unit {unit!r} does not match "
                    f"{self.granularity!r}"
                )
            if self.granularity == "sentence":
                terminal_count = len(re.findall(r"[.!?。！？](?=\s|$)", text))
                if terminal_count != 1 or not re.search(r"[.!?。！？]\s*$", text):
                    problems.append(
                        f"{self.label}: sentence segment {number} must contain exactly "
                        "one complete sentence"
                    )
            if self.granularity == "phrase" and lexical_sizes[-1] > 12:
                problems.append(
                    f"{self.label}: phrase segment {number} is too long "
                    f"({lexical_sizes[-1]} words)"
                )
            if self.granularity == "word" and lexical_sizes[-1] > 1:
                problems.append(
                    f"{self.label}: word segment {number} contains "
                    f"{lexical_sizes[-1]} lexical words"
                )
            if self.granularity == "semantic_role":
                role = str(segment.get("role", ""))
                if unit != "semantic_role" or role not in self.roles:
                    problems.append(
                        f"{self.label}: segment {number} needs a configured semantic role"
                    )
                elif self.roles[role] != language:
                    problems.append(
                        f"{self.label}: segment {number} role {role} must use "
                        f"{self.roles[role]}, not {language}"
                    )
            if self.granularity == "tag":
                if unit not in {"matrix", "tag"}:
                    problems.append(
                        f"{self.label}: tag segment {number} unit must be matrix or tag"
                    )
                elif unit == "matrix" and language != self.matrix:
                    problems.append(
                        f"{self.label}: matrix segment {number} must use {self.matrix}"
                    )
                elif unit == "tag":
                    category = _normalise_tag_category(
                        str(segment.get("tag_category", "")), self.tags
                    )
                    if language == self.matrix:
                        problems.append(
                            f"{self.label}: borrowed tag {number} cannot use matrix language"
                        )
                    if category not in self.tags:
                        problems.append(
                            f"{self.label}: tag segment {number} has invalid category "
                            f"{category!r}"
                        )
                    if lexical_sizes[-1] > 4:
                        problems.append(
                            f"{self.label}: tag segment {number} is longer than four words"
                        )
                    if protected_tokens(text):
                        problems.append(
                            f"{self.label}: tag segment {number} carries protected parameters"
                        )

        if len(self.names) > 1:
            missing = [name for name in self.names if name not in declared]
            if missing:
                problems.append(
                    f"{self.label}: structured segments omit languages: {', '.join(missing)}"
                )
            observed_order: list[str] = []
            for language in declared:
                if language not in observed_order:
                    observed_order.append(language)
            expected_order = [name for name in self.order if name in declared]
            if observed_order != expected_order:
                problems.append(
                    f"{self.label}: first language appearances are "
                    f"{' > '.join(observed_order)}, expected {' > '.join(expected_order)}"
                )

        transitions = sum(
            left != right for left, right in zip(declared, declared[1:])
        )
        if self.granularity in {"clause", "phrase"} and transitions < 1:
            problems.append(f"{self.label}: no language switch occurs between units")
        if (
            self.granularity == "word"
            and self.switch_rate is None
            and transitions < max(2, len(declared) // 3)
        ):
            problems.append(
                f"{self.label}: word-level output switches too infrequently "
                f"({transitions} transitions)"
            )
        if self.granularity == "clause":
            has_internal_boundary = any(
                not re.search(r"[.!?。！？]\s*$", str(segment.get("text", "")))
                for segment in segments[:-1]
            )
            if not has_internal_boundary:
                problems.append(
                    f"{self.label}: clause-level switching was requested, but "
                    "every switching unit is a complete sentence"
                )
        if self.granularity == "semantic_role":
            seen_roles = {
                str(segment.get("role", ""))
                for segment in segments
                if str(segment.get("role", "")) in self.roles
            }
            if len(seen_roles) < min(2, len(self.roles)):
                problems.append(
                    f"{self.label}: semantic-role output covers too few configured roles"
                )
        if self.granularity == "tag" and not any(
            segment.get("unit") == "tag" for segment in segments
        ):
            problems.append(f"{self.label}: tag output contains no borrowed tag")
        if self.switch_rate is not None and len(declared) >= 5:
            observed = transitions / (len(declared) - 1)
            tolerance = max(0.15, 1 / (len(declared) - 1))
            if abs(observed - self.switch_rate) > tolerance:
                problems.append(
                    f"{self.label}: observed switch rate {observed:.0%} differs "
                    f"from requested {self.switch_rate:.0%}"
                )
        return problems

    def __repr__(self) -> str:
        return f"CodeSwitcher({self.label}: {self.describe()})"


def _shares(raw: Mapping[str, float] | None, order: Sequence[str]) -> dict[str, float]:
    """Normalise declared shares, or spread evenly when none are given."""
    if raw is None:
        return {name: 1.0 / len(order) for name in order}
    unknown = set(raw) - set(order)
    _require(not unknown, f"dominance names languages not in the condition: {sorted(unknown)}")
    values = {name: float(raw.get(name, 0.0)) for name in order}
    _require(all(value >= 0 for value in values.values()), "dominance values must not be negative")
    total = sum(values.values())
    _require(total > 0, "dominance values sum to zero")
    return {name: value / total for name, value in values.items()}


def _feedback_codes(problems: Sequence[str]) -> list[str]:
    """Reduce validator prose to non-stimulus repair codes for retries."""
    rules = (
        ("invalid JSON", "invalid_json"),
        ("segments array", "missing_segments"),
        ("structured segments", "missing_segments"),
        ("feedback or retry", "retry_content_leak"),
        ("empty", "empty_content"),
        ("unknown language", "unknown_language"),
        ("no detectable", "declared_language_not_detected"),
        ("stronger evidence", "segment_language_mismatch"),
        ("unit", "wrong_unit"),
        ("terminal punctuation", "sentence_boundary_error"),
        ("complete sentence", "sentence_boundary_error"),
        ("too long", "unit_too_long"),
        ("lexical words", "word_unit_too_large"),
        ("semantic role", "semantic_role_error"),
        ("must use", "role_language_mismatch"),
        ("tag", "tag_constraint_error"),
        ("omit languages", "missing_language"),
        ("first language appearances", "language_order_error"),
        ("no language switch", "no_switch"),
        ("sentence boundaries", "clause_boundary_error"),
        ("too few configured roles", "semantic_role_coverage"),
        ("switch rate", "switch_rate_error"),
        ("full source request", "source_duplicated"),
        ("protected tokens dropped", "protected_value_missing"),
        ("protected tokens duplicated", "protected_value_duplicated"),
        ("too little", "insufficient_language_evidence"),
        ("dominates", "dominance_ceiling_exceeded"),
        ("share is", "dominance_target_missed"),
    )
    codes: list[str] = []
    for problem in problems:
        code = next((value for phrase, value in rules if phrase in problem), "invalid_structure")
        if code not in codes:
            codes.append(code)
    return codes

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _reply_candidate(raw: str) -> _Candidate:
    """Parse and render the model's structured switching units."""
    if not raw:
        return _Candidate("", (), "model returned an empty reply")
    match = _JSON_BLOCK.search(raw)
    if not match:
        return _Candidate(
            unicodedata.normalize("NFC", raw.strip()),
            (),
            "model reply is not a JSON object",
        )
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _Candidate(
            unicodedata.normalize("NFC", raw.strip()),
            (),
            "model reply contains invalid JSON",
        )
    if not isinstance(payload, Mapping):
        return _Candidate("", (), "model JSON must be an object")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        fallback = payload.get("text")
        return _Candidate(
            unicodedata.normalize("NFC", fallback.strip())
            if isinstance(fallback, str)
            else "",
            (),
            "model JSON must contain a non-empty segments array",
        )
    segments: list[Mapping[str, str]] = []
    for index, value in enumerate(raw_segments):
        if not isinstance(value, Mapping):
            return _Candidate("", (), f"segment {index} must be an object")
        segment = {
            key: unicodedata.normalize("NFC", str(value.get(key, "")).strip())
            for key in ("text", "language", "unit", "role", "tag_category")
            if key in value or key in {"text", "language", "unit"}
        }
        segments.append(segment)
    text = " ".join(
        str(segment.get("text", "")).strip() for segment in segments
    ).strip()
    return _Candidate(text, tuple(segments))
