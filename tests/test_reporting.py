from __future__ import annotations

import unittest

from csrt_mas.reporting import _bar, _e


class ReportingTests(unittest.TestCase):
    def test_html_escapes_experiment_metadata(self) -> None:
        self.assertEqual(_e('<script>alert("x")</script>'), "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;")

    def test_metric_bar_clamps_visual_width_but_preserves_value(self) -> None:
        rendered = _bar(1.25)
        self.assertIn("width:100.00%", rendered)
        self.assertIn("125.0%", rendered)
        self.assertIn("NA", _bar(float("nan")))


if __name__ == "__main__":
    unittest.main()
