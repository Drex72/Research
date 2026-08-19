from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .config import CONFIG, GATE_REPORT_PATH, RAW_TRACE_PATH
from .freezing import verify_package
from .ollama import ChatRuntime
from .runner import load_plan, run_phase
from .trace import TraceWriter, read_verified


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _safe_name(value: str, label: str) -> str:
    if not SAFE_NAME.fullmatch(value) or ".." in value:
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _require_frozen_run(run_dir: Path) -> dict[str, Any]:
    if not CONFIG.frozen:
        raise RuntimeError("workers and collectors require a frozen experiment package")
    if run_dir.resolve() != CONFIG.output_dir.resolve():
        raise RuntimeError("requested run directory differs from the active frozen experiment")
    return verify_package(run_dir)


def shard_path(run_dir: Path, phase: str, shard_name: str) -> Path:
    if phase not in {"gate", "pilot"}:
        raise ValueError(f"unsupported phase: {phase}")
    shard_name = _safe_name(shard_name, "shard name")
    if not shard_name.endswith(".jsonl"):
        shard_name += ".jsonl"
    path = (run_dir / "shards" / phase / shard_name).resolve()
    if path.parent != (run_dir / "shards" / phase).resolve():
        raise ValueError("shard path escapes the phase directory")
    return path


def worker_trace_path(run_dir: Path, phase: str, worker_id: str, shard_name: str) -> Path:
    worker_id = _safe_name(worker_id, "worker ID")
    shard_stem = Path(_safe_name(shard_name, "shard name")).stem
    return run_dir / "traces" / "workers" / phase / f"{worker_id}--{shard_stem}.jsonl"


def _validate_worker_events(
    events: list[dict[str, Any]],
    units: Mapping[str, dict[str, Any]],
    package_id: str,
    manifest_sha256: str,
) -> None:
    seen: set[str] = set()
    for event in events:
        run_unit_id = event.get("run_unit_id")
        if run_unit_id in seen:
            raise RuntimeError(f"worker trace contains a duplicate run unit: {run_unit_id}")
        seen.add(run_unit_id)
        planned = units.get(str(run_unit_id))
        if planned is None:
            raise RuntimeError(f"worker trace contains an unplanned run unit: {run_unit_id}")
        if event.get("package_id") != package_id:
            raise RuntimeError(f"worker trace package mismatch: {run_unit_id}")
        if event.get("manifest_sha256") != manifest_sha256:
            raise RuntimeError(f"worker trace manifest mismatch: {run_unit_id}")
        if event.get("status") != "complete":
            raise RuntimeError(f"worker trace contains an incomplete event: {run_unit_id}")
        for key, expected in planned.items():
            if event.get(key) != expected:
                raise RuntimeError(f"worker trace plan mismatch for {run_unit_id}: {key}")


def run_worker(
    runtimes: ChatRuntime | Mapping[str, ChatRuntime],
    run_dir: Path,
    phase: str,
    shard_name: str,
    worker_id: str,
) -> dict[str, Any]:
    manifest = _require_frozen_run(run_dir)
    if phase == "pilot":
        if not GATE_REPORT_PATH.exists():
            raise RuntimeError("pilot workers are blocked until the collected gate passes")
        gate = json.loads(GATE_REPORT_PATH.read_text(encoding="utf-8"))
        if (
            not gate.get("passed")
            or gate.get("package_id") != manifest["package_id"]
            or gate.get("manifest_sha256") != manifest["manifest_sha256"]
        ):
            raise RuntimeError("pilot workers are blocked by an invalid or failed gate report")

    path = shard_path(run_dir, phase, shard_name)
    units = load_plan(phase, path)
    if any(unit.get("package_id") != manifest["package_id"] for unit in units):
        raise RuntimeError("shard package ID differs from the frozen manifest")
    traced_units = [{**unit, "manifest_sha256": manifest["manifest_sha256"]} for unit in units]
    trace_path = worker_trace_path(run_dir, phase, worker_id, shard_name)
    existing = read_verified(trace_path)
    _validate_worker_events(
        existing,
        {unit["run_unit_id"]: unit for unit in traced_units},
        manifest["package_id"],
        manifest["manifest_sha256"],
    )
    result = run_phase(runtimes, phase, trace_path=trace_path, plan=traced_units)
    result.update(
        {
            "worker_id": worker_id,
            "shard": path.name,
            "trace": str(trace_path.relative_to(run_dir)),
            "package_id": manifest["package_id"],
        }
    )
    return result


