from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from csrt_mas.distribution import collect_phase
from csrt_mas.trace import TraceWriter, read_verified


class DistributionTests(unittest.TestCase):
    @staticmethod
    def _unit() -> dict:
        return {
            "run_unit_id": "unit-one",
            "phase": "gate",
            "semantic_id": "gate-one",
            "surface": "EN",
            "topology": "single",
            "model": "scripted",
            "models": {"case_officer": "scripted", "executor": "scripted"},
            "seed": 1,
            "replicate": 0,
            "package_id": "package-one",
        }

    @staticmethod
    def _event(unit: dict) -> dict:
        return {
            **unit,
            "manifest_sha256": "manifest-one",
            "status": "complete",
            "technical_failure": False,
            "outcome": {"utility_success": True, "action_sequence": []},
        }

    def _layout(self, root: Path) -> tuple[Path, Path, Path]:
        run = root / "runs" / "example"
        plan = run / "plans" / "gate.jsonl"
        plan.parent.mkdir(parents=True)
        plan.write_text(json.dumps(self._unit()) + "\n", encoding="utf-8")
        collected = run / "traces" / "collected.jsonl"
        report = run / "metrics" / "gate-report.json"
        return run, collected, report

    def test_complete_worker_output_is_canonically_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, collected, report = self._layout(Path(directory))
            worker = run / "traces" / "workers" / "gate" / "machine--shard-000.jsonl"
            TraceWriter(worker).append(self._event(self._unit()))
            manifest = {
                "package_id": "package-one",
                "manifest_sha256": "manifest-one",
            }
            fake_config = SimpleNamespace(frozen=True, output_dir=run)
            with (
                patch("csrt_mas.distribution.CONFIG", fake_config),
                patch("csrt_mas.distribution.RAW_TRACE_PATH", collected),
                patch("csrt_mas.distribution.GATE_REPORT_PATH", report),
                patch("csrt_mas.distribution.verify_package", return_value=manifest),
            ):
                result = collect_phase(run, "gate")
            self.assertEqual(result["gate_rows"], 1)
            self.assertEqual(len(read_verified(collected)), 1)
            self.assertTrue(report.exists())

    def test_duplicate_units_across_workers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, collected, report = self._layout(Path(directory))
            directory_path = run / "traces" / "workers" / "gate"
            event = self._event(self._unit())
            TraceWriter(directory_path / "one--shard-000.jsonl").append(event)
            TraceWriter(directory_path / "two--shard-000.jsonl").append(event)
            manifest = {"package_id": "package-one", "manifest_sha256": "manifest-one"}
            fake_config = SimpleNamespace(frozen=True, output_dir=run)
            with (
                patch("csrt_mas.distribution.CONFIG", fake_config),
                patch("csrt_mas.distribution.RAW_TRACE_PATH", collected),
                patch("csrt_mas.distribution.GATE_REPORT_PATH", report),
                patch("csrt_mas.distribution.verify_package", return_value=manifest),
                self.assertRaisesRegex(RuntimeError, "duplicate run unit across worker traces"),
            ):
                collect_phase(run, "gate")

    def test_incomplete_phase_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run, collected, report = self._layout(Path(directory))
            manifest = {"package_id": "package-one", "manifest_sha256": "manifest-one"}
            fake_config = SimpleNamespace(frozen=True, output_dir=run)
            with (
                patch("csrt_mas.distribution.CONFIG", fake_config),
                patch("csrt_mas.distribution.RAW_TRACE_PATH", collected),
                patch("csrt_mas.distribution.GATE_REPORT_PATH", report),
                patch("csrt_mas.distribution.verify_package", return_value=manifest),
                self.assertRaisesRegex(RuntimeError, "collection is incomplete"),
            ):
                collect_phase(run, "gate")


if __name__ == "__main__":
    unittest.main()
