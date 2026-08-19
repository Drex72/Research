"""Code-switching as a standalone, pluggable module.

Give it a prompt and a condition; it returns a code-switched prompt.

    from csrt_codeswitch import CodeSwitcher

    sw = CodeSwitcher(["English", "Yoruba"], granularity="clause", generate=my_model)
    result = sw.switch("Please approve loan SWIFT-000001 for 300,000.")
    print(result.text if result.ok else result.problems)

It has no dependency on the experiment runner, the scenario layer, or any
particular model client, so the experiment can plug it in and so can a
notebook. A condition is constructor arguments, not a file: languages, their
order, their shares, the switching granularity, the semantic-role allocation,
the tag categories and the switch rate. Adding a language is one entry in
``languages.json`` next to this file.
"""

from __future__ import annotations

from .switcher import (
    GRANULARITIES,
    SEMANTIC_ROLES,
    TAG_CATEGORIES,
    CodeSwitcher,
    CodeSwitchError,
    Language,
    LanguageEvidence,
    Result,
    count_languages,
    load_languages,
    protected_tokens,
)
from .validation import (
    BackTranslatedSegment,
    BackTranslationValidator,
    SemanticValidation,
    SentenceTransformerScorer,
    SwitchResult,
)

from .translator import (
    TranslationError,
    TranslationResult,
)

__all__ = [
    "GRANULARITIES",
    "SEMANTIC_ROLES",
    "TAG_CATEGORIES",
    "CodeSwitchError",
    "CodeSwitcher",
    "Language",
    "LanguageEvidence",
    "Result",
    "count_languages",
    "load_languages",
    "protected_tokens",
    "TranslationError",
    "TranslationResult",
    "BackTranslatedSegment",
    "BackTranslationValidator",
    "SemanticValidation",
    "SentenceTransformerScorer",
    "SwitchResult",
]
