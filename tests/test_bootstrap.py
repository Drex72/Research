from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from csrt_mas.bootstrap import EXPERIMENT_ENV, ROOT, select_experiment


class BootstrapTests(unittest.TestCase):
    def test_run_command_selects_frozen_experiment_before_imports(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = select_experiment(
                ["worker", "--run", "runs/example", "--phase", "gate", "--shard", "shard-000"]
            )
            self.assertEqual(args[0], "worker")
            self.assertEqual(
                os.environ[EXPERIMENT_ENV],
                str((ROOT / "runs/example/package/experiment.json").resolve()),
            )

    def test_explicit_experiment_is_removed_before_cli_parsing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = select_experiment(["--experiment", "custom.json", "validate"])
            self.assertEqual(args, ["validate"])
            self.assertEqual(os.environ[EXPERIMENT_ENV], str((ROOT / "custom.json").resolve()))


if __name__ == "__main__":
    unittest.main()
