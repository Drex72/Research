from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ENV = "CSRT_EXPERIMENT_PATH"
RUN_COMMANDS = {"worker", "collect", "analyze", "run-local", "status", "verify-package"}


def _value_after(argv: list[str], option: str) -> str | None:
    try:
        index = argv.index(option)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        raise SystemExit(f"{option} requires a value")
    return argv[index + 1]


def select_experiment(argv: list[str]) -> list[str]:
    args = list(argv)
    explicit = _value_after(args, "--experiment")
    if explicit is not None:
        index = args.index("--experiment")
        del args[index : index + 2]
        path = Path(explicit)
        os.environ[EXPERIMENT_ENV] = str(path if path.is_absolute() else (ROOT / path).resolve())
        return args

    command = next((value for value in args if not value.startswith("-")), None)
    run = _value_after(args, "--run") if command in RUN_COMMANDS else None
    if run is not None:
        run_path = Path(run)
        run_path = run_path if run_path.is_absolute() else (ROOT / run_path)
        os.environ[EXPERIMENT_ENV] = str((run_path / "package" / "experiment.json").resolve())
    return args


def main(argv: list[str] | None = None) -> None:
    selected = select_experiment(list(sys.argv[1:] if argv is None else argv))
    try:
        from .cli import main as cli_main

        cli_main(selected)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
