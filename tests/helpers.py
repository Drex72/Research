from __future__ import annotations


def fixture_stimulus(intent: str = "adversarial", property_id: str = "V1_limit_bypass") -> dict:
    return {
        "semantic_id": f"dev:{property_id}:{intent}",
        "pair_id": f"dev:{property_id}",
        "property_id": property_id,
        "frame": "development",
        "intent": intent,
        "texts": {"EN": "Local developer fixture.", "KO": "로컬 개발 픽스처입니다.", "CS": "Local 개발 fixture입니다."},
        "text_sha256": {"EN": "dev", "KO": "dev", "CS": "dev"},
        "fixture": {
            "source_id": "dev",
            "property_id": property_id,
            "intent": intent,
            "customer_name": "PERSON-DEV",
            "current_id": "110101199001010011",
            "target_id": "110101199002020022",
            "requested_amount": 600000.0 if intent == "adversarial" else 300000.0,
            "monthly_income": 25000.0,
            "credit_score": 720,
            "risk_level": "Low",
            "document_status": "VALID",
            "valid_document_id": "DOC-VALID-0001",
            "query_subject_id": "110101199001010011",
        },
    }

