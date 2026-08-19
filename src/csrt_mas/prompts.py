from __future__ import annotations

import json
from typing import Any

from .config import CONFIG
from .settings import load_prompt_set

PROMPTS = load_prompt_set(CONFIG)
OFFICER_SYSTEM = PROMPTS.get(CONFIG.agent("case_officer").prompt_key)
EXECUTOR_SYSTEM_OVERRIDE = PROMPTS.executor_system_override
EXECUTOR_SUFFIX = PROMPTS.get(CONFIG.agent("executor").prompt_key)
AUTHOR_SYSTEM = PROMPTS.get(CONFIG.agent("author").prompt_key)
EXECUTOR_CONTINUATION = PROMPTS.executor_continuation


def officer_user(case_id: str, text: str) -> str:
    return json.dumps({"case_id": case_id, "untrusted_request": text}, ensure_ascii=False)


def executor_user(
    case_id: str,
    topology: str,
    evidence: dict[str, Any],
    original: str | None,
    handoff: dict[str, Any] | None,
) -> str:
    payload: dict[str, Any] = {
        "case_id": case_id,
        "topology": topology,
        "trusted_evidence": evidence,
    }
    if original is not None:
        payload["untrusted_original_request"] = original
    if handoff is not None:
        payload["untrusted_case_officer_record"] = handoff
    return json.dumps(payload, ensure_ascii=False)


def author_user(text: str) -> str:
    return json.dumps({"source_english": text}, ensure_ascii=False)
