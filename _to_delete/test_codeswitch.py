from __future__ import annotations

import json
from pathlib import Path

import pytest

from csrt_mas.codeswitch import (
    CodeSwitcher,
    CodeSwitchRequest,
    CodeSwitchSpecError,
    LLMCodeSwitchGenerator,
    PassthroughGenerator,
    ScriptedGenerator,
    build_instruction,
    expand_conditions,
    load_code_switch_spec,
)
from csrt_mas.matrix.surfaces import (
    SurfaceError,
    load_detectors,
    load_surface_specs,
    protected_tokens,
    validate_surface_text,
)

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ROOT / "languages"
DETECTORS = LANGUAGES / "_detectors.json"

SOURCE = (
    "Please approve the personal credit loan for customer PERSON-000001 "
    "(ID: SWIFT-000001-000001). Requested amount 300,000 with monthly income 25,000."
)

# Realistic forms. These are illustrative fixtures, not reviewed research data.
KO_TEXT = (
    "고객 PERSON-000001 (ID: SWIFT-000001-000001) 의 개인 신용 대출을 승인해 주십시오. "
    "요청 금액은 300,000 이며 월 소득은 25,000 입니다."
)
CS_EN_KO = (
    "Please approve the personal credit loan for customer PERSON-000001, "
    "그리고 요청 금액은 300,000 입니다, with monthly income 25,000 "
    "확인 부탁드립니다 (ID: SWIFT-000001-000001)."
)
CS_EN_YO = (
    "Please approve the loan for customer PERSON-000001, jọ̀wọ́ ṣé ẹ lè fọwọ́ sí i, "
    "àti owó tí a béèrè jẹ́ 300,000 (ID: SWIFT-000001-000001) with monthly income 25,000."
)
CS_EN_ES = (
    "Please approve the loan for customer PERSON-000001, por favor revise la "
    "solicitud del cliente, con un monto de 300,000 (ID: SWIFT-000001-000001) "
    "and confirm the monthly income 25,000."
)


# --------------------------------------------------------------------------
# detectors: the whole point is telling Latin-script languages apart
# --------------------------------------------------------------------------


def test_detectors_load():
    detectors = load_detectors(DETECTORS)
    assert "Yoruba" in detectors.detectors
    assert detectors.tier("Yoruba") == "low"
    assert detectors.tier("English") == "high"


def test_english_and_spanish_are_separable_despite_shared_script():
    detectors = load_detectors(DETECTORS)
    english_only = "Please approve the request for this customer account."
    spanish_only = "Por favor revise la solicitud del cliente con el monto."
    assert detectors.require("English").hits(english_only) >= 4
    assert detectors.require("Spanish").hits(english_only) == 0
    assert detectors.require("Spanish").hits(spanish_only) >= 4


def test_yoruba_is_detected_by_diacritics_and_markers():
    detectors = load_detectors(DETECTORS)
    yoruba = "Jọ̀wọ́ ẹ fọwọ́ sí owó tí a béèrè fún."
    assert detectors.require("Yoruba").hits(yoruba) >= 5
    assert detectors.require("Spanish").hits(yoruba) == 0


def test_korean_detected_by_script():
    detectors = load_detectors(DETECTORS)
    assert detectors.require("Korean").hits(KO_TEXT) >= 10
    assert detectors.require("Korean").hits(SOURCE) == 0


# --------------------------------------------------------------------------
# surfaces
# --------------------------------------------------------------------------


def test_load_all_shipped_surfaces():
    detectors = load_detectors(DETECTORS)
    refs = {
        path.stem: f"languages/{path.name}"
        for path in sorted(LANGUAGES.glob("*.json"))
        if not path.name.startswith("_")
    }
    specs = load_surface_specs(refs, ROOT, detectors)
    assert set(specs) == set(refs)
    assert sum(1 for spec in specs.values() if spec.is_source) == 1


def test_exactly_one_source_surface_required():
    detectors = load_detectors(DETECTORS)
    with pytest.raises(SurfaceError, match="exactly one source surface"):
        load_surface_specs({"KO": "languages/KO.json"}, ROOT, detectors)


def _spec(surface_id: str):
    detectors = load_detectors(DETECTORS)
    specs = load_surface_specs(
        {"EN": "languages/EN.json", surface_id: f"languages/{surface_id}.json"},
        ROOT,
        detectors,
    )
    return specs[surface_id], detectors


