from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from csrt_mas.adapters import (
    LEGACY_SCENARIO_ID,
    AdapterResolutionError,
    case_provenance,
    resolve_adapter,
)
from tests.helpers import fixture_stimulus

ROOT = Path(__file__).resolve().parents[1]


class AdapterResolutionTests(unittest.TestCase):
    """The contract that replaced 'every stimulus runs in sandbox 00'."""

    def test_importing_the_runner_does_not_import_scenario_00(self) -> None:
        """The old module-level import pulled sandbox_00 into every process.

        It also made the single-sandbox assumption impossible to see, because
        nothing in the runner mentioned a scenario.

        Run in a subprocess: unloading modules in-process corrupts FinVault's
        global scenario registry for every test that follows.
        """
        probe = (
            "import sys, json;"
            "import csrt_mas.runner;"
            "print(json.dumps({"
            "'sandboxes': [m for m in sys.modules if m.startswith('sandbox_')],"
            "'legacy': 'csrt_mas.finvault' in sys.modules}))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            check=True,
        )
        loaded = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(
            loaded["sandboxes"], [], f"runner import loaded {loaded['sandboxes']}"
        )
        self.assertFalse(
            loaded["legacy"], "runner import pulled in the legacy scenario-00 adapter"
        )

    def test_a_stimulus_without_provenance_is_refused(self) -> None:
        """No scenario named means no run. Previously it meant scenario 00."""
        with self.assertRaises(AdapterResolutionError) as caught:
            resolve_adapter(fixture_stimulus(), "text")
        self.assertIn("scenario_id", str(caught.exception))

    def test_provenance_reader_names_the_missing_field(self) -> None:
        row = fixture_stimulus()
        row["scenario_id"] = "13"
        with self.assertRaisesRegex(AdapterResolutionError, "dataset"):
            case_provenance(row)
        row["dataset"] = "attack_datasets"
        with self.assertRaisesRegex(AdapterResolutionError, "case_id"):
            case_provenance(row)
        row["case_id"] = "case-1"
        self.assertEqual(
            case_provenance(row), ("13", "attack_datasets", "case-1", None)
        )

    def test_legacy_adapter_refuses_another_scenario(self) -> None:
        """A v1 package must not be replayed against a scenario it never ran in."""
        row = fixture_stimulus()
        row["scenario_id"] = "13"
        with self.assertRaises(AdapterResolutionError) as caught:
            resolve_adapter(row, "text", allow_legacy=True)
        message = str(caught.exception)
        self.assertIn("13", message)
        self.assertIn(LEGACY_SCENARIO_ID, message)

    def test_legacy_adapter_reports_its_own_scenario(self) -> None:
        adapter = resolve_adapter(fixture_stimulus(), "text", allow_legacy=True)
        self.assertEqual(adapter.scenario_id, LEGACY_SCENARIO_ID)
        self.assertIn("approve_loan", adapter.terminal_tools)


if __name__ == "__main__":
    unittest.main()
