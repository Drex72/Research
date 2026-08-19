"""Readable terminal presentation for code-switching results."""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from collections import Counter
from collections.abc import Mapping
from typing import Any

from csrt_codeswitch import Result, protected_tokens


_COLORS = (36, 35, 33, 32, 34, 31)


def _paint(value: str, code: int, enabled: bool) -> str:
    return f"\033[1;{code}m{value}\033[0m" if enabled else value


def _wrap(value: str, width: int, indent: str = "   ") -> list[str]:
    return textwrap.wrap(
        " ".join(value.split()) or "(empty)",
        width=max(30, width - len(indent)),
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _token_audit(source: str, output: str) -> tuple[list[str], list[str], list[str]]:
    expected = protected_tokens(source)
    observed = protected_tokens(output)
    missing = sorted(expected - observed)
    added = sorted(observed - expected)
    duplicates = sorted(
        token for token in expected if output.count(token) > source.count(token)
    )
    return missing, added, duplicates


def format_result(
    label: str,
    source: str,
    result: Result,
    *,
    width: int | None = None,
    color: bool | None = None,
) -> str:
    """Return a source-versus-segments view suitable for a terminal or log."""
    width = width or min(max(shutil.get_terminal_size((100, 24)).columns, 76), 120)
    color = (
        sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        if color is None
        else color
    )
    # Result.ok covers structural checks only. Meaning equivalence belongs to
    # the semantic and bilingual-review gates in CodeSwitcher.
    status = "STRUCTURAL PASS" if result.ok else "STRUCTURAL FAIL"
    status_code = 32 if result.ok else 31
    lines = [
        "",
        "┌" + "─" * (width - 2) + "┐",
        f"  {label}  {_paint(status, status_code, color)}"
        f"  ·  {result.attempts} generation attempt(s)",
    ]

    condition = result.condition
    if condition:
        route = " → ".join(str(item) for item in condition.get("order", ()))
        lines.append(
            f"  Condition: {condition.get('granularity', '?')} units"
            f"  ·  language order {route or '?'}"
            f"  ·  matrix {condition.get('matrix', '?')}"
        )

    lines.extend(["├" + "─" * (width - 2) + "┤", "  SOURCE"])
    lines.extend(_wrap(source, width))

    if result.segments:
        lines.append("  OUTPUT BY SWITCHING UNIT")
        palette: dict[str, int] = {}
        path: list[str] = []
        for index, segment in enumerate(result.segments, 1):
            language = str(segment.get("language", "?"))
            if language not in palette:
                palette[language] = _COLORS[len(palette) % len(_COLORS)]
            path.append(language)
            unit = str(segment.get("unit", "?"))
            details = [unit]
            for key in ("role", "tag_category"):
                if segment.get(key):
                    details.append(str(segment[key]))
            verdict = str(segment.get("language_verdict", ""))
            if verdict:
                detected = str(segment.get("detected_language", ""))
                confidence = str(segment.get("language_confidence", ""))
                language_detail = f"language {verdict}"
                if detected:
                    language_detail += f": {detected} {confidence}"
                details.append(language_detail)
            marker = _paint(language.upper(), palette[language], color)
            lines.append(f"  {index:02d}  {marker:<12} {' · '.join(details)}")
            lines.extend(_wrap(str(segment.get("text", "")), width, "      "))
        compressed_path = [name for pos, name in enumerate(path) if pos == 0 or name != path[pos - 1]]
        lines.append("  SWITCH PATH: " + " → ".join(compressed_path))
    else:
        lines.append("  OUTPUT")
        lines.extend(_wrap(result.text, width))

    expected = Counter(protected_tokens(source))
    missing, added, duplicated = _token_audit(source, result.text)
    normalized_source = " ".join(source.casefold().split())
    normalized_output = " ".join(result.text.casefold().split())
    copied = bool(normalized_source and normalized_source in normalized_output)
    preserved = not missing and not added and not duplicated
    lines.extend(
        [
            "  QUICK AUDIT",
            f"   • language evidence: {dict(result.languages)}",
            f"   • full source copied unchanged: {'YES' if copied else 'no'}",
            f"   • protected values: {'preserved' if preserved else 'FAILED'}"
            f" ({len(expected)} expected)",
        ]
    )
    if missing:
        lines.append(f"   • missing: {', '.join(missing)}")
    if added:
        lines.append(f"   • invented: {', '.join(added)}")
    if duplicated:
        lines.append(f"   • duplicated: {', '.join(duplicated)}")
        lines.append(
            "   • interpretation: the same case facts appear in more than one "
            "unit, indicating parallel repetition rather than one mixed rewrite"
        )

    if result.problems:
        lines.append("  WHY IT WAS REJECTED")
        lines.extend(f"   ✗ {problem}" for problem in result.problems)
    elif result.ok:
        lines.append(
            "  DECISION: structural checks passed; semantic validation and "
            "bilingual review still required"
        )
    lines.append("└" + "─" * (width - 2) + "┘")
    return "\n".join(lines)


def print_result(label: str, source: str, result: Result) -> None:
    print(format_result(label, source, result))
