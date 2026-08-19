from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from csrt_mas.settings import EXPERIMENT_ENV, ROOT
from csrt_mas.trace import TraceWriter


class PackageIntegrationTests(unittest.TestCase):
    @staticmethod
    def _rows(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _write_synthetic_workers(self, run_dir: Path, phase: str, manifest: dict) -> None:
        scenario = run_dir / "package" / "scenario"
        stimuli_path = scenario / ("qualification.jsonl" if phase == "gate" else "cases.jsonl")
        stimuli = {row["semantic_id"]: row for row in self._rows(stimuli_path)}
        for shard_path in sorted((run_dir / "shards" / phase).glob("*.jsonl")):
            trace_path = (
                run_dir
                / "traces"
                / "workers"
                / phase
                / f"synthetic--{shard_path.stem}.jsonl"
            )
            writer = TraceWriter(trace_path)
            for unit in self._rows(shard_path):
                stimulus = stimuli[unit["semantic_id"]]
                action = {
                    "tool": "escalate_to_human",
                    "args": {"case_id": unit["semantic_id"], "reason": "synthetic integration"},
                }
                officer_compromised = None
                if unit["topology"] in {"summary-relay", "trust-break"} and stimulus["intent"] == "adversarial":
                    officer_compromised = False
                writer.append(
                    {
                        **unit,
                        "manifest_sha256": manifest["manifest_sha256"],
                        "status": "complete",
                        "pair_id": stimulus["pair_id"],
                        "property_id": stimulus["property_id"],
                        "frame": stimulus["frame"],
                        "intent": stimulus["intent"],
                        "text_sha256": stimulus["text_sha256"][unit["surface"]],
                        "input_text": stimulus["texts"][unit["surface"]],
                        "officer_record": None,
                        "officer_compromised": officer_compromised,
                        "calls": [],
                        "outcome": {
                            "action": action,
                            "action_sequence": [action],
                            "tool_result": {},
                            "state": {},
                            "triggered": [],
                            "target_triggered": False,
                            "any_triggered": False,
                            "utility_success": True if stimulus["intent"] == "benign" else None,
                            "technical_failure": False,
                            "steps": [],
                        },
                        "technical_failure": False,
                        "elapsed_seconds": 0.0,
                    }
                )

    def test_migrated_design_freezes_and_reloads_from_copied_resources(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        experiment_id = f"package-test-{suffix}"
        experiment_path = ROOT / ".omx" / "context" / f"{experiment_id}.json"
        run_dir = ROOT / "runs" / experiment_id
        raw = json.loads((ROOT / "experiment.json").read_text(encoding="utf-8"))
        raw["experiment_id"] = experiment_id
        raw["status"] = "ready"
        experiment_path.parent.mkdir(parents=True, exist_ok=True)
        experiment_path.write_text(json.dumps(raw), encoding="utf-8")
        environment = {**os.environ, EXPERIMENT_ENV: str(experiment_path)}
        try:
            frozen = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from csrt_mas.freezing import freeze_experiment; "
                    "import json; print(json.dumps(freeze_experiment(3), sort_keys=True))",
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(frozen.stdout)
            self.assertEqual(manifest["plans"], {"gate": 108, "pilot": 384})
            self.assertEqual(manifest["shards_per_phase"], 3)
            self.assertEqual(manifest["research"]["domain"], "finance")
            self.assertEqual(manifest["configuration"]["languages"], ["EN", "KO", "CS"])

            frozen_environment = {
                **os.environ,
                EXPERIMENT_ENV: str(run_dir / "package" / "experiment.json"),
            }
            validated = subprocess.run(
                [sys.executable, "-m", "csrt_mas", "validate"],
                cwd=ROOT,
                env=frozen_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads(validated.stdout)
            self.assertTrue(summary["frozen"])
            self.assertEqual(summary["gate_units"], 108)
            self.assertEqual(summary["pilot_units"], 384)

            verified = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "csrt_mas",
                    "verify-package",
                    "--run",
                    str(run_dir.relative_to(ROOT)),
                ],
                cwd=ROOT,
                env=frozen_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(json.loads(verified.stdout)["verified"])

            self._write_synthetic_workers(run_dir, "gate", manifest)
            gate = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "csrt_mas",
                    "collect",
                    "--run",
                    str(run_dir.relative_to(ROOT)),
                    "--phase",
                    "gate",
                ],
                cwd=ROOT,
                env=frozen_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(json.loads(gate.stdout)["gate_passed"])

            self._write_synthetic_workers(run_dir, "pilot", manifest)
            collected = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "csrt_mas",
                    "collect",
                    "--run",
                    str(run_dir.relative_to(ROOT)),
                    "--phase",
                    "pilot",
                ],
                cwd=ROOT,
                env=frozen_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(collected.stdout)["pilot_rows"], 384)

            analyzed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "csrt_mas",
                    "analyze",
                    "--run",
                    str(run_dir.relative_to(ROOT)),
                ],
                cwd=ROOT,
                env=frozen_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(analyzed.stdout)["rows"], 384)
            html_report = run_dir / "report" / "EXPERIMENT_REPORT.html"
            self.assertTrue(html_report.exists())
            html_text = html_report.read_text(encoding="utf-8")
            self.assertIn("Agents and models", html_text)
            self.assertIn("Action-level risk by language and pipeline", html_text)
            self.assertIn("Reproducibility and provenance", html_text)
            self.assertNotIn("synthetic integration", html_text)
        finally:
            if experiment_path.exists():
                experiment_path.unlink()
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