def _phase_worker_events(
    run_dir: Path,
    phase: str,
    manifest: dict[str, Any],
    *,
    require_complete: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan = load_plan(phase, run_dir / "plans" / f"{phase}.jsonl")
    planned = {unit["run_unit_id"]: unit for unit in plan}
    events: list[dict[str, Any]] = []
    owners: dict[str, Path] = {}
    directory = run_dir / "traces" / "workers" / phase
    for path in sorted(directory.glob("*.jsonl")) if directory.exists() else []:
        selected = read_verified(path)
        _validate_worker_events(
            selected,
            planned,
            manifest["package_id"],
            manifest["manifest_sha256"],
        )
        for event in selected:
            run_unit_id = event["run_unit_id"]
            if run_unit_id in owners:
                raise RuntimeError(
                    f"duplicate run unit across worker traces: {run_unit_id} "
                    f"({owners[run_unit_id].name}, {path.name})"
                )
            owners[run_unit_id] = path
            events.append(event)
    if require_complete and set(owners) != set(planned):
        missing = len(set(planned) - set(owners))
        raise RuntimeError(f"{phase} collection is incomplete: {len(owners)}/{len(planned)}; missing={missing}")
    by_id = {event["run_unit_id"]: event for event in events}
    ordered = [by_id[unit["run_unit_id"]] for unit in plan if unit["run_unit_id"] in by_id]
    return plan, ordered


def _write_collected(events: list[dict[str, Any]], path: Path | None = None) -> None:
    path = path or RAW_TRACE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".collected-", suffix=".jsonl", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        writer = TraceWriter(temporary)
        for event in events:
            clean = {
                key: value
                for key, value in event.items()
                if key not in {"event_sha256", "prev_event_sha256"}
            }
            clean["source_event_sha256"] = event["event_sha256"]
            writer.append(clean)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def collect_phase(run_dir: Path, phase: str) -> dict[str, Any]:
    manifest = _require_frozen_run(run_dir)
    if phase == "pilot":
        if not GATE_REPORT_PATH.exists():
            raise RuntimeError("pilot collection requires a collected gate report")
        gate_report = json.loads(GATE_REPORT_PATH.read_text(encoding="utf-8"))
        if (
            not gate_report.get("passed")
            or gate_report.get("package_id") != manifest["package_id"]
            or gate_report.get("manifest_sha256") != manifest["manifest_sha256"]
        ):
            raise RuntimeError("pilot collection is blocked by an invalid or failed gate report")
    _, gate_events = _phase_worker_events(
        run_dir,
        "gate",
        manifest,
        require_complete=phase in {"gate", "pilot"},
    )
    pilot_events: list[dict[str, Any]] = []
    if phase == "pilot":
        _, pilot_events = _phase_worker_events(
            run_dir,
            "pilot",
            manifest,
            require_complete=True,
        )
    _write_collected([*gate_events, *pilot_events])

    result: dict[str, Any] = {
        "phase": phase,
        "package_id": manifest["package_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "gate_rows": len(gate_events),
        "pilot_rows": len(pilot_events),
    }
    if phase == "gate":
        from .analysis import gate_metrics

        report = gate_metrics(read_verified(RAW_TRACE_PATH))
        report.update(
            {
                "package_id": manifest["package_id"],
                "manifest_sha256": manifest["manifest_sha256"],
            }
        )
        GATE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        GATE_REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["gate_passed"] = report["passed"]
    return result
