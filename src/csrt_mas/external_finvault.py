"""Import reviewed external records into the existing FinVault case format.

The adapter is deliberately deterministic. It does not translate prompts, call a
model, or infer whether a record is safe. Input records must contain a reviewed
matched pair and synthetic fixture identifiers.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SURFACES = ("EN", "KO", "CS")
PROPERTY_BY_CATEGORY = {
    "unauthorized_information_access": "V4_privacy_breach",
    "privacy_breach": "V4_privacy_breach",
    "unauthorized_transaction": "V1_limit_bypass",
    "policy_bypass": "V2_blacklist_bypass",
    "document_fraud": "V3_fake_document",
}
SYNTHETIC_ID = re.compile(r"^(?:PERSON|ORGANIZATION|DOC|CASE|SWIFT)-[A-Z0-9-]+$|^\d{18}$")
REQUIRED_FIXTURE = {
    "customer_name",
    "current_id",
    "target_id",
    "requested_amount",
    "monthly_income",
    "credit_score",
    "risk_level",
    "document_status",
    "valid_document_id",
    "query_subject_id",
}


class AdapterError(ValueError):
    """Raised when an external record cannot be safely normalized."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise AdapterError(f"line {line_number} must contain a JSON object")
        rows.append(value)
    return rows


def _source_texts(record: dict[str, Any], label: str) -> dict[str, str]:
    value = record.get(label)
    if isinstance(value, str):
        return {"EN": value}
    if not isinstance(value, dict):
        raise AdapterError(f"{label} must be a string or surface map")
    texts = {str(key).upper(): str(text) for key, text in value.items()}
    if not texts or any(not text.strip() for text in texts.values()):
        raise AdapterError(f"{label} contains an empty language form")
    unknown = set(texts) - set(SUPPORTED_SURFACES)
    if unknown:
        raise AdapterError(f"unsupported FinVault surfaces: {sorted(unknown)}")
    missing = set(SUPPORTED_SURFACES) - set(texts)
    if missing:
        raise AdapterError(f"{label} is missing reviewed surfaces: {sorted(missing)}")
    return texts


def _fixture(record: dict[str, Any], intent: str) -> dict[str, Any]:
    value = record.get("fixture")
    if not isinstance(value, dict):
        raise AdapterError("fixture is required; external personal data is never copied automatically")
    missing = REQUIRED_FIXTURE - set(value)
    if missing:
        raise AdapterError(f"fixture is missing fields: {sorted(missing)}")
    result = {key: value[key] for key in REQUIRED_FIXTURE}
    for key in ("customer_name", "current_id", "target_id", "valid_document_id", "query_subject_id"):
        if not isinstance(result[key], str) or not SYNTHETIC_ID.fullmatch(result[key]):
            raise AdapterError(f"fixture.{key} must be a synthetic FinVault identifier")
    expected_subject = result["target_id"] if intent == "adversarial" else result["current_id"]
    if intent == "adversarial" and result["target_id"] == result["current_id"]:
        raise AdapterError("adversarial information-access fixtures must target a different subject")
    result["query_subject_id"] = expected_subject
    return result


def _property(record: dict[str, Any]) -> str:
    explicit = record.get("property_id")
    category = str(record.get("risk_category", "")).strip().lower()
    property_id = str(explicit or PROPERTY_BY_CATEGORY.get(category, ""))
    if property_id not in {"V1_limit_bypass", "V2_blacklist_bypass", "V3_fake_document", "V4_privacy_breach"}:
        raise AdapterError(f"unsupported FinVault risk/property: {explicit or category}")
    return property_id


def _normalize_pair(record: dict[str, Any], source: dict[str, str], index: int) -> list[dict[str, Any]]:
    record_id = str(record.get("record_id") or record.get("id") or "").strip()
    if not record_id:
        raise AdapterError(f"record {index} has no record_id")
    pair_id = f"external:{source['dataset']}:{record_id}"
    property_id = _property(record)
    output: list[dict[str, Any]] = []
    for intent, field in (("adversarial", "adversarial"), ("benign", "benign")):
        texts = _source_texts(record, field)
        fixture = _fixture(record, intent)
        text_hashes = {surface: _sha256(text) for surface, text in texts.items()}
        output.append(
            {
                "semantic_id": f"{pair_id}:{intent}",
                "pair_id": pair_id,
                "property_id": property_id,
                "frame": str(record.get("frame") or "external_dataset"),
                "intent": intent,
                "source_id": record_id,
                "source_path": source["url"],
                "source_sha256": source["sha256"],
                "source_dataset": source["dataset"],
                "source_version": source["version"],
                "source_license": source["license"],
                "language_review": record.get("language_review", "not_recorded"),
                "texts": texts,
                "text_sha256": text_hashes,
                "fixture": {**fixture, "source_id": record_id, "property_id": property_id, "intent": intent},
            }
        )
    return output


def import_finvault_jsonl(
    input_path: Path,
    output_path: Path,
    *,
    dataset: str,
    version: str,
    url: str,
    license_name: str,
) -> dict[str, Any]:
    """Normalize reviewed pair records into FinVault's case JSONL format."""
    source_bytes = input_path.read_bytes()
    source = {
        "dataset": dataset,
        "version": version,
        "url": url,
        "license": license_name,
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(_read_jsonl(input_path), 1):
        normalized = _normalize_pair(record, source, index)
        pair_id = normalized[0]["pair_id"]
        if pair_id in seen:
            raise AdapterError(f"duplicate pair: {pair_id}")
        seen.add(pair_id)
        rows.extend(normalized)
    if not rows:
        raise AdapterError("input contains no records")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "input": str(input_path),
        "output": str(output_path),
        "dataset": dataset,
        "version": version,
        "source_sha256": source["sha256"],
        "pairs": len(seen),
        "semantic_rows": len(rows),
        "surfaces": list(SUPPORTED_SURFACES),
    }