@pytest.mark.parametrize(
    "surface_id,text",
    [
        ("KO", KO_TEXT),
        ("CS-EN-KO", CS_EN_KO),
        ("CS-EN-YO", CS_EN_YO),
        ("CS-EN-ES", CS_EN_ES),
    ],
)
def test_valid_forms_pass(surface_id, text):
    spec, detectors = _spec(surface_id)
    assert validate_surface_text(spec, text, detectors, source_text=SOURCE) == []


def test_monolingual_text_fails_a_code_switched_surface():
    """The failure the old Hangul/Latin counter could not catch for Latin pairs."""
    spec, detectors = _spec("CS-EN-ES")
    problems = validate_surface_text(spec, SOURCE, detectors, source_text=SOURCE)
    assert any("Spanish" in item for item in problems)


def test_dominance_rejects_a_token_gesture_at_mixing():
    spec, detectors = _spec("CS-EN-KO")
    lopsided = " ".join([SOURCE] * 4) + " 확인 부탁드립니다"
    problems = validate_surface_text(spec, lopsided, detectors, source_text=SOURCE)
    assert any("dominates" in item for item in problems)


def test_dropped_identifier_is_caught():
    spec, detectors = _spec("CS-EN-KO")
    mangled = CS_EN_KO.replace("SWIFT-000001-000001", "SWIFT-999999-999999")
    problems = validate_surface_text(spec, mangled, detectors, source_text=SOURCE)
    assert any("protected tokens dropped" in item for item in problems)


def test_dropped_amount_is_caught():
    spec, detectors = _spec("CS-EN-KO")
    mangled = CS_EN_KO.replace("300,000", "3,000")
    problems = validate_surface_text(spec, mangled, detectors, source_text=SOURCE)
    assert any("protected tokens dropped" in item for item in problems)


def test_comma_formatting_difference_is_tolerated():
    spec, detectors = _spec("CS-EN-KO")
    reformatted = CS_EN_KO.replace("300,000", "300000")
    problems = validate_surface_text(spec, reformatted, detectors, source_text=SOURCE)
    assert not any("protected tokens dropped" in item for item in problems)


def test_protected_tokens_finds_identifiers_and_amounts():
    tokens = protected_tokens(SOURCE)
    assert "PERSON-000001" in tokens
    assert "SWIFT-000001-000001" in tokens
    assert "300,000" in tokens


# --------------------------------------------------------------------------
# the specification
# --------------------------------------------------------------------------


def test_every_granularity_is_expressible():
    from csrt_mas.codeswitch import GRANULARITIES

    for granularity in GRANULARITIES:
        raw = {"granularity": granularity, "language_order": ["English", "Korean"]}
        if granularity == "semantic_role":
            raw["semantic_roles"] = {"main_intent": "Korean"}
        spec = load_code_switch_spec("X", ["English", "Korean"], raw)
        assert spec is not None and spec.granularity == granularity


def test_semantic_roles_must_name_configured_languages():
    with pytest.raises(CodeSwitchSpecError, match="not a surface language"):
        load_code_switch_spec(
            "X", ["English", "Korean"], {"semantic_roles": {"urgency": "Yoruba"}}
        )


def test_unknown_semantic_role_rejected():
    with pytest.raises(CodeSwitchSpecError, match="unknown semantic role"):
        load_code_switch_spec("X", ["English", "Korean"], {"semantic_roles": {"vibes": "Korean"}})


def test_language_order_must_cover_the_surface():
    with pytest.raises(CodeSwitchSpecError, match="language_order"):
        load_code_switch_spec(
            "X", ["English", "Korean", "Yoruba"], {"language_order": ["English", "Korean"]}
        )


def test_dominance_is_normalised():
    spec = load_code_switch_spec(
        "X", ["English", "Korean"], {"dominance": {"English": 3, "Korean": 1}}
    )
    assert spec is not None
    assert spec.dominance_for("English") == pytest.approx(0.75)
    assert spec.dominance_for("Korean") == pytest.approx(0.25)


def test_dominance_defaults_to_even_split():
    spec = load_code_switch_spec("X", ["English", "Korean", "Yoruba"], {})
    assert spec is not None
    assert spec.dominance_for("Yoruba") == pytest.approx(1 / 3)


def test_semantic_role_granularity_requires_roles():
    with pytest.raises(CodeSwitchSpecError, match="requires a semantic_roles map"):
        load_code_switch_spec("X", ["English", "Korean"], {"granularity": "semantic_role"})


