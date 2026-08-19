from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from csrt_mas.trace import TraceWriter, read_verified


class TraceTests(unittest.TestCase):
    def test_append_resume_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            writer = TraceWriter(path)
            writer.append({"run_unit_id": "one", "status": "complete"})
            resumed = TraceWriter(path)
            self.assertIn("one", resumed.completed)
            resumed.append({"run_unit_id": "two", "status": "complete"})
            self.assertEqual(len(read_verified(path)), 2)
            lines = path.read_text().splitlines()
            value = json.loads(lines[0])
            value["status"] = "changed"
            lines[0] = json.dumps(value)
            path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(ValueError):
                read_verified(path)


if __name__ == "__main__":
    unittest.main()

