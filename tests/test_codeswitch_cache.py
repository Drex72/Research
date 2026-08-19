from __future__ import annotations

import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from csrt_codeswitch import CodeSwitcher, Result
from csrt_codeswitch.reviewer import (
    MachineReviewFailed,
    MachineReviewResult,
)
from csrt_codeswitch.translator import (
    BatchTranslationResult,
    TranslationResult,
)
from csrt_codeswitch import validation


class FixedScorer:
    def score(self, left: str, right: str) -> float:
        return 1.0


class FakeTranslator:
    forward_calls = 0
    back_calls = 0

    def __init__(self, *args, **kwargs):
        self.backend_name = "openai-fake"

    def translate(self, text, *, source_language, target_language):
        if target_language == "English":
            type(self).back_calls += 1
            translated = "translated"
        else:
            type(self).forward_calls += 1
            translated = f"{target_language} translation"
        return TranslationResult(
            source_text=text.strip(),
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            backend=self.backend_name,
            usage={"input_tokens": 10, "output_tokens": 5},
        )

    def translate_many(self, texts, *, source_language, target_language):
        type(self).back_calls += 1
        return BatchTranslationResult(
            source_texts=tuple(texts),
            translated_texts=tuple("translated" for _ in texts),
            source_language=source_language,
            target_language=target_language,
            backend=self.backend_name,
        )


class FakeReviewer:
    translation_calls = 0
    final_calls = 0
    fail_final = False

    def __init__(self, *args, **kwargs):
        self.backend_name = "openai-fake-reviewer"

    @staticmethod
    def _result(source, translated, source_language, target_language, passed):
        return MachineReviewResult(
            source_text=source,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            reviewer_backend="openai-fake-reviewer",
            passed=passed,
            summary="passed" if passed else "substantive failure",
        )

    def review(
        self,
        source,
        translated,
        *,
        source_language,
        target_language,
        domain,
    ):
        type(self).translation_calls += 1
        return self._result(
            source,
            translated,
            source_language,
            target_language,
            True,
        )

    def review_code_switched(
        self,
        source,
        result,
        *,
        source_language,
        domain,
    ):
        type(self).final_calls += 1
        return self._result(
            source,
            result.text,
            source_language,
            "mixed",
            not type(self).fail_final,
        )


class ConcurrentTranslator(FakeTranslator):
    barrier = threading.Barrier(3)

    def translate(self, text, *, source_language, target_language):
        if target_language != "English":
            type(self).barrier.wait(timeout=2)
        return super().translate(
            text,
            source_language=source_language,
            target_language=target_language,
        )


