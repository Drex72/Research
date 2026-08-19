from __future__ import annotations

import unittest

from csrt_mas.schemas import SchemaError, validate_action, validate_officer


class SchemaTests(unittest.TestCase):
    def test_action_rejects_extra_fields(self) -> None:
        with self.assertRaises(SchemaError):
            validate_action({"tool": "escalate_to_human", "args": {}, "extra": True})

    def test_action_rejects_unknown_name(self) -> None:
        with self.assertRaises(SchemaError):
            validate_action({"tool": "unknown", "args": {}})

    def test_officer_requires_matching_case(self) -> None:
        value = {
            "case_id": "other",
            "risk_label": "UNCERTAIN",
            "requested_operation": "OTHER",
            "recommended_action": "ESCALATE",
            "normalized_summary": "Developer fixture",
        }
        with self.assertRaises(SchemaError):
            validate_officer(value, "expected")


if __name__ == "__main__":
    unittest.main()

