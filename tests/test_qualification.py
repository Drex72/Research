from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from csrt_mas.qualification import validate_qualification_stimuli, write_qualification_stimuli
from csrt_mas.runner import make_plan


class QualificationTests(unittest.TestCase):
    def test_heldout_artifact_is_balanced_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qualification.jsonl"
            written = write_qualification_stimuli(path)
            validated = validate_qualification_stimuli(path)
        self.assertEqual(written, validated)
        self.assertEqual(validated["semantic_rows"], 8)
        self.assertEqual(validated["properties"], 4)
        self.assertEqual(validated["surfaces"], 3)

    def test_gate_plan_uses_only_heldout_rows_and_fixed_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate-plan.jsonl"
            units = make_plan("gate", path)
        self.assertEqual(len(units), 108)
        self.assertEqual(sum(unit["replicate"] == 0 for unit in units), 96)
        repeats = [unit for unit in units if unit["replicate"] == 1]
        self.assertEqual(len(repeats), 12)
        repeated_cells = {(unit["surface"], unit["topology"]) for unit in repeats}
        self.assertEqual(len(repeated_cells), 12)
        self.assertTrue(all(unit["semantic_id"].startswith("qualification:") for unit in units))


if __name__ == "__main__":
    unittest.main()
