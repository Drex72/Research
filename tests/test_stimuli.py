from __future__ import annotations

import unittest

from csrt_mas.stimuli import validate_stimuli


class StimulusTests(unittest.TestCase):
    def test_frozen_candidate_is_complete_and_matched(self) -> None:
        result = validate_stimuli()
        self.assertEqual(result["semantic_rows"], 32)
        self.assertEqual(result["matched_pairs"], 16)
        self.assertEqual(result["surfaces"], 3)


if __name__ == "__main__":
    unittest.main()
