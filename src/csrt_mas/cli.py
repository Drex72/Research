from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analysis import analyze, gate_metrics
from .config import (
    CONFIG,
    FINVAULT_ROOT,
    GATE_REPORT_PATH,
    OLLAMA_VERSION,
    PILOT_PLAN_PATH,
    RAW_TRACE_PATH,
    ROOT,
)
from .distribution import collect_phase, run_worker
from .external_finvault import import_finvault_jsonl
from .finvault import validate_executor_tools
from .finvault_dynamic import (
    FinVaultCatalog,
    audit_all_interfaces,
    load_dynamic_design,
)
from .freezing import freeze_experiment, verify_package
from .ollama import ChatRuntime, OllamaClient
from .qualification import validate_qualification_stimuli
from .runner import load_plan, make_plan
from .settings import (
    configuration_summary,
    load_outcome_rules,
    load_pipeline_set,
    load_prompt_set,
)
from .stimuli import author_stimuli, validate_stimuli
from .trace import read_verified


def _runtimes() -> dict[str, ChatRuntime]:
    clients: dict[str, OllamaClient] = {}
    observed_version: str | None = None
    observed_digests: dict[str, str] = {}
    for role, agent in CONFIG.agents.items():
        client = OllamaClient(model=agent.model)
        if observed_version is None:
            observed_version = client.version()
        if observed_version != OLLAMA_VERSION:
            raise RuntimeError("local runtime version differs from experiment configuration")
        if agent.model not in observed_digests:
            observed_digests[agent.model] = client.model_digest()
        digest = observed_digests[agent.model]
        if digest != agent.digest:
            raise RuntimeError(f"local model digest differs for agent role: {role}")
        clients[role] = client
    return clients


def _runtime(role: str = "executor") -> ChatRuntime:
    return _runtimes()[role]


def _finvault_catalog() -> FinVaultCatalog:
    return FinVaultCatalog(FINVAULT_ROOT, ROOT / "scenarios" / "finvault")


def _phase_rows(phase: str) -> list[dict[str, Any]]:
    return [
        event
        for event in read_verified(RAW_TRACE_PATH)
        if event.get("phase") == phase and event.get("status") == "complete"
    ]


def _validate() -> dict[str, Any]:
    prompts = load_prompt_set(CONFIG)
    pipelines = load_pipeline_set(CONFIG)
    rules = load_outcome_rules(CONFIG)
    tools = validate_executor_tools()
    stimuli = validate_stimuli()
    qualification = validate_qualification_stimuli()
    gate = make_plan("gate")
    pilot = make_plan("pilot")
    dynamic_design = load_dynamic_design(CONFIG.raw, CONFIG.root, _finvault_catalog())
    return {
        **configuration_summary(CONFIG, prompts, pipelines),
        "stimuli": stimuli,
        "qualification": qualification,
        "outcome_rule_set": rules["rule_set_id"],
        "executor_tools": sorted(tools),
        "gate_units": len(gate),
        "pilot_units": len(pilot),
        "dynamic_finvault": dynamic_design.summary(_finvault_catalog()),
    }


def _status() -> dict[str, Any]:
    prompts = load_prompt_set(CONFIG)
    summary = configuration_summary(CONFIG, prompts)
    package_state = "editable"
    if CONFIG.manifest_path.exists():
        try:
            verify_package()
            package_state = "verified"
        except (OSError, ValueError, RuntimeError):
            package_state = "mismatch"
    gate = _phase_rows("gate")
    pilot = _phase_rows("pilot")
    worker_files = {
        phase: len(list((CONFIG.output_dir / "traces" / "workers" / phase).glob("*.jsonl")))
        for phase in ("gate", "pilot")
    }
    summary.update(
        {
            "package": package_state,
            "gate_completed": len(gate),
            "pilot_completed": len(pilot),
            "worker_trace_files": worker_files,
            "technical_failures": sum(bool(row.get("technical_failure")) for row in gate + pilot),
        }
    )
    return summary


def _require_complete_pilot(manifest: dict[str, Any] | None = None) -> None:
    manifest = manifest or verify_package()
    events = read_verified(RAW_TRACE_PATH)
    measured = [event for event in events if event.get("phase") in {"gate", "pilot"}]
    for event in measured:
        if (
            event.get("package_id") != manifest["package_id"]
            or event.get("manifest_sha256") != manifest["manifest_sha256"]
        ):
            raise RuntimeError("collected trace provenance differs from the frozen package")
    planned = len(load_plan("pilot", PILOT_PLAN_PATH))
    completed = sum(event.get("phase") == "pilot" and event.get("status") == "complete" for event in events)
    if completed != planned:
        raise RuntimeError(f"analysis requires a complete collected pilot: {completed}/{planned}")


