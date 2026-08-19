"""Validation for generated code-switched text."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence
from .translator import DEFAULT_VERIFICATION_MODEL as VERIFICATION_MODEL, Translator
from .reviewer import (
    DEFAULT_FINAL_REVIEWER_MODEL,
    MachineReviewError,
    MachineReviewFailed,
    MachineReviewIssue,
    MachineReviewResult,
    MachineReviewValidator,
)
from .cache import (
    BACK_TRANSLATION_PROMPT_VERSION,
    MIXING_PROMPT_VERSION,
    REVIEW_PROMPT_VERSION,
    TRANSLATION_PROMPT_VERSION,
    created_at,
    stable_key,
)

SIMILARITY_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SIMILARITY_CACHE = (
    Path(__file__).resolve().parents[2] / ".model-cache" / "sentence-transformers"
)

_PROTECTED = re.compile(
    r"(?<![A-Z0-9._-])"
    r"(?:[A-Z][A-Z0-9]*-[A-Z0-9-]{2,}|\d[\d,._]*\d|\d)"
    r"(?![A-Z0-9_-])"
)

_NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|do\s+not|don't|mustn't|shouldn't)\b",
    re.IGNORECASE,
)


def protected_tokens(text: str, extra: Iterable[str] = ()) -> set[str]:
    return set(_PROTECTED.findall(text)) | {item for item in extra if item}


def plain_number(token: str) -> str:
    return token.replace(",", "").replace("_", "").rstrip(".")


class SimilarityScorer(Protocol):
    def score(self, left: str, right: str) -> float: ...


class SentenceTransformerScorer:
    def __init__(
        self,
        *,
        model_name: str = SIMILARITY_MODEL,
        cache_dir: Path = SIMILARITY_CACHE,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.device = device or os.environ.get("CSRT_SIMILARITY_DEVICE", "cpu")
        self._model = None

    def _load(self):
        if self._model is None:
            os.environ.setdefault(
                "HF_HOME",
                str(Path(__file__).resolve().parents[2] / ".model-cache" / "huggingface"),
            )

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "semantic validation requires sentence-transformers"
                ) from exc

            self._model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self.cache_dir),
                device=self.device,
            )

        return self._model

    def score(self, left: str, right: str) -> float:
        embeddings = self._load().encode(
            [left, right],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        return max(0.0, min(1.0, float(embeddings[0] @ embeddings[1])))


@dataclass(frozen=True)
class BackTranslatedSegment:
    position: int
    language: str
    original_text: str
    english_text: str
    backend: str


@dataclass(frozen=True)
class SemanticValidation:
    passed: bool
    similarity: float | None
    threshold: float
    back_translated_text: str
    segments: tuple[BackTranslatedSegment, ...]
    problems: tuple[str, ...] = ()


class BackTranslationValidator:
    def __init__(
        self,
        *,
        translator: Translator,
        scorer: SimilarityScorer | None = None,
        minimum_similarity: float = 0.82,
        parallel_languages: bool = True,
    ) -> None:
        if not 0.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity must be between 0 and 1")

        self.translator = translator
        self.scorer = scorer or SentenceTransformerScorer()
        self.minimum_similarity = float(minimum_similarity)
        self.parallel_languages = bool(parallel_languages)

    def _render_foreign(
        self,
        segments: Sequence[Mapping[str, Any]],
        source_language: str,
        problems: list[str],
    ) -> dict[int, tuple[str, str]]:
        """Back-translate every non-source segment, grouped by language.

        Returns position -> (english, backend). A position missing from the
        result could not be rendered, and the caller reports that as a gap
        rather than silently shortening the reconstruction.

        If the batch comes back the wrong length the segments are translated
        one at a time instead. A batch that loses or merges an item would
        misalign every position after it, which is a worse failure than the
        cost it saves.
        """
        by_language: dict[str, list[tuple[int, str]]] = {}
        for position, segment in enumerate(segments, 1):
            language = str(segment.get("language", ""))
            if language.casefold() == source_language.casefold():
                continue
            text = str(segment.get("text", "")).strip()
            if text:
                by_language.setdefault(language, []).append((position, text))

        def translate_language(
            language: str,
            items: list[tuple[int, str]],
        ) -> tuple[dict[int, tuple[str, str]], list[str]]:
            language_rendered: dict[int, tuple[str, str]] = {}
            language_problems: list[str] = []
            positions = [position for position, _ in items]
            texts = [text for _, text in items]
            batch = None

            if len(texts) > 1 and hasattr(self.translator, "translate_many"):
                try:
                    batch = self.translator.translate_many(
                        texts,
                        source_language=language,
                        target_language=source_language,
                    )
                except Exception as exc:
                    language_problems.append(
                        f"{language} batch back-translation failed, falling back "
                        f"to one call per segment: {type(exc).__name__}: {exc}"
                    )
                    batch = None

                if batch is not None and len(batch.translated_texts) != len(texts):
                    language_problems.append(
                        f"{language} batch back-translation returned "
                        f"{len(batch.translated_texts)} of {len(texts)} segments, "
                        "falling back to one call per segment"
                    )
                    batch = None

            if batch is not None:
                for position, english in zip(positions, batch.translated_texts):
                    language_rendered[position] = (english, batch.backend)
            else:
                for position, text in items:
                    try:
                        translated = self.translator.translate(
                            text,
                            source_language=language,
                            target_language=source_language,
                        )
                    except Exception as exc:
                        language_problems.append(
                            f"segment {position} back-translation failed: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue
                    language_rendered[position] = (
                        translated.translated_text,
                        translated.backend,
                    )

            return language_rendered, language_problems

        rendered: dict[int, tuple[str, str]] = {}
        groups = list(by_language.items())
        if self.parallel_languages and len(groups) > 1:
            with ThreadPoolExecutor(
                max_workers=min(4, len(groups))
            ) as executor:
                translated_groups = list(
                    executor.map(
                        lambda item: translate_language(*item),
                        groups,
                    )
                )
        else:
            translated_groups = [
                translate_language(*item)
                for item in groups
            ]

        for language_rendered, language_problems in translated_groups:
            rendered.update(language_rendered)
            problems.extend(language_problems)

        return rendered

    def validate(
        self,
        source_text: str,
        source_language: str,
        result: Any,
    ) -> SemanticValidation:
        if not result.segments:
            return SemanticValidation(
                passed=False,
                similarity=None,
                threshold=self.minimum_similarity,
                back_translated_text="",
                segments=(),
                problems=("structured segments are required for back-translation",),
            )

        problems: list[str] = []
        back_segments: list[BackTranslatedSegment] = []

        # One request per foreign language, not one per segment. Segment-wise
        # back-translation was the single largest cost in the pipeline: a
        # clause-level turn spends nine calls, a word-level one thirty-odd, and
        # each pays the full instruction block plus a reasoning-model's fixed
        # overhead to render a handful of words. Batching pays that once.
        rendered = self._render_foreign(result.segments, source_language, problems)

        for position, segment in enumerate(result.segments, 1):
            language = str(segment.get("language", ""))
            text = str(segment.get("text", "")).strip()

            if language.casefold() == source_language.casefold():
                english = text
                backend = "source-language"
            else:
                if position not in rendered:
                    continue
                english, backend = rendered[position]

            back_segments.append(
                BackTranslatedSegment(
                    position=position,
                    language=language,
                    original_text=text,
                    english_text=english,
                    backend=backend,
                )
            )

        reconstructed = " ".join(segment.english_text for segment in back_segments)
        similarity: float | None = None

        if len(back_segments) != len(result.segments):
            problems.append("not every segment could be reconstructed in English")
        elif reconstructed:
            try:
                similarity = self.scorer.score(source_text, reconstructed)
            except Exception as exc:
                problems.append(
                    f"semantic similarity failed: {type(exc).__name__}: {exc}"
                )

            if similarity is not None and similarity < self.minimum_similarity:
                problems.append(
                    f"semantic similarity {similarity:.3f} is below "
                    f"{self.minimum_similarity:.3f}"
                )

        source_values = protected_tokens(source_text)
        reconstructed_values = protected_tokens(reconstructed)
        missing = sorted(source_values - reconstructed_values)
        added = sorted(reconstructed_values - source_values)

        if missing:
            problems.append(
                "back-translation dropped protected values: " + ", ".join(missing)
            )

        if added:
            problems.append(
                "back-translation added protected values: " + ", ".join(added)
            )

        if bool(_NEGATION.search(source_text)) != bool(_NEGATION.search(reconstructed)):
            problems.append("negation polarity changed during back-translation")

        return SemanticValidation(
            passed=not problems,
            similarity=similarity,
            threshold=self.minimum_similarity,
            back_translated_text=reconstructed,
            segments=tuple(back_segments),
            problems=tuple(problems),
        )


@dataclass(frozen=True)
class SwitchResult:
    generation: Any
    semantic: SemanticValidation | None
    translation_backends: Mapping[str, str] = field(default_factory=dict)
    machine_review: MachineReviewResult | None = None
    cache_hit: bool = False

    @property
    def ok(self) -> bool:
        return self.generation.ok and bool(self.semantic and self.semantic.passed)

    @property
    def text(self) -> str:
        return self.generation.text

    @property
    def problems(self) -> tuple[str, ...]:
        semantic_problems = self.semantic.problems if self.semantic else ()
        return (*self.generation.problems, *semantic_problems)


def run_pipeline(
    switcher: Any,
    source_text: str,
    *,
    source_language: str = "English",
    translations: Mapping[str, Any] | None = None,
    protect: Sequence[str] = (),
    review_attempts: int = 2,
) -> SwitchResult:
    source_text = source_text.strip()
    supplied = dict(translations or {})
    parallel_texts: dict[str, str] = {}
    backends: dict[str, str] = {}
    verifier = Translator(model=VERIFICATION_MODEL, reasoning_effort="none")
    domain = "financial risk management"
    technical_attempts = max(1, int(review_attempts))

    for language in switcher.names:
        if language.casefold() == source_language.casefold():
            parallel_texts[language] = source_text
            backends[language] = "source-language"

    foreign_languages = [
        language
        for language in switcher.names
        if language.casefold() != source_language.casefold()
    ]

    def prepare_language(language: str):
        translator = Translator()
        reviewer = MachineReviewValidator()
        translation_key = stable_key(
            {
                "source_text": source_text,
                "source_language": source_language,
                "target_language": language,
                "translation_model": translator.backend_name,
                "translation_review_model": reviewer.backend_name,
                "translation_prompt_version": TRANSLATION_PROMPT_VERSION,
                "review_prompt_version": REVIEW_PROMPT_VERSION,
            }
        )
        cached = switcher.cache.get_translation(translation_key)

        if cached is not None:
            translated_text = cached["translated_text"]
            backend = cached["backend"]
            review = _review_from_dict(cached["machine_review"])
        else:
            translated = supplied.get(language)
            if translated is None:
                translated = translator.translate(
                    source_text,
                    source_language=source_language,
                    target_language=language,
                )

            if translated.source_text != source_text:
                raise ValueError(
                    f"{language} machine translation source text does not match"
                )
            if translated.target_language.casefold() != language.casefold():
                raise ValueError(
                    f"machine translation target {translated.target_language!r} "
                    f"does not match {language!r}"
                )

            review = _technical_retry(
                lambda: reviewer.review(
                    source_text,
                    translated.translated_text,
                    source_language=source_language,
                    target_language=language,
                    domain=domain,
                ),
                technical_attempts,
            )
            translated_text = translated.translated_text
            backend = translated.backend
            switcher.cache.save_translation(
                translation_key,
                {
                    "source_text": source_text,
                    "source_language": source_language,
                    "target_language": language,
                    "translated_text": translated_text,
                    "backend": backend,
                    "model": translator.backend_name,
                    "translation_prompt_version": TRANSLATION_PROMPT_VERSION,
                    "review_prompt_version": REVIEW_PROMPT_VERSION,
                    "usage": dict(translated.usage or {}),
                    "machine_review": _review_to_dict(review),
                    "created_at": created_at(),
                },
            )

        return language, translated_text, backend, review

    if switcher.parallel_languages and len(foreign_languages) > 1:
        with ThreadPoolExecutor(
            max_workers=min(4, len(foreign_languages))
        ) as executor:
            prepared_items = list(
                executor.map(
                    prepare_language,
                    foreign_languages,
                )
            )
    else:
        prepared_items = [
            prepare_language(language)
            for language in foreign_languages
        ]

    prepared = {
        language: (translated_text, backend, review)
        for language, translated_text, backend, review in prepared_items
    }

    for language in foreign_languages:
        translated_text, backend, review = prepared[language]
        if not review.passed:
            raise MachineReviewFailed(review)

        parallel_texts[language] = translated_text
        backends[language] = backend

    mix_payload = {
        "source_text": source_text,
        "languages": list(switcher.names),
        "granularity": switcher.granularity,
        "matrix": switcher.matrix,
        "order": list(switcher.order),
        "dominance": dict(switcher.dominance),
        "switch_rate": switcher.switch_rate,
        "mixing_model": switcher.model,
        "mixing_prompt_version": MIXING_PROMPT_VERSION,
        "review_prompt_version": REVIEW_PROMPT_VERSION,
        "back_translation_prompt_version": BACK_TRANSLATION_PROMPT_VERSION,
        "parallel_texts_hash": stable_key(parallel_texts),
        "final_review_model": DEFAULT_FINAL_REVIEWER_MODEL,
    }
    mix_key = stable_key(mix_payload)
    cached_mix = switcher.cache.get_mix(mix_key)
    if cached_mix is not None:
        return _switch_result_from_dict(cached_mix, cache_hit=True)

    generation = switcher._mix(
        source_text,
        protect=protect,
        parallel_texts=parallel_texts,
    )

    for failed_attempt in generation.attempt_history:
        if failed_attempt.get("problems"):
            switcher.cache.save_failed_mix(
                {
                    "key": mix_key,
                    **mix_payload,
                    **dict(failed_attempt),
                    "created_at": created_at(),
                }
            )

    if not generation.ok:
        return SwitchResult(
            generation=generation,
            semantic=None,
            translation_backends=backends,
        )

    reviewer = MachineReviewValidator(model=DEFAULT_FINAL_REVIEWER_MODEL)
    final_review = _technical_retry(
        lambda: reviewer.review_code_switched(
            source_text,
            generation,
            source_language=source_language,
            domain=domain,
        ),
        technical_attempts,
    )

    if not final_review.passed:
        switcher.cache.save_failed_mix(
            {
                "key": mix_key,
                **mix_payload,
                "attempt": generation.attempts,
                "text": generation.text,
                "segments": [dict(item) for item in generation.segments],
                "problems": [final_review.summary],
                "stage": "code_switch_review",
                "created_at": created_at(),
            }
        )
        raise MachineReviewFailed(final_review)

    semantic = BackTranslationValidator(
        translator=verifier,
        parallel_languages=switcher.parallel_languages,
    ).validate(
        source_text,
        source_language,
        generation,
    )
    result = SwitchResult(
        generation=generation,
        semantic=semantic,
        translation_backends=backends,
        machine_review=final_review,
    )

    if semantic.passed:
        switcher.cache.save_mix(
            mix_key,
            _switch_result_to_dict(result),
        )
    else:
        switcher.cache.save_failed_mix(
            {
                "key": mix_key,
                **mix_payload,
                "attempt": generation.attempts,
                "text": generation.text,
                "segments": [dict(item) for item in generation.segments],
                "problems": list(semantic.problems),
                "stage": "back_translation",
                "created_at": created_at(),
            }
        )

    return result


def _technical_retry(operation, attempts: int):
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except MachineReviewError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
    raise last_error


def _review_to_dict(review: MachineReviewResult) -> dict[str, Any]:
    return asdict(review)


def _review_from_dict(value: Mapping[str, Any]) -> MachineReviewResult:
    return MachineReviewResult(
        source_text=str(value["source_text"]),
        translated_text=str(value["translated_text"]),
        source_language=str(value["source_language"]),
        target_language=str(value["target_language"]),
        reviewer_backend=str(value["reviewer_backend"]),
        passed=bool(value["passed"]),
        summary=str(value["summary"]),
        issues=tuple(
            MachineReviewIssue(**dict(issue))
            for issue in value.get("issues", [])
        ),
        corrected_translation=value.get("corrected_translation"),
        usage=value.get("usage"),
    )


def _switch_result_to_dict(result: SwitchResult) -> dict[str, Any]:
    return {
        "generation": result.generation.as_dict(),
        "semantic": asdict(result.semantic) if result.semantic else None,
        "translation_backends": dict(result.translation_backends),
        "machine_review": (
            _review_to_dict(result.machine_review)
            if result.machine_review
            else None
        ),
        "created_at": created_at(),
    }


def _switch_result_from_dict(
    value: Mapping[str, Any],
    *,
    cache_hit: bool,
) -> SwitchResult:
    from .switcher import Result

    generation_value = dict(value["generation"])
    generation = Result(
        text=generation_value["text"],
        ok=bool(generation_value["ok"]),
        attempts=int(generation_value["attempts"]),
        problems=tuple(generation_value.get("problems", [])),
        languages=dict(generation_value.get("languages", {})),
        condition=dict(generation_value.get("condition", {})),
        segments=tuple(generation_value.get("segments", [])),
        attempt_history=tuple(generation_value.get("attempt_history", [])),
    )
    semantic_value = value.get("semantic")
    semantic = None
    if semantic_value is not None:
        semantic = SemanticValidation(
            passed=bool(semantic_value["passed"]),
            similarity=semantic_value.get("similarity"),
            threshold=float(semantic_value["threshold"]),
            back_translated_text=str(semantic_value["back_translated_text"]),
            segments=tuple(
                BackTranslatedSegment(**dict(segment))
                for segment in semantic_value.get("segments", [])
            ),
            problems=tuple(semantic_value.get("problems", [])),
        )
    review_value = value.get("machine_review")
    return SwitchResult(
        generation=generation,
        semantic=semantic,
        translation_backends=dict(value.get("translation_backends", {})),
        machine_review=(
            _review_from_dict(review_value)
            if isinstance(review_value, Mapping)
            else None
        ),
        cache_hit=cache_hit,
    )