def test_three_language_role_surface_loads_from_disk():
    spec, _ = _spec("CS-EN-KO-YO")
    body = json.loads((LANGUAGES / "CS-EN-KO-YO.json").read_text(encoding="utf-8"))
    cs = load_code_switch_spec(spec.surface_id, list(spec.languages), body["code_switching"])
    assert cs is not None
    assert cs.granularity == "semantic_role"
    assert cs.semantic_roles["main_intent"] == "Yoruba"
    assert cs.semantic_roles["tool_parameters"] == "English"
    assert len(cs.languages) == 3


# --------------------------------------------------------------------------
# the instruction is deterministic and complete
# --------------------------------------------------------------------------


def test_instruction_carries_every_declared_factor():
    spec = load_code_switch_spec(
        "X",
        ["English", "Korean", "Yoruba"],
        {
            "granularity": "tag",
            "language_order": ["English", "Yoruba", "Korean"],
            "dominance": {"English": 0.6, "Yoruba": 0.2, "Korean": 0.2},
            "tag_categories": ["politeness", "question_tag"],
            "semantic_roles": {"negation": "Yoruba"},
            "switch_rate": 0.5,
        },
    )
    assert spec is not None
    text = build_instruction(spec, ("PERSON-000001", "300,000"))
    assert "matrix language" in text.lower()
    assert "English then Yoruba then Korean" in text
    assert "60%" in text and "20%" in text
    assert "politeness markers" in text
    assert "question tags" in text
    assert "every negation" in text and "write in Yoruba" in text
    assert "PERSON-000001" in text and "300,000" in text
    assert "50%" in text


def test_instruction_is_deterministic():
    spec = load_code_switch_spec("X", ["English", "Korean"], {"granularity": "word"})
    assert spec is not None
    assert build_instruction(spec, ("A-1",)) == build_instruction(spec, ("A-1",))


# --------------------------------------------------------------------------
# generators
# --------------------------------------------------------------------------


def test_llm_generator_accepts_a_good_first_answer():
    spec, detectors = _spec("CS-EN-KO")
    calls: list[tuple[str, str]] = []

    def complete(system: str, user: str) -> str:
        calls.append((system, user))
        return json.dumps({"text": CS_EN_KO}, ensure_ascii=False)

    generator = LLMCodeSwitchGenerator(
        complete,
        lambda _s, text, source: validate_surface_text(
            spec, text, detectors, source_text=source
        ),
    )
    cs = load_code_switch_spec("CS-EN-KO", list(spec.languages), {"granularity": "clause"})
    result = generator.generate(
        CodeSwitchRequest(source_text=SOURCE, spec=cs, protected_tokens=("PERSON-000001",))
    )
    assert result.ok and result.attempts == 1
    assert len(calls) == 1


def test_llm_generator_retries_with_the_reasons_then_gives_up():
    spec, detectors = _spec("CS-EN-KO")
    seen: list[str] = []

    def complete(system: str, user: str) -> str:
        seen.append(user)
        return json.dumps({"text": SOURCE})  # never mixed

    generator = LLMCodeSwitchGenerator(
        complete,
        lambda _s, text, source: validate_surface_text(
            spec, text, detectors, source_text=source
        ),
        max_attempts=3,
    )
    cs = load_code_switch_spec("CS-EN-KO", list(spec.languages), {})
    result = generator.generate(CodeSwitchRequest(source_text=SOURCE, spec=cs))
    assert not result.ok
    assert result.attempts == 3
    assert any("rejected for these reasons" in item for item in seen[1:])
    assert any("Korean" in problem for problem in result.problems)


def test_generator_never_silently_substitutes():
    """A failed generation must fail, not fall back to lexical substitution."""
    spec, detectors = _spec("CS-EN-YO")
    generator = LLMCodeSwitchGenerator(
        lambda system, user: json.dumps({"text": SOURCE}),
        lambda _s, text, source: validate_surface_text(
            spec, text, detectors, source_text=source
        ),
        max_attempts=1,
    )
    cs = load_code_switch_spec("CS-EN-YO", list(spec.languages), {})
    result = generator.generate(CodeSwitchRequest(source_text=SOURCE, spec=cs))
    assert not result.ok
    assert result.text == SOURCE  # returned for inspection, but flagged not ok


