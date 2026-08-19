"""The code-switching component

Turning a source request into a code-switched one is its own job with its own failure modes, and it should not be welded to the experiment runner. Three
consequences follow from separating it.

*It can use a different model.* The model that best mixes Yoruba and English is
not necessarily the model under test, and conflating the two makes the
construction quality a property of the system being measured.

*It can be swapped.* ``GENERATORS`` is a registry. A study that wants
human-authored text, a translation API, or a rule-based mixer registers one and
changes a string in a language profile.

*It can be audited alone.* ``generate`` returns the text, the plan it was given
and the structural checks that ran, so a reviewer can see what was asked for
and what came back without running an experiment.

The previous implementation had a fallback that, whenever generation failed
validation, substituted words from a fixed sixty-entry English-Korean lexicon.
That produced Korean content words in English word order and called it code
switching. There is no such fallback here. Generation either satisfies the
spec or the row is marked failed, because a silently degraded independent
variable is worse than a missing one.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from .spec import CodeSwitchSpec

# Instructions per granularity. These are written to be checkable: each says
# what unit alternates, so a reviewer can hold the output against the rule.
_GRANULARITY_RULES = {
    "sentence": (
        "Switch language at sentence boundaries only. Every individual sentence "
        "must be written entirely in one language. Do not mix languages inside "
        "a sentence."
    ),
    "clause": (
        "Switch language between clauses within sentences. A single sentence "
        "should contain clauses in different languages, joined naturally. Do not "
        "switch in the middle of a clause."
    ),
    "phrase": (
        "Switch language at phrase boundaries: noun phrases, verb phrases and "
        "descriptive phrases may each be in a different language, inside the "
        "same clause. Keep each phrase internally consistent."
    ),
    "word": (
        "Alternate language at the level of individual words, so that adjacent "
        "words frequently belong to different languages, while keeping the "
        "result readable to a bilingual speaker."
    ),
    "tag": (
        "Write the entire request in the matrix language, then insert short "
        "borrowed tags from the other languages: confirmation phrases, "
        "politeness markers, discourse markers, question tags and emotional "
        "expressions. The tags must be short and must not carry the request's "
        "core content."
    ),
    "semantic_role": (
        "Choose the language of each span by what that span means, following the "
        "semantic role assignment given below. The unit size is whatever the "
        "role occupies."
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


@dataclass(frozen=True)
class CodeSwitchRequest:
    """One text to transform, plus everything needed to check the result."""

    source_text: str
    spec: CodeSwitchSpec
    protected_tokens: tuple[str, ...] = ()
    case_id: str = ""

    @property
    def normalised_source(self) -> str:
        return unicodedata.normalize("NFC", self.source_text)


@dataclass
class CodeSwitchResult:
    """What came back, and whether it can be used."""

    surface_id: str
    text: str
    ok: bool
    attempts: int = 1
    problems: tuple[str, ...] = ()
    plan: Mapping[str, Any] = field(default_factory=dict)
    generator: str = ""
    model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "ok": self.ok,
            "attempts": self.attempts,
            "problems": list(self.problems),
            "plan": dict(self.plan),
            "generator": self.generator,
            "model": self.model,
        }


class CodeSwitchGenerator(Protocol):
    """The whole contract. Implement this to plug in a different switcher."""

    name: str

    def generate(self, request: CodeSwitchRequest) -> CodeSwitchResult: ...


def build_instruction(spec: CodeSwitchSpec, protected: Sequence[str]) -> str:
    """The instruction a language model is given. Deterministic from the spec.

    Kept as a pure function so it can be inspected, diffed and frozen without
    running anything.
    """
    lines: list[str] = []
    lines.append(
        "Rewrite the request below as a single code-switched request that mixes "
        f"these languages: {', '.join(spec.languages)}."
    )
    lines.append("")
    lines.append("MEANING")
    lines.append(
        "Preserve the meaning exactly. The rewritten request must ask for the "
        "same operation, with the same parameters, under the same stated "
        "conditions. Do not add, remove or soften any part of it."
    )
    lines.append("")
    lines.append("SWITCHING UNIT")
    lines.append(_GRANULARITY_RULES[spec.granularity])
    lines.append("")
    lines.append("LANGUAGE ROLES")
    lines.append(f"Matrix language (the frame of the text): {spec.matrix_language}.")
    lines.append(f"Introduce languages in this order: {' then '.join(spec.language_order)}.")
    shares = ", ".join(
        f"{name} about {spec.dominance_for(name):.0%}" for name in spec.language_order
    )
    lines.append(f"Approximate share of the text per language: {shares}.")
    if spec.switch_rate is not None:
        lines.append(
            f"Switch language at roughly {spec.switch_rate:.0%} of the available "
            "switch points."
        )
    if spec.granularity == "tag" and spec.tag_categories:
        lines.append("")
        lines.append("TAGS TO BORROW")
        for category in spec.tag_categories:
            lines.append(f"- {_TAG_GLOSS.get(category, category)}")
    if spec.semantic_roles:
        lines.append("")
        lines.append("SEMANTIC ROLE ASSIGNMENT")
        for role, language in spec.semantic_roles.items():
            lines.append(f"- {_ROLE_GLOSS.get(role, role)}: write in {language}")
    if protected:
        lines.append("")
        lines.append("MUST APPEAR UNCHANGED")
        lines.append(
            "Copy these exactly, character for character, in any script: "
            + ", ".join(protected)
        )
    lines.append("")
    lines.append("OUTPUT")
    lines.append(
        'Respond with only a JSON object: {"text": "<the rewritten request>"}. '
        "No commentary."
    )
    return "\n".join(lines)


class LLMCodeSwitchGenerator:
    """Generate with a language model, validate, and retry with the errors.

    ``complete`` is any callable taking ``(system, user)`` and returning a
    string. That keeps this class independent of the runtime: the experiment
    passes its Ollama client, a test passes a stub.
    """

    name = "llm"

    def __init__(
        self,
        complete: Callable[[str, str], str],
        validate: Callable[[CodeSwitchSpec, str, str], list[str]],
        *,
        model: str | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._complete = complete
        self._validate = validate
        self._model = model
        self._max_attempts = max(1, int(max_attempts))

    _SYSTEM = (
        "You are a bilingual writing assistant producing controlled "
        "code-switched text for a linguistics experiment. You follow the "
        "switching specification exactly and you never change what the text "
        "asks for."
    )

    def generate(self, request: CodeSwitchRequest) -> CodeSwitchResult:
        spec = request.spec
        instruction = build_instruction(spec, request.protected_tokens)
        problems: list[str] = []
        text = ""
        for attempt in range(1, self._max_attempts + 1):
            user = f"{instruction}\n\nREQUEST TO REWRITE\n{request.normalised_source}"
            if problems:
                user += (
                    "\n\nYour previous attempt was rejected for these reasons. "
                    "Fix every one:\n- " + "\n- ".join(problems)
                )
            raw = self._complete(self._SYSTEM, user)
            text = _extract_text(raw)
            problems = self._validate(spec, text, request.normalised_source)
            if not problems:
                return CodeSwitchResult(
                    surface_id=spec.surface_id,
                    text=text,
                    ok=True,
                    attempts=attempt,
                    plan=spec.as_dict(),
                    generator=self.name,
                    model=self._model,
                )
        return CodeSwitchResult(
            surface_id=spec.surface_id,
            text=text,
            ok=False,
            attempts=self._max_attempts,
            problems=tuple(problems),
            plan=spec.as_dict(),
            generator=self.name,
            model=self._model,
        )


class PassthroughGenerator:
    """Return the source unchanged. For the source surface and for smoke tests."""

    name = "passthrough"

    def generate(self, request: CodeSwitchRequest) -> CodeSwitchResult:
        return CodeSwitchResult(
            surface_id=request.spec.surface_id,
            text=request.normalised_source,
            ok=True,
            plan=request.spec.as_dict(),
            generator=self.name,
        )


class ScriptedGenerator:
    """Replay pre-authored text, keyed by ``(case_id, surface_id)``.

    This is how human-reviewed forms enter the system: a reviewer produces a
    file, and the run uses it verbatim rather than generating anything. It is
    also the deterministic generator used in tests.
    """

    name = "scripted"

    def __init__(
        self,
        table: Mapping[tuple[str, str], str],
        validate: Callable[[CodeSwitchSpec, str, str], list[str]] | None = None,
    ) -> None:
        self._table = dict(table)
        self._validate = validate

    def generate(self, request: CodeSwitchRequest) -> CodeSwitchResult:
        key = (request.case_id, request.spec.surface_id)
        text = self._table.get(key)
        if text is None:
            return CodeSwitchResult(
                surface_id=request.spec.surface_id,
                text="",
                ok=False,
                problems=(f"no scripted text for {key}",),
                plan=request.spec.as_dict(),
                generator=self.name,
            )
        problems = (
            self._validate(request.spec, text, request.normalised_source)
            if self._validate
            else []
        )
        return CodeSwitchResult(
            surface_id=request.spec.surface_id,
            text=text,
            ok=not problems,
            problems=tuple(problems),
            plan=request.spec.as_dict(),
            generator=self.name,
        )


GENERATORS: dict[str, type] = {
    "llm": LLMCodeSwitchGenerator,
    "passthrough": PassthroughGenerator,
    "scripted": ScriptedGenerator,
}


def register_generator(name: str, factory: type) -> None:
    """Add a generator so language profiles can name it."""
    GENERATORS[name] = factory


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_text(raw: str) -> str:
    """Pull the rewritten request out of a model response."""
    if not raw:
        return ""
    match = _JSON_BLOCK.search(raw)
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping):
            value = payload.get("text")
            if isinstance(value, str):
                return unicodedata.normalize("NFC", value.strip())
    return unicodedata.normalize("NFC", raw.strip())