def _run_path(value: str | None) -> Path:
    path = CONFIG.output_dir if value is None else Path(value)
    if not path.is_absolute():
        path = CONFIG.root / path
    return path.resolve()


def _shard_names(run_dir: Path, phase: str) -> list[str]:
    names = [path.name for path in sorted((run_dir / "shards" / phase).glob("*.jsonl"))]
    if not names:
        raise FileNotFoundError(f"no {phase} shards found in {run_dir}")
    return names


def _run_local(run_dir: Path, worker_id: str) -> dict[str, Any]:
    verify_package(run_dir)
    runtimes = _runtimes()
    for shard in _shard_names(run_dir, "gate"):
        run_worker(runtimes, run_dir, "gate", shard, worker_id)
    gate = collect_phase(run_dir, "gate")
    print(json.dumps(gate, sort_keys=True), flush=True)
    if not gate["gate_passed"]:
        return {"gate_passed": False, "pilot_rows": 0, "decision": None}
    for shard in _shard_names(run_dir, "pilot"):
        run_worker(runtimes, run_dir, "pilot", shard, worker_id)
    collected = collect_phase(run_dir, "pilot")
    _require_complete_pilot()
    result = analyze()
    return {
        "gate_passed": True,
        "pilot_rows": collected["pilot_rows"],
        "decision": result["decision"],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="csrt-mas")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate the editable or frozen experiment without model calls")
    describe = sub.add_parser(
        "describe",
        help="show what experiment.json implies: cases, clusters, run size. No model calls",
    )
    prepare = sub.add_parser(
        "prepare",
        help="author every language surface and write the stimulus file, before freezing",
    )
    prepare.add_argument(
        "--limit", type=int,
        help="stop after generating this many surfaces, for a cheap first look",
    )
    prepare.add_argument(
        "--no-reuse", action="store_true",
        help="regenerate every surface instead of reusing the cache",
    )
    prepare.add_argument(
        "--require-reviewed", action="store_true",
        help="refuse to write stimuli unless every generated surface is marked reviewed",
    )
    freeze = sub.add_parser("freeze", help="create an immutable run package and deterministic shards")
    freeze.add_argument("--shards", type=int)
    status = sub.add_parser("status", help="show aggregate package and completion status")
    status.add_argument("--run")
    verify = sub.add_parser("verify-package", help="verify every frozen package checksum")
    verify.add_argument("--run", required=True)

    worker = sub.add_parser("worker", help="execute one frozen shard")
    worker.add_argument("--run", required=True)
    worker.add_argument("--phase", choices=("gate", "pilot"), required=True)
    worker.add_argument("--shard", required=True)
    worker.add_argument("--worker-id", required=True)

    collect = sub.add_parser("collect", help="verify and collect a complete phase")
    collect.add_argument("--run", required=True)
    collect.add_argument("--phase", choices=("gate", "pilot"), required=True)

    analyze_parser = sub.add_parser("analyze", help="analyze a complete verified pilot")
    analyze_parser.add_argument("--run", required=True)

    local = sub.add_parser("run-local", help="run every shard sequentially on this machine")
    local.add_argument("--run", required=True)
    local.add_argument("--worker-id", default="local")

    author = sub.add_parser("author-v1", help="legacy English/Korean FinVault corpus helper")
    author.add_argument("--force", action="store_true")
    external = sub.add_parser("import-finvault-dataset", help="import reviewed external pairs into FinVault case JSONL")
    external.add_argument("--input", required=True)
    external.add_argument("--output", required=True)
    external.add_argument("--dataset", required=True)
    external.add_argument("--version", required=True)
    external.add_argument("--url", required=True)
    external.add_argument("--license", dest="license_name", required=True)
    catalog = sub.add_parser(
        "finvault-catalog",
        help="list FinVault scenarios and CSRT integration readiness without model calls",
    )
    catalog.add_argument("--scenario")
    dataset = sub.add_parser(
        "finvault-dataset",
        help="inspect a FinVault dataset selection without displaying raw cases",
    )
    dataset.add_argument(
        "--dataset",
        choices=("attack_datasets", "attack_datasets_synthesis", "normal_datasets"),
        required=True,
    )
    dataset.add_argument("--scenario", required=True)
    dataset.add_argument("--family")
    sub.add_parser(
        "finvault-design",
        help="validate and summarize experiment.json dynamic FinVault selection",
    )
    sub.add_parser(
        "finvault-audit",
        help="audit all upstream sandbox interfaces without claiming oracle validity",
    )
    args = parser.parse_args(argv)

    if args.command == "import-finvault-dataset":
        result = import_finvault_jsonl(
            Path(args.input),
            Path(args.output),
            dataset=args.dataset,
            version=args.version,
            url=args.url,
            license_name=args.license_name,
        )
        print(json.dumps(result, sort_keys=True))
    elif args.command == "finvault-catalog":
        selected = [args.scenario] if args.scenario else None
        catalog_value = _finvault_catalog()
        if selected is None:
            result = catalog_value.summary()
        else:
            record = catalog_value.records(selected)[0]
            result = {
                "scenario_id": record.scenario_id,
                "name": record.name,
                "industry": record.industry,
                "status": record.status,
                "tools": list(record.tools),
                "vulnerabilities": list(record.vulnerabilities),
                "import_error": record.import_error,
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "finvault-dataset":
        cases = _finvault_catalog().load_cases(
            args.dataset,
            args.scenario,
            family=args.family,
        )
        print(
            json.dumps(
                {
                    "dataset": args.dataset,
                    "scenario_id": args.scenario,
                    "family": args.family,
                    "case_count": len(cases),
                    "multi_turn_cases": sum(len(case.follow_up_prompts) > 0 for case in cases),
                    "turn_count": sum(len(case.turns) for case in cases),
                    "properties": sorted({case.property_id for case in cases}),
                    "source_files": sorted({str(case.source_path) for case in cases}),
                    "source_sha256": sorted({case.source_sha256 for case in cases}),
                },
                sort_keys=True,
            )
        )
    elif args.command == "finvault-design":
        catalog_value = _finvault_catalog()
        design = load_dynamic_design(CONFIG.raw, CONFIG.root, catalog_value)
        print(json.dumps(design.summary(catalog_value), sort_keys=True))
    elif args.command == "finvault-audit":
        print(json.dumps(audit_all_interfaces(_finvault_catalog()), sort_keys=True))
    elif args.command == "describe":
        from .pilot import describe as describe_design

        print(json.dumps(describe_design(), indent=2, sort_keys=True))
    elif args.command == "prepare":
        from .pilot import prepare as prepare_stimuli

        summary = prepare_stimuli(
            limit=args.limit,
            reuse=not args.no_reuse,
            require_reviewed=args.require_reviewed,
        )
        # Counts, identifiers and hashes only; never stimulus text.
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not summary["authoring"]["complete"]:
            raise SystemExit(1)
    elif args.command == "validate":
        print(json.dumps(_validate(), sort_keys=True))
    elif args.command == "status":
        print(json.dumps(_status(), sort_keys=True))
    elif args.command == "freeze":
        if CONFIG.frozen:
            raise RuntimeError("select the editable root experiment before freezing")
        if CONFIG.status != "ready":
            raise RuntimeError("experiment.json status must be ready before freezing")
        _validate()
        result = freeze_experiment(args.shards)
        print(
            json.dumps(
                {
                    "experiment_id": result["experiment_id"],
                    "package_id": result["package_id"],
                    "manifest_sha256": result["manifest_sha256"],
                    "plans": result["plans"],
                    "shards_per_phase": result["shards_per_phase"],
                },
                sort_keys=True,
            )
        )
    elif args.command == "verify-package":
        result = verify_package(_run_path(args.run))
        print(json.dumps({"package_id": result["package_id"], "verified": True}, sort_keys=True))
    elif args.command == "worker":
        run_dir = _run_path(args.run)
        verify_package(run_dir)
        result = run_worker(
            _runtimes(),
            run_dir,
            args.phase,
            args.shard,
            args.worker_id,
        )
        print(json.dumps(result, sort_keys=True))
    elif args.command == "collect":
        result = collect_phase(_run_path(args.run), args.phase)
        print(json.dumps(result, sort_keys=True))
    elif args.command == "analyze":
        manifest = verify_package(_run_path(args.run))
        _require_complete_pilot(manifest)
        result = analyze()
        print(json.dumps({"decision": result["decision"], "rows": result["rows"]}, sort_keys=True))
    elif args.command == "run-local":
        print(json.dumps(_run_local(_run_path(args.run), args.worker_id), sort_keys=True))
    else:
        if CONFIG.frozen:
            raise RuntimeError("corpus authoring is disabled inside a frozen package")
        result = author_stimuli(_runtime("author"), force=args.force)
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