class CacheBehaviourTests(unittest.TestCase):
    def setUp(self):
        FakeTranslator.forward_calls = 0
        FakeTranslator.back_calls = 0
        FakeReviewer.translation_calls = 0
        FakeReviewer.final_calls = 0
        FakeReviewer.fail_final = False
        self.temporary = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temporary.name)
        self.mix_calls = 0
        self.patches = [
            patch.object(validation, "Translator", FakeTranslator),
            patch.object(validation, "MachineReviewValidator", FakeReviewer),
            patch.object(validation, "SentenceTransformerScorer", FixedScorer),
        ]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in reversed(self.patches):
            active.stop()
        self.temporary.cleanup()

    def switcher(
        self,
        languages=("English", "Yoruba"),
        *,
        granularity="clause",
        order=None,
        fail_mix=False,
        parallel_languages=True,
    ):
        switcher = CodeSwitcher(
            list(languages),
            granularity=granularity,
            order=list(order) if order else None,
            attempts=1,
            min_hits=1,
            max_dominance=1.0,
            artifacts_dir=self.cache_dir,
            parallel_languages=parallel_languages,
        )

        def mix(this, source, **kwargs):
            self.mix_calls += 1
            segments = tuple(
                {
                    "text": source if language == "English" else "translated",
                    "language": language,
                    "unit": granularity,
                }
                for language in this.order
            )
            problems = ("structural failure",) if fail_mix else ()
            return Result(
                text=" ".join(item["text"] for item in segments),
                ok=not fail_mix,
                attempts=1,
                problems=problems,
                languages={language: 1 for language in this.names},
                condition=this.as_dict(),
                segments=segments,
                attempt_history=(
                    {
                        "attempt": 1,
                        "text": "failed" if fail_mix else "accepted",
                        "segments": list(segments),
                        "problems": list(problems),
                    },
                ),
            )

        switcher._mix = types.MethodType(mix, switcher)
        return switcher

    def execute(self, switcher):
        return switcher.switch("Please approve.")

    def test_identical_second_run_reuses_translation_and_mix(self):
        first = self.execute(self.switcher())
        self.assertTrue(first.ok)
        self.assertEqual(FakeTranslator.forward_calls, 1)
        self.assertEqual(self.mix_calls, 1)

        second = self.execute(self.switcher())
        self.assertTrue(second.cache_hit)
        self.assertEqual(FakeTranslator.forward_calls, 1)
        self.assertEqual(self.mix_calls, 1)

    def test_new_target_language_causes_translation(self):
        self.execute(self.switcher())
        self.execute(self.switcher(("English", "Korean")))
        self.assertEqual(FakeTranslator.forward_calls, 2)

    def test_granularity_reuses_translation_but_creates_mix(self):
        self.execute(self.switcher(granularity="clause"))
        self.execute(self.switcher(granularity="sentence"))
        self.assertEqual(FakeTranslator.forward_calls, 1)
        self.assertEqual(self.mix_calls, 2)

    def test_language_order_creates_new_mix(self):
        self.execute(self.switcher(order=("English", "Yoruba")))
        self.execute(self.switcher(order=("Yoruba", "English")))
        self.assertEqual(FakeTranslator.forward_calls, 1)
        self.assertEqual(self.mix_calls, 2)

    def test_mixing_prompt_version_creates_new_mix(self):
        self.execute(self.switcher())
        with patch.object(validation, "MIXING_PROMPT_VERSION", "2"):
            self.execute(self.switcher())
        self.assertEqual(FakeTranslator.forward_calls, 1)
        self.assertEqual(self.mix_calls, 2)

    def test_downstream_agent_change_does_not_reconstruct(self):
        result = self.execute(self.switcher())
        before = (
            FakeTranslator.forward_calls,
            FakeReviewer.translation_calls,
            FakeReviewer.final_calls,
            self.mix_calls,
        )
        for downstream_agent in ("agent-a", "agent-b"):
            _ = (downstream_agent, result.text)
        self.assertEqual(
            before,
            (
                FakeTranslator.forward_calls,
                FakeReviewer.translation_calls,
                FakeReviewer.final_calls,
                self.mix_calls,
            ),
        )

    def test_failed_mix_is_saved_but_not_reused(self):
        failed = self.execute(self.switcher(fail_mix=True))
        self.assertFalse(failed.ok)
        failure_file = self.cache_dir / "failed_mixes.jsonl"
        self.assertTrue(failure_file.exists())
        self.assertEqual(len(failure_file.read_text().splitlines()), 1)

        passed = self.execute(self.switcher())
        self.assertTrue(passed.ok)
        self.assertEqual(self.mix_calls, 2)

    def test_back_translation_only_runs_after_final_review_passes(self):
        FakeReviewer.fail_final = True
        with self.assertRaises(MachineReviewFailed):
            self.execute(self.switcher())
        self.assertEqual(FakeReviewer.final_calls, 1)
        self.assertEqual(FakeTranslator.back_calls, 0)

    def test_substantive_review_failure_is_not_retried(self):
        FakeReviewer.fail_final = True
        with self.assertRaises(MachineReviewFailed):
            self.execute(self.switcher())
        self.assertEqual(FakeReviewer.final_calls, 1)
        self.assertEqual(self.mix_calls, 1)

    def test_cache_uses_sha256_keys(self):
        self.execute(self.switcher())
        records = json.loads(
            (self.cache_dir / "translations.json").read_text()
        )
        key = next(iter(records))
        self.assertEqual(len(key), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in key))

    def test_independent_languages_are_prepared_concurrently(self):
        ConcurrentTranslator.barrier = threading.Barrier(3)
        with patch.object(validation, "Translator", ConcurrentTranslator):
            result = self.execute(
                self.switcher(
                    ("English", "Yoruba", "Korean", "Spanish"),
                )
            )

        self.assertTrue(result.ok)
        records = json.loads(
            (self.cache_dir / "translations.json").read_text()
        )
        self.assertEqual(len(records), 3)

    def test_low_credit_mode_runs_languages_sequentially(self):
        result = self.execute(
            self.switcher(
                ("English", "Yoruba", "Korean", "Spanish"),
                parallel_languages=False,
            )
        )

        self.assertTrue(result.ok)
        self.assertFalse(
            result.generation.condition["parallel_languages"]
        )


if __name__ == "__main__":
    unittest.main()
