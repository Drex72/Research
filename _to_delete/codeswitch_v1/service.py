"""The plug interface: text in, code-switched text out.

Everything else in this package is machinery. This is the part you call.

    switcher = CodeSwitcher.from_profile("languages/CS-EN-KO-YO.json")
    result = switcher.switch("Please approve loan SWIFT-000001 for 300,000.")
    print(result.text)

The switcher holds no experiment state. It does not know what a scenario is,
what a pipeline is, or what is being measured. It takes a string and a
specification and returns a string, plus the checks that ran on it. That is
what makes it swappable: the experiment can use it, a notebook can use it, and
a reviewer can use it to inspect one prompt without setting anything up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .detect import (
    DetectorSet,
    SurfaceSpec,
    load_detectors,
    protected_tokens,
    validate_surface_text,
)
from .generator import (
    GENERATORS,
    CodeSwitchGenerator,
    CodeSwitchRequest,
    CodeSwitchResult,
    LLMCodeSwitchGenerator,
    PassthroughGenerator,
    ScriptedGenerator,
    build_instruction,
)
from .spec import CodeSwitchSpec, CodeSwitchSpecError, load_code_switch_spec

DEFAULT_DETECTORS = Path("languages/_detectors.json")


@dataclass
class CodeSwitcher:
    """A configured switcher for one surface."""

    spec: CodeSwitchSpec
    surface: SurfaceSpec
    detectors: DetectorSet
    generator: CodeSwitchGenerator

    # ---- construction ---------------------------------------------------

    @classmethod
    def from_profile(
        cls,
        profile_path: str | Path,
        *,
        detectors_path: str | Path | None = None,
        complete: Callable[[str, str], str] | None = None,
        scripted: Mapping[tuple[str, str], str] | None = None,
        model: str | None = None,
        max_attempts: int = 3,
    ) -> "CodeSwitcher":
        """Build from a language profile on disk.

        ``complete`` is only needed for the ``llm`` generator. Pass any
        callable taking ``(system, user)`` and returning the model's text, so
        this module never depends on a particular client.
        """
        from .detect import _surface_from_raw

        path = Path(profile_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        surface = _surface_from_raw(raw, path)
        spec = load_code_switch_spec(
            surface.surface_id, list(surface.languages), raw.get("code_switching")
        )
        if spec is None:
            raise CodeSwitchSpecError(
                f"{path} has no code_switching block; it is not a switchable surface"
            )
        detectors = load_detectors(
            Path(detectors_path) if detectors_path else path.parent / "_detectors.json"
        )
        generator = cls._build_generator(
            spec,
            surface,
            detectors,
            complete=complete,
            scripted=scripted,
            model=model,
            max_attempts=max_attempts,
        )
        return cls(spec=spec, surface=surface, detectors=detectors, generator=generator)

    @classmethod
    def from_spec(
        cls,
        surface_id: str,
        languages: Sequence[str],
        code_switching: Mapping[str, Any],
        *,
        detectors_path: str | Path = DEFAULT_DETECTORS,
        complete: Callable[[str, str], str] | None = None,
        scripted: Mapping[tuple[str, str], str] | None = None,
        model: str | None = None,
        max_attempts: int = 3,
        min_hits: int = 3,
        max_dominance: float = 0.85,
        review_status: str = "review-required",
    ) -> "CodeSwitcher":
        """Build a switcher from values in code, with no profile file.

        Use this to sweep a factor without writing a file per cell. Everything
        ``from_profile`` reads from JSON is a parameter here.
        """
        from .detect import _surface_from_raw

        body = {
            "schema_version": 2,
            "surface_id": surface_id,
            "type": "code_switched" if len(languages) > 1 else "monolingual",
            "languages": list(languages),
            "application_point": "user_request",
            "construction": "constructed in code",
            "review_status": review_status,
            "detection": {
                "min_hits_per_language": min_hits,
                "max_dominance": max_dominance,
            },
        }
        surface = _surface_from_raw(body, None)
        spec = load_code_switch_spec(surface_id, list(languages), dict(code_switching))
        if spec is None:
            raise CodeSwitchSpecError(f"{surface_id}: no code_switching values given")
        detectors = load_detectors(Path(detectors_path))
        generator = cls._build_generator(
            spec, surface, detectors,
            complete=complete, scripted=scripted, model=model, max_attempts=max_attempts,
        )
        return cls(spec=spec, surface=surface, detectors=detectors, generator=generator)

    @staticmethod
    def _build_generator(
        spec: CodeSwitchSpec,
        surface: SurfaceSpec,
        detectors: DetectorSet,
        *,
        complete: Callable[[str, str], str] | None,
        scripted: Mapping[tuple[str, str], str] | None,
        model: str | None,
        max_attempts: int,
    ) -> CodeSwitchGenerator:
        def validate(_spec: CodeSwitchSpec, text: str, source: str) -> list[str]:
            return validate_surface_text(
                surface, text, detectors, source_text=source
            )

        name = spec.generator
        if name == "passthrough":
            return PassthroughGenerator()
        if name == "scripted":
            return ScriptedGenerator(scripted or {}, validate)
        if name == "llm":
            if complete is None:
                raise CodeSwitchSpecError(
                    f"surface {spec.surface_id} uses the llm generator; "
                    "pass complete=<callable> to CodeSwitcher.from_profile"
                )
            return LLMCodeSwitchGenerator(
                complete, validate, model=model or spec.model_profile, max_attempts=max_attempts
            )
        factory = GENERATORS.get(name)
        if factory is None:
            raise CodeSwitchSpecError(f"unknown code-switch generator: {name}")
        return factory()  # type: ignore[call-arg]

    # ---- use ------------------------------------------------------------

    def switch(
        self, text: str, *, case_id: str = "", extra_protected: Iterable[str] = ()
    ) -> CodeSwitchResult:
        """Transform one request."""
        tokens = tuple(sorted(protected_tokens(text, extra_protected)))
        request = CodeSwitchRequest(
            source_text=text,
            spec=self.spec,
            protected_tokens=tokens,
            case_id=case_id,
        )
        return self.generator.generate(request)

    def switch_many(
        self, items: Sequence[Mapping[str, str]]
    ) -> list[CodeSwitchResult]:
        """Transform a batch of ``{"case_id": ..., "text": ...}`` items."""
        return [
            self.switch(item["text"], case_id=str(item.get("case_id", "")))
            for item in items
        ]

    def check(self, text: str, source_text: str | None = None) -> list[str]:
        """Run the structural checks on text this switcher did not produce.

        Useful for reviewing human-authored forms before marking a surface
        reviewed.
        """
        return validate_surface_text(
            self.surface, text, self.detectors, source_text=source_text
        )

    def language_profile(self, text: str) -> dict[str, int]:
        """Per-language evidence counts, for inspecting a generated form."""
        return self.detectors.profile(text, list(self.spec.languages))

    def instruction(self, text: str = "") -> str:
        """The exact instruction the llm generator would send. For auditing."""
        return build_instruction(self.spec, tuple(sorted(protected_tokens(text))))

    def describe(self) -> dict[str, Any]:
        return {
            "surface": self.spec.surface_id,
            "summary": self.spec.describe(),
            "review_status": self.surface.review_status,
            "reviewed": self.surface.reviewed,
            **self.spec.as_dict(),
        }
