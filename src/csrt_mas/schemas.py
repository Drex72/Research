from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import CONFIG

class SchemaError(ValueError):
    pass


RISK_LABELS = {"BENIGN", "RESTRICTED", "UNCERTAIN"}
RECOMMENDATIONS = {"ALLOW", "DENY", "ESCALATE"}
OPERATIONS = {"APPROVE", "REJECT", "QUERY", "VERIFY", "ESCALATE", "OTHER"}
# A model that wants to decline had no way to say so: the enum listed only real
# tools, so refusal had to be expressed as whichever action looked least bad,
# and was then scored as that action. Refusing is a distinct outcome and needs
# its own name. It is not a sandbox tool; the adapter treats it as a no-op and
# the run ends.
REFUSAL_TOOL = "refuse_to_act"

TOOLS = set(CONFIG.agent("executor").tools) | {REFUSAL_TOOL}


OFFICER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "case_id": {"type": "string"},
        "risk_label": {"type": "string", "enum": sorted(RISK_LABELS)},
        "requested_operation": {"type": "string", "enum": sorted(OPERATIONS)},
        "recommended_action": {"type": "string", "enum": sorted(RECOMMENDATIONS)},
        "normalized_summary": {"type": "string", "maxLength": 600},
    },
    "required": [
        "case_id",
        "risk_label",
        "requested_operation",
        "recommended_action",
        "normalized_summary",
    ],
    "additionalProperties": False,
}

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {"type": "string", "enum": sorted(TOOLS)},
        "args": {"type": "object"},
    },
    "required": ["tool", "args"],
    "additionalProperties": False,
}

AUTHOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ko": {"type": "string"},
        "cs": {"type": "string"},
    },
    "required": ["ko", "cs"],
    "additionalProperties": False,
}


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise SchemaError("response must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    actual = set(value)
    if actual != expected:
        raise SchemaError(f"unexpected keys: {sorted(actual ^ expected)}")


def validate_officer(value: dict[str, Any], expected_case_id: str) -> dict[str, Any]:
    keys = {
        "case_id",
        "risk_label",
        "requested_operation",
        "recommended_action",
        "normalized_summary",
    }
    _exact_keys(value, keys)
    if value["case_id"] != expected_case_id:
        raise SchemaError("case_id mismatch")
    if value["risk_label"] not in RISK_LABELS:
        raise SchemaError("invalid risk_label")
    if value["requested_operation"] not in OPERATIONS:
        raise SchemaError("invalid requested_operation")
    if value["recommended_action"] not in RECOMMENDATIONS:
        raise SchemaError("invalid recommended_action")
    if not isinstance(value["normalized_summary"], str) or len(value["normalized_summary"]) > 600:
        raise SchemaError("invalid normalized_summary")
    return value


def validate_action(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"tool", "args"})
    if value["tool"] not in TOOLS:
        raise SchemaError("unknown tool")
    if not isinstance(value["args"], dict):
        raise SchemaError("args must be an object")
    return value


def validate_author(value: dict[str, Any]) -> dict[str, str]:
    _exact_keys(value, {"ko", "cs"})
    if not all(isinstance(value[k], str) and value[k].strip() for k in ("ko", "cs")):
        raise SchemaError("language forms must be non-empty strings")
    return {"ko": value["ko"], "cs": value["cs"]}


@dataclass(frozen=True)
class ModelReply:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_duration_ns: int
