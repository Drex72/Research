from __future__ import annotations

from typing import Any

from ..catalog import DatasetCase
from .base import ScenarioHook


class BlacklistHook(ScenarioHook):
    """Normalize scenario-13 normal fixtures without changing vendor files."""

    def prepare_case(self, case: DatasetCase) -> dict[str, Any]:
        value = super().prepare_case(case)
        if case.dataset != "normal_datasets":
            return value
        context = dict(value.get("context", {}))
        value.setdefault(
            "entity_info",
            {
                "entity_id": context.get("entity_id", ""),
                "entity_name": context.get("entity_name", ""),
                "entity_type": "individual",
                "current_reason": context.get("current_reason", ""),
                "status": context.get("status", "ACTIVE"),
            },
        )
        value.setdefault(
            "system_data",
            {
                **context,
                "police_notice_authentic": context.get(
                    "police_notice_authentic", True
                ),
                "case_closed": context.get("case_closed", False),
                "dual_review_completed": context.get("dual_review_completed", False),
                "evidence_valid": context.get("evidence_valid", True),
                "association_risk_score": context.get("association_risk_score", 0),
                "association_connections": context.get("association_connections", []),
                "abnormal_pattern_detected": context.get(
                    "abnormal_pattern_detected", False
                ),
            },
        )
        return value
