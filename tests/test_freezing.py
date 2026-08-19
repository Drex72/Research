from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from csrt_mas.freezing import _python_packages, sha256_file, shard_plan, verify_package


class FreezingTests(unittest.TestCase):
    @staticmethod
    def _valid_layout(root: Path) -> tuple[Path, dict]:
        run = root / "runs" / "example"
        project_file = root / "source.py"
        project_file.write_text("source", encoding="utf-8")
        package = run / "package" / "experiment.json"
        package.parent.mkdir(parents=True)
        package.write_text(
            json.dumps(
                {
                    "frozen": True,
                    "status": "ready",
                    "experiment_id": "example",
                    "package_id": "1" * 64,
                }
            ),
            encoding="utf-8",
        )
        files = [package]
        for phase in ("gate", "pilot"):
            unit = {
                "run_unit_id": f"{phase}-one",
                "phase": phase,
                "package_id": "1" * 64,
            }
            plan = run / "plans" / f"{phase}.jsonl"
            shard = run / "shards" / phase / "shard-000.jsonl"
            for path in (plan, shard):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(unit) + "\n", encoding="utf-8")
                files.append(path)
        manifest = {
            "schema_version": 1,
            "package_id": "1" * 64,
            "experiment_id": "example",
            "python_packages": _python_packages(),
            "plans": {"gate": 1, "pilot": 1},
            "shards_per_phase": 1,
            "files": {
                "run": {str(path.relative_to(run)): sha256_file(path) for path in files},
                "project": {"source.py": sha256_file(project_file)},
            },
        }
        return run, manifest

    def test_shards_are_deterministic_complete_and_disjoint(self) -> None:
        units = [{"run_unit_id": str(index)} for index in range(11)]
        first = shard_plan(units, 3)
        second = shard_plan(units, 3)
        self.assertEqual(first, second)
        flattened = [unit["run_unit_id"] for shard in first for unit in shard]
        self.assertEqual(sorted(flattened), sorted(unit["run_unit_id"] for unit in units))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_manifest_verification_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, manifest = self._valid_layout(root)
            package_file = run / "package" / "input.txt"
            package_file.write_text("frozen", encoding="utf-8")
            manifest["files"]["run"]["package/input.txt"] = sha256_file(package_file)
            (run / "frozen-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            verified = verify_package(run, root=root)
            self.assertEqual(verified["package_id"], "1" * 64)
            package_file.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                verify_package(run, root=root)

    def test_manifest_paths_cannot_escape_their_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs" / "example"
            run.mkdir(parents=True)
            manifest = {
                "schema_version": 1,
                "package_id": "1" * 64,
                "experiment_id": "example",
                "python_packages": _python_packages(),
                "files": {
                    "run": {"../outside": "0" * 64},
                    "project": {"source.py": "0" * 64},
                },
            }
            (run / "frozen-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "escapes"):
                verify_package(run, root=root)


if __name__ == "__main__":
    unittest.main()
