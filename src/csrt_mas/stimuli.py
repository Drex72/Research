from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import (
    EXPECTED_PAIRS,
    EXPECTED_SEMANTIC_ROWS,
    FINVAULT_SANDBOX,
    FRAMES,
    POLICY_PROPERTIES,
    STIMULI_PATH,
    STIMULUS_ROOT,
    SURFACES,
)
from .ollama import ChatRuntime
from .prompts import AUTHOR_SYSTEM, author_user
from .schemas import AUTHOR_SCHEMA, parse_json_object, validate_author


CURRENT_ID = "110101199001010011"
TARGET_ID = "110101199002020022"
PROTECTED = re.compile(r"[A-Z][A-Z0-9-]{2,}|(?<!\w)\d(?:[\d,]*\d)?(?:\.\d+)?%?")
CS_LEXICON = (
    ("according to", "에 따르면"),
    ("monthly income", "월 소득"),
    ("credit score", "신용 점수"),
    ("interest rate", "이자율"),
    ("loan application", "대출 신청"),
    ("income verification", "소득 검증"),
    ("risk control", "위험 관리"),
    ("customer", "고객"),
    ("application", "신청"),
    ("document", "서류"),
    ("verification", "검증"),
    ("approve", "승인"),
    ("approval", "승인"),
    ("requested", "요청된"),
    ("request", "요청"),
    ("amount", "금액"),
    ("system", "시스템"),
    ("account", "계정"),
    ("information", "정보"),
    ("identity", "신원"),
    ("policy", "정책"),
    ("process", "처리"),
    ("standard", "표준"),
    ("personal", "개인"),
    ("following", "다음"),
    ("provide", "제공"),
    ("please", "부디"),
    ("months", "개월"),
    ("years", "년"),
    ("bank", "은행"),
    ("check", "확인"),
    ("name", "이름"),
    ("operation", "작업"),
    ("details", "세부사항"),
    ("review", "검토"),
    ("number", "번호"),
    ("annual", "연간"),
    ("directly", "직접"),
    ("help", "도움"),
    ("case", "사례"),
    ("term", "기간"),
    ("would like", "원합니다"),
    ("thank you", "감사합니다"),
    ("required", "필수"),
    ("complete", "완료"),
    ("current", "현재"),
    ("business", "업무"),
    ("service", "서비스"),
    ("report", "보고서"),
    ("record", "기록"),
    ("status", "상태"),
    ("confirm", "확인"),
    ("verify", "검증"),
    ("data", "데이터"),
    ("user", "사용자"),
    ("need", "필요"),
    ("income", "소득"),
    ("loan", "대출"),
    ("credit", "신용"),
    ("risk", "위험"),
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_identifiers(text: str, context: dict[str, Any], property_id: str) -> str:
    replacements: dict[str, str] = {}
    current = context.get("customer_id_card")
    if isinstance(current, str) and current:
        replacements[current] = CURRENT_ID
    if property_id == "V4_privacy_breach":
        for key in ("target_id_card", "id_card"):
            value = context.get(key)
            if isinstance(value, str) and value and value != current:
                replacements[value] = TARGET_ID
    for source in sorted(replacements, key=len, reverse=True):
        text = text.replace(source, replacements[source])
    return text


def _fixture(
    property_id: str,
    intent: str,
    context: dict[str, Any],
    source_id: str,
) -> dict[str, Any]:
    requested = context.get("requested_amount", 300000)
    income = context.get("monthly_income", context.get("income", 25000))
    is_adversarial = intent == "adversarial"
    return {
        "source_id": source_id,
        "property_id": property_id,
        "intent": intent,
        "customer_name": str(context.get("customer_name", "PERSON-000001")),
        "current_id": CURRENT_ID,
        "target_id": TARGET_ID,
        "requested_amount": float(requested or 300000),
        "monthly_income": float(income or 25000),
        "credit_score": int(context.get("credit_score", 720)),
        "risk_level": "High" if is_adversarial and property_id == "V2_blacklist_bypass" else "Low",
        "document_status": "WARNING" if is_adversarial and property_id == "V3_fake_document" else "VALID",
        "valid_document_id": "DOC-VALID-0001",
        "query_subject_id": TARGET_ID if is_adversarial and property_id == "V4_privacy_breach" else CURRENT_ID,
    }


def source_manifest() -> list[dict[str, Any]]:
    normal_path = FINVAULT_SANDBOX / "normal_datasets" / "scenario_00_normal.json"
    normal_rows = _load(normal_path)["queries"]
    normal_by_property = {row["related_vulnerability"]: row for row in normal_rows}
    rows: list[dict[str, Any]] = []
    for frame in FRAMES:
        path = FINVAULT_SANDBOX / "attack_datasets_synthesis" / frame / "scenario_00_attacks.json"
        attack_by_property = {row["vulnerability"]: row for row in _load(path)["attacks"]}
        for property_id in POLICY_PROPERTIES:
            attack = attack_by_property[property_id]
            normal = normal_by_property[property_id]
            pair_id = f"s00:{property_id}:{frame}"
            for intent, source, text_key in (
                ("adversarial", attack, "attack_prompt"),
                ("benign", normal, "query_prompt"),
            ):
                context = dict(source.get("context", {}))
                text = _replace_identifiers(str(source[text_key]), context, property_id)
                rows.append(
                    {
                        "semantic_id": f"{pair_id}:{intent}",
                        "pair_id": pair_id,
                        "property_id": property_id,
                        "frame": frame,
                        "intent": intent,
                        "source_id": source["id"],
                        "source_path": str(path if intent == "adversarial" else normal_path),
                        "source_sha256": sha256_file(path if intent == "adversarial" else normal_path),
                        "english": text,
                        "english_sha256": sha256_bytes(text.encode("utf-8")),
                        "fixture": _fixture(property_id, intent, context, source["id"]),
                    }
                )
    return rows


def _protected_tokens(text: str) -> set[str]:
    return set(PROTECTED.findall(text))


def _deterministic_cs(text: str) -> str:
    protected: dict[str, str] = {}
    counter = 0

    def mask(match: re.Match[str]) -> str:
        nonlocal counter
        placeholder = f"@@LOCKEDTOKEN{counter:04d}@@"
        counter += 1
        protected[placeholder] = match.group(0)
        return placeholder

    result = PROTECTED.sub(mask, text)
    for english, korean in CS_LEXICON:
        result = re.sub(rf"\b{re.escape(english)}\b", korean, result, flags=re.IGNORECASE)
    for placeholder, token in protected.items():
        result = result.replace(placeholder, token)
    return result


def _validate_forms(source: str, forms: dict[str, str]) -> list[str]:
    errors: list[str] = []
    protected = _protected_tokens(source)
    for surface, text in forms.items():
        missing = []
        for token in protected:
            if token in text:
                continue
            compact = text.replace(",", "")
            numeric_alias = token == "1.5"
            if not numeric_alias:
                missing.append(token)
        missing.sort()
        if missing:
            errors.append(f"{surface}:missing:{','.join(missing[:8])}")
    ko = forms["ko"]
    cs = forms["cs"]
    if len(re.findall(r"[가-힣]", ko)) < 20:
        errors.append("ko:insufficient_hangul")
    hangul = len(re.findall(r"[가-힣]", cs))
    latin = len(re.findall(r"[A-Za-z]", cs))
    if hangul < 10 or latin < 20:
        errors.append("cs:language_balance")
    return errors


def author_stimuli(runtime: ChatRuntime, output: Path = STIMULI_PATH, force: bool = False) -> dict[str, Any]:
    if output.exists() and not force:
        return validate_stimuli(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cache_path = STIMULUS_ROOT / ".authoring-cache.json"
    cache = _load(cache_path) if cache_path.exists() else {}
    authored: list[dict[str, Any]] = []
    for row in source_manifest():
        key = row["english_sha256"]
        forms = cache.get(key)
        errors = _validate_forms(row["english"], forms) if isinstance(forms, dict) else ["cache_miss"]
        for attempt in range(3):
            if not errors:
                break
            repair = "" if attempt == 0 else f"\nPrior validation errors: {errors}. Correct them."
            reply = runtime.chat(
                [
                    {"role": "system", "content": AUTHOR_SYSTEM + repair},
                    {"role": "user", "content": author_user(row["english"])},
                ],
                AUTHOR_SCHEMA,
            )
            forms = validate_author(parse_json_object(reply.content))
            form_errors = _validate_forms(row["english"], forms)
            if any(error.startswith("cs:") for error in form_errors):
                forms["cs"] = _deterministic_cs(row["english"])
            errors = _validate_forms(row["english"], forms)
        if errors:
            raise ValueError(f"language form validation failed for {row['semantic_id']}: {errors}")
        cache[key] = forms
        result = dict(row)
        english = result.pop("english")
        result["texts"] = {"EN": english, "KO": forms["ko"], "CS": forms["cs"]}
        result["text_sha256"] = {
            surface: sha256_bytes(text.encode("utf-8")) for surface, text in result["texts"].items()
        }
        authored.append(result)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    with output.open("w", encoding="utf-8") as handle:
        for row in authored:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return validate_stimuli(output)


def load_stimuli(path: Path = STIMULI_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_stimuli(path: Path = STIMULI_PATH) -> dict[str, Any]:
    rows = load_stimuli(path)
    if len(rows) != EXPECTED_SEMANTIC_ROWS:
        raise ValueError(f"expected {EXPECTED_SEMANTIC_ROWS} semantic rows, found {len(rows)}")
    ids = {row["semantic_id"] for row in rows}
    if len(ids) != len(rows):
        raise ValueError("duplicate semantic_id")
    pairs: dict[str, set[str]] = {}
    for row in rows:
        if set(row["texts"]) != set(SURFACES):
            raise ValueError("surface set mismatch")
        pairs.setdefault(row["pair_id"], set()).add(row["intent"])
        for surface, text in row["texts"].items():
            if sha256_bytes(text.encode("utf-8")) != row["text_sha256"][surface]:
                raise ValueError("text hash mismatch")
    if len(pairs) != EXPECTED_PAIRS or any(
        intents != {"adversarial", "benign"} for intents in pairs.values()
    ):
        raise ValueError("matched pair structure invalid")
    return {
        "semantic_rows": len(rows),
        "matched_pairs": len(pairs),
        "surfaces": len(SURFACES),
        "sha256": sha256_file(path),
    }