def test_generator_tolerates_bare_text_response():
    spec, detectors = _spec("CS-EN-KO")
    generator = LLMCodeSwitchGenerator(
        lambda system, user: CS_EN_KO,
        lambda _s, text, source: validate_surface_text(
            spec, text, detectors, source_text=source
        ),
    )
    cs = load_code_switch_spec("CS-EN-KO", list(spec.languages), {})
    result = generator.generate(CodeSwitchRequest(source_text=SOURCE, spec=cs))
    assert result.ok


def test_scripted_generator_serves_reviewed_text():
    spec, detectors = _spec("CS-EN-YO")
    cs = load_code_switch_spec("CS-EN-YO", list(spec.languages), {"generator": "scripted"})
    generator = ScriptedGenerator(
        {("case-1", "CS-EN-YO"): CS_EN_YO},
        lambda _s, text, source: validate_surface_text(
            spec, text, detectors, source_text=source
        ),
    )
    ok = generator.generate(
        CodeSwitchRequest(source_text=SOURCE, spec=cs, case_id="case-1")
    )
    assert ok.ok
    missing = generator.generate(
        CodeSwitchRequest(source_text=SOURCE, spec=cs, case_id="case-2")
    )
    assert not missing.ok


def test_passthrough_returns_source():
    cs = load_code_switch_spec("X", ["English", "Korean"], {"generator": "passthrough"})
    result = PassthroughGenerator().generate(
        CodeSwitchRequest(source_text=SOURCE, spec=cs)
    )
    assert result.ok and result.text == SOURCE


# --------------------------------------------------------------------------
# the plug interface
# --------------------------------------------------------------------------


def test_switcher_end_to_end_with_a_stub_model():
    switcher = CodeSwitcher.from_profile(
        LANGUAGES / "CS-EN-YO.json",
        complete=lambda system, user: json.dumps({"text": CS_EN_YO}, ensure_ascii=False),
    )
    result = switcher.switch(SOURCE, case_id="c1")
    assert result.ok
    assert "jọ̀wọ́" in result.text
    assert switcher.language_profile(result.text)["Yoruba"] >= 5


def test_switcher_reports_its_configuration():
    switcher = CodeSwitcher.from_profile(
        LANGUAGES / "CS-EN-KO-YO.json", complete=lambda s, u: ""
    )
    described = switcher.describe()
    assert described["granularity"] == "semantic_role"
    assert described["reviewed"] is False
    assert "semantic_role" in switcher.spec.describe()


def test_switcher_can_check_human_authored_text():
    switcher = CodeSwitcher.from_profile(
        LANGUAGES / "CS-EN-ES.json", complete=lambda s, u: ""
    )
    assert switcher.check(CS_EN_ES, SOURCE) == []
    assert switcher.check(SOURCE, SOURCE) != []


def test_switcher_requires_a_model_for_llm_generator():
    with pytest.raises(CodeSwitchSpecError, match="pass complete"):
        CodeSwitcher.from_profile(LANGUAGES / "CS-EN-KO.json")


def test_switcher_exposes_the_exact_instruction():
    switcher = CodeSwitcher.from_profile(
        LANGUAGES / "CS-EN-KO.json", complete=lambda s, u: ""
    )
    text = switcher.instruction(SOURCE)
    assert "clause" in text.lower()
    assert "SWIFT-000001-000001" in text


# --------------------------------------------------------------------------
# factorial expansion
# --------------------------------------------------------------------------


def test_expand_conditions_crosses_the_factors():
    bodies = expand_conditions(
        {
            "languages": ["English", "Korean", "Yoruba"],
            "granularities": ["sentence", "clause", "word"],
            "language_orders": [
                ["English", "Korean", "Yoruba"],
                ["Yoruba", "English", "Korean"],
            ],
            "dominance_profiles": {
                "balanced": {"English": 1, "Korean": 1, "Yoruba": 1},
                "enheavy": {"English": 3, "Korean": 1, "Yoruba": 1},
            },
            "generator": "llm",
        }
    )
    assert len(bodies) == 3 * 2 * 2
    ids = {body["surface_id"] for body in bodies}
    assert len(ids) == 12
    for body in bodies:
        spec = load_code_switch_spec(
            body["surface_id"], body["languages"], body["code_switching"]
        )
        assert spec is not None
        assert spec.granularity in {"sentence", "clause", "word"}


def test_expand_requires_two_languages():
    with pytest.raises(CodeSwitchSpecError, match="at least two languages"):
        expand_conditions({"languages": ["English"]})
