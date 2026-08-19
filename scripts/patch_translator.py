#!/usr/bin/env python3
"""Add batched back-translation and a cheap verification tier to translator.py.

Written as anchored replacements rather than a whole-file overwrite: the file
differs between machines, and every anchor below is asserted to occur exactly
once before anything is written. If any anchor has moved, nothing changes and
the script says which one.

    python3 scripts/patch_translator.py            # apply
    python3 scripts/patch_translator.py --check    # report only

Re-running is safe: an already-patched file is detected and left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "csrt_codeswitch" / "translator.py"

MARKER = "def translate_many("

# --- 1. a cheap tier for calls whose output never reaches the dataset --------

ANCHOR_MODEL = 'DEFAULT_TRANSLATION_MODEL = "gpt-5.6-sol"\n'
REPLACE_MODEL = (
    'DEFAULT_TRANSLATION_MODEL = "gpt-5.6-sol"\n'
    '\n'
    '# Used for back-translation, which exists to detect drift and whose output\n'
    '# never reaches the dataset. Sol is $5/$30 per million; Luna is $1/$6, and\n'
    '# output is where the money goes because reasoning tokens bill at the\n'
    '# output rate. Forward translation stays on the default.\n'
    'DEFAULT_VERIFICATION_MODEL = "gpt-5.6-luna"\n'
)

# --- 2. reasoning effort becomes per-instance --------------------------------

ANCHOR_INIT = (
    "        model: str = DEFAULT_TRANSLATION_MODEL,\n"
    "        client: Any | None = None,\n"
    "        timeout: float = 180,\n"
    "    ) -> None:\n"
    "        self._model = model\n"
    "        self._backend_name = f\"openai-{model}\"\n"
    "        self._client = client\n"
    "        self._timeout = timeout\n"
)
REPLACE_INIT = (
    "        model: str = DEFAULT_TRANSLATION_MODEL,\n"
    "        client: Any | None = None,\n"
    "        timeout: float = 180,\n"
    "        reasoning_effort: str = \"low\",\n"
    "    ) -> None:\n"
    "        self._model = model\n"
    "        self._backend_name = f\"openai-{model}\"\n"
    "        self._client = client\n"
    "        self._timeout = timeout\n"
    "        self._effort = reasoning_effort\n"
)

ANCHOR_EFFORT = '            reasoning={"effort": "low"},\n'
REPLACE_EFFORT = '            reasoning={"effort": self._effort},\n'

# --- 3. the batch call -------------------------------------------------------

ANCHOR_TAIL = (
    "            backend=self._backend_name,\n"
    "        )\n"
)
BATCH = '''
    def _request_batch(
        self,
        texts: list[str],
        *,
        source_language: str,
        target_language: str,
    ) -> list[str]:
        """Translate several fragments in one request, order preserved."""
        numbered = "\\n".join(
            f"{position}. {text}" for position, text in enumerate(texts, 1)
        )
        response = self._get_client().responses.create(
            model=self._model,
            instructions=(
                "You are a professional contextual translator. You will be given "
                "numbered fragments of a longer text. Translate each fragment "
                "independently, preserving its operational meaning rather than "
                "translating technical terms literally. Preserve actors, actions, "
                "departments, permissions, negation, modality, identifiers, "
                "numbers, and conditions exactly. A fragment may be a single word "
                "or a partial clause; translate it as it stands and do not merge, "
                "split, reorder or drop any fragment. Do not add explanations. "
                'Return only JSON: {"translations":["...","..."]}, with exactly '
                "one entry per input fragment, in the same order."
            ),
            input=(
                f"Source language: {source_language}\\n"
                f"Target language: {target_language}\\n"
                f"Fragment count: {len(texts)}\\n\\n"
                f"FRAGMENTS\\n{numbered}\\n\\n"
                'Output a JSON object with the key "translations": an array of '
                f"exactly {len(texts)} strings, in the order given."
            ),
            reasoning={"effort": self._effort},
            text={"format": {"type": "json_object"}},
            max_output_tokens=4096,
            store=False,
        )

        return self._parse_batch_response(response.output_text)

    @staticmethod
    def _parse_batch_response(output: str) -> list[str]:
        output = output.strip()

        if not output:
            raise TranslationError("OpenAI returned no batch translation")

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise TranslationError(
                "OpenAI returned invalid batch translation JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise TranslationError(
                "OpenAI batch translation response must be a JSON object"
            )

        translations = payload.get("translations")

        if not isinstance(translations, list):
            raise TranslationError(
                "OpenAI batch translation response has no translations array"
            )

        cleaned = []
        for position, item in enumerate(translations, 1):
            if not isinstance(item, str) or not item.strip():
                raise TranslationError(
                    f"batch translation entry {position} is empty or not a string"
                )
            cleaned.append(item.strip())

        return cleaned

    def translate_many(
        self,
        texts: list[str],
        *,
        target_language: str,
        source_language: str = "English",
    ) -> BatchTranslationResult:
        """Translate a list of fragments in a single request.

        The caller is responsible for checking that the result has as many
        entries as it asked for; this method does not pad or truncate, because
        a silently shortened list would misalign every fragment after the gap.
        """
        if not texts:
            raise ValueError("batch translation needs at least one fragment")

        for text in texts:
            self._validate_request(text, source_language, target_language)

        try:
            translated = self._request_batch(
                [text.strip() for text in texts],
                source_language=source_language.strip(),
                target_language=target_language.strip(),
            )
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(
                f"{self._backend_name} batch translation failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        return BatchTranslationResult(
            source_texts=tuple(text.strip() for text in texts),
            translated_texts=tuple(translated),
            source_language=source_language.strip(),
            target_language=target_language.strip(),
            backend=self._backend_name,
        )
'''

BATCH_RESULT = '''

@dataclass(frozen=True)
class BatchTranslationResult:
    source_texts: tuple[str, ...]
    translated_texts: tuple[str, ...]
    source_language: str
    target_language: str
    backend: str
'''


def apply(text: str) -> str:
    steps = [
        ("model constant", ANCHOR_MODEL, REPLACE_MODEL),
        ("constructor", ANCHOR_INIT, REPLACE_INIT),
        ("reasoning effort", ANCHOR_EFFORT, REPLACE_EFFORT),
        ("end of translate()", ANCHOR_TAIL, ANCHOR_TAIL + BATCH),
    ]
    for label, anchor, replacement in steps:
        found = text.count(anchor)
        if found != 1:
            raise SystemExit(
                f"anchor '{label}' occurs {found} times, expected exactly 1. "
                "Nothing was written."
            )
        text = text.replace(anchor, replacement)
    return text.rstrip("\n") + "\n" + BATCH_RESULT


def main() -> int:
    check_only = "--check" in sys.argv
    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        print(f"{TARGET.name} already patched; nothing to do.")
        return 0

    patched = apply(text)

    if check_only:
        print(f"{TARGET.name} would go from {len(text)} to {len(patched)} bytes.")
        return 0

    TARGET.write_text(patched, encoding="utf-8")
    print(f"patched {TARGET} ({len(text)} -> {len(patched)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
