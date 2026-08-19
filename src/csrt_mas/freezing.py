from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG, FINVAULT_COMMIT, FINVAULT_ROOT, FRAMES, ROOT
from .finvault import validate_executor_tools
from .finvault_dynamic import FinVaultCatalog, load_dynamic_design
from .qualification import validate_qualification_stimuli
from .runner import make_plan
from .settings import load_outcome_rules, load_pipeline_set, load_prompt_set
from .stimuli import validate_stimuli


RUNTIME_DISTRIBUTIONS = ("csrt-mas-pilot", "gymnasium", "python-dotenv", "PyYAML")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path = ROOT) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _safe_child(root: Path, relative: str, name: str) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise RuntimeError(f"{name} path must be relative")
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"{name} path escapes its root: {relative}") from exc
    return resolved


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_jsonl(path: Path, name: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unable to read frozen {name}: {path}") from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError(f"frozen {name} must contain JSON objects")
    return rows


def verify_upstream_revision() -> str:
    try:
        observed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=FINVAULT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to verify the configured FinVault checkout") from exc
    if observed != FINVAULT_COMMIT:
        raise RuntimeError(
            f"FinVault revision mismatch: configured {FINVAULT_COMMIT}, observed {observed}"
        )
    return observed


def _repository_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to identify the project Git revision") from exc


def _python_packages() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in RUNTIME_DISTRIBUTIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"required Python distribution is not installed: {distribution}") from exc
    return versions


def project_dependency_files() -> list[Path]:
    catalog = FinVaultCatalog(FINVAULT_ROOT, ROOT / "scenarios" / "finvault")
    design = load_dynamic_design(CONFIG.raw, CONFIG.root, catalog)
    dynamic: list[Path] = [
        ROOT / "scenarios" / "finvault" / "registry.json",
        *(catalog.spec(scenario_id, required=True).path for scenario_id in design.scenario_ids),
        *(agent.path for agent in design.agents.values()),
        *(profile.path for profile in design.surfaces.values()),
        *(pipeline.path for pipeline in design.graph_pipelines),
    ]
    for agent in design.agents.values():
        dynamic.extend(
            [
                ROOT / agent.model_profile,
                ROOT / agent.system_prompt,
            ]
        )
    for pipeline in design.graph_pipelines:
        dynamic.extend(
            ROOT / edge.template
            for edge in pipeline.edges
            if edge.template is not None
        )
    for scenario_id in design.scenario_ids:
        dynamic.extend(
            [
                FINVAULT_ROOT / "sandbox" / "prompts" / f"prompt_{scenario_id}.py",
                *sorted(
                    (FINVAULT_ROOT / "sandbox" / f"sandbox_{scenario_id}").rglob("*.py")
                ),
            ]
        )
        for family in design.families or (None,):
            dynamic.append(catalog.dataset_path(design.dataset, scenario_id, family=family))
        if design.include_normal_controls:
            dynamic.append(catalog.dataset_path("normal_datasets", scenario_id))
    upstream = [
        FINVAULT_ROOT / "sandbox" / "normal_datasets" / "scenario_00_normal.json",
        *[
            FINVAULT_ROOT / "sandbox" / "attack_datasets_synthesis" / frame / "scenario_00_attacks.json"
            for frame in FRAMES
        ],
        FINVAULT_ROOT / "sandbox" / "prompts" / "prompt_00.py",
        *sorted((FINVAULT_ROOT / "sandbox" / "base").rglob("*.py")),
        *sorted((FINVAULT_ROOT / "sandbox" / "sandbox_00").rglob("*.py")),
    ]
    return list(dict.fromkeys([
        ROOT / "pyproject.toml",
        *sorted((ROOT / "src" / "csrt_mas").rglob("*.py")),
        *sorted((ROOT / "src" / "csrt_codeswitch").rglob("*.py")),
        ROOT / "src" / "csrt_codeswitch" / "languages.json",
        *sorted((ROOT / "tests").rglob("*.py")),
        *upstream,
        *dynamic,
    ]))


def mutable_input_files() -> list[Path]:
    prompts = load_prompt_set(CONFIG)
    pipelines = load_pipeline_set(CONFIG)
    profiles = {agent.profile.path for agent in CONFIG.agents.values()}
    return sorted(
        {
            CONFIG.path,
            CONFIG.scenario.path,
            CONFIG.stimuli_path,
            CONFIG.qualification_stimuli_path,
            CONFIG.outcome_rules_path,
            CONFIG.protocol_path,
            *prompts.files,
            *pipelines.files,
            *profiles,
        }
    )


def _copy(path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def _copy_package_resources(stage: Path, final_run: Path, package_id: str) -> Path:
    package = stage / "package"
    prompts = load_prompt_set(CONFIG)
    pipelines = load_pipeline_set(CONFIG)

    prompt_dir = package / "prompts"
    _copy(prompts.path, prompt_dir / "prompt-set.json")
    for prompt_path in prompts.prompt_paths.values():
        _copy(prompt_path, prompt_dir / prompt_path.relative_to(prompts.path.parent))
    if prompts.override_path is not None:
        _copy(prompts.override_path, prompt_dir / prompts.override_path.relative_to(prompts.path.parent))

    profile_targets: dict[Path, Path] = {}
    for agent in CONFIG.agents.values():
        profile_targets.setdefault(agent.profile.path, package / "models" / f"{agent.profile.profile_id}.json")
    for source, target in profile_targets.items():
        _copy(source, target)

    pipeline_targets: dict[str, Path] = {}
    for pipeline_id, pipeline in pipelines.pipelines.items():
        target = package / "pipelines" / f"{pipeline_id}.json"
        _copy(pipeline.path, target)
        pipeline_targets[pipeline_id] = target

    scenario_dir = package / "scenario"
    _copy(CONFIG.stimuli_path, scenario_dir / "cases.jsonl")
    _copy(CONFIG.qualification_stimuli_path, scenario_dir / "qualification.jsonl")
    _copy(CONFIG.outcome_rules_path, scenario_dir / "outcome-rules.json")
    scenario_raw = json.loads(CONFIG.scenario.path.read_text(encoding="utf-8"))
    scenario_raw["data"].update(
        {
            "cases": _relative(final_run / "package" / "scenario" / "cases.jsonl"),
            "qualification_cases": _relative(final_run / "package" / "scenario" / "qualification.jsonl"),
            "outcome_rules": _relative(final_run / "package" / "scenario" / "outcome-rules.json"),
        }
    )
    _write_json(scenario_dir / "scenario.json", scenario_raw)

    _copy(CONFIG.protocol_path, package / "protocol" / "METHODS.md")

    experiment = json.loads(CONFIG.path.read_text(encoding="utf-8"))
    experiment.update({"frozen": True, "package_id": package_id, "status": "ready"})
    experiment["scenario"] = _relative(final_run / "package" / "scenario" / "scenario.json")
    experiment["prompt_set"] = _relative(final_run / "package" / "prompts" / "prompt-set.json")
    experiment["pipelines"] = [
        _relative(final_run / "package" / "pipelines" / f"{pipeline_id}.json")
        for pipeline_id in pipelines.pipelines
    ]
    for role, agent in CONFIG.agents.items():
        experiment["agents"][role]["model_profile"] = _relative(
            final_run / "package" / "models" / f"{agent.profile.profile_id}.json"
        )
    experiment["protocol"] = _relative(final_run / "package" / "protocol" / "METHODS.md")
    frozen_path = package / "experiment.json"
    _write_json(frozen_path, experiment)
    return frozen_path


def shard_plan(units: list[dict[str, Any]], count: int) -> list[list[dict[str, Any]]]:
    if count < 1:
        raise ValueError("shard count must be at least one")
    if count > len(units):
        raise ValueError("shard count cannot exceed the number of planned units")
    shards = [[] for _ in range(count)]
    for index, unit in enumerate(units):
        shards[index % count].append(unit)
    return shards


def _write_shards(stage: Path, phase: str, units: list[dict[str, Any]], count: int) -> list[Path]:
    paths: list[Path] = []
    for index, shard in enumerate(shard_plan(units, count)):
        path = stage / "shards" / phase / f"shard-{index:03d}.jsonl"
        _write_jsonl(path, shard)
        paths.append(path)
    return paths


def freeze_experiment(shard_count: int | None = None) -> dict[str, Any]:
    if CONFIG.frozen:
        raise RuntimeError("a frozen package cannot be frozen again")
    if CONFIG.status != "ready":
        raise RuntimeError("experiment.json status must be ready before freezing")
    if CONFIG.output_dir.exists():
        raise FileExistsError(f"run directory already exists: {CONFIG.output_dir}")

    verify_upstream_revision()
    validate_executor_tools()
    validate_stimuli()
    validate_qualification_stimuli()
    load_outcome_rules(CONFIG)
    mutable = mutable_input_files()
    dependencies = project_dependency_files()
    missing = [path for path in [*mutable, *dependencies] if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing freeze inputs: {[str(path) for path in missing]}")

    source_hashes = {_relative(path): sha256_file(path) for path in mutable}
    dependency_hashes = {_relative(path): sha256_file(path) for path in dependencies}
    package_id = sha256_bytes(
        canonical(
            {
                "experiment_id": CONFIG.experiment_id,
                "project_commit": _repository_commit(),
                "source_inputs": source_hashes,
                "project_dependencies": dependency_hashes,
            }
        )
    )
    count = CONFIG.default_shards if shard_count is None else shard_count
    runs_root = CONFIG.output_dir.parent
    runs_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{CONFIG.experiment_id}-", dir=runs_root))
    try:
        _copy_package_resources(stage, CONFIG.output_dir, package_id)
        gate = make_plan("gate", stage / "plans" / "gate.jsonl", package_id=package_id)
        pilot = make_plan("pilot", stage / "plans" / "pilot.jsonl", package_id=package_id)
        _write_shards(stage, "gate", gate, count)
        _write_shards(stage, "pilot", pilot, count)

        run_files = sorted(
            path for path in stage.rglob("*") if path.is_file() and path.name != "frozen-manifest.json"
        )
        manifest = {
            "schema_version": 1,
            "package_id": package_id,
            "experiment_id": CONFIG.experiment_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "project_commit": _repository_commit(),
            "upstream_commit": FINVAULT_COMMIT,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_packages": _python_packages(),
            "outcomes_observed_before_freeze": False,
            "research": {
                "title": CONFIG.metadata.title,
                "aim": CONFIG.metadata.aim,
                "research_question": CONFIG.metadata.research_question,
                "hypothesis": CONFIG.metadata.hypothesis,
                "domain": CONFIG.metadata.domain,
                "risk_outcomes": list(CONFIG.metadata.risk_outcomes),
                "tags": list(CONFIG.metadata.tags),
                "parent_experiment": CONFIG.metadata.parent_experiment,
            },
            "configuration": {
                "scenario": CONFIG.scenario.scenario_id,
                "languages": list(CONFIG.surfaces),
                "pipelines": list(CONFIG.pipeline_ids),
            },
            "models": {
                role: {
                    "profile_id": agent.profile.profile_id,
                    "provider": agent.provider,
                    "model": agent.model,
                    "digest": agent.digest,
                }
                for role, agent in CONFIG.agents.items()
            },
            "plans": {"gate": len(gate), "pilot": len(pilot)},
            "shards_per_phase": count,
            "source_inputs": source_hashes,
            "files": {
                "run": {
                    str(path.relative_to(stage)): sha256_file(path)
                    for path in run_files
                },
                "project": dependency_hashes,
            },
        }
        _write_json(stage / "frozen-manifest.json", manifest)
        os.replace(stage, CONFIG.output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {**manifest, "manifest_sha256": sha256_file(CONFIG.manifest_path)}


def verify_package(run_dir: Path | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    run_dir = (run_dir or CONFIG.output_dir).resolve()
    manifest_path = run_dir / "frozen-manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"frozen manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported frozen manifest schema_version")
    package_id = manifest.get("package_id")
    if (
        not isinstance(package_id, str)
        or len(package_id) != 64
        or any(character not in "0123456789abcdef" for character in package_id.lower())
    ):
        raise RuntimeError("frozen manifest package_id is invalid")
    if manifest.get("experiment_id") != run_dir.name:
        raise RuntimeError("frozen manifest experiment_id differs from the run directory")
    expected_packages = manifest.get("python_packages")
    if not isinstance(expected_packages, dict) or not expected_packages:
        raise RuntimeError("frozen manifest Python package inventory is missing")
    if _python_packages() != expected_packages:
        raise RuntimeError("installed Python packages differ from the frozen manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not all(
        isinstance(files.get(scope), dict) and files[scope] for scope in ("run", "project")
    ):
        raise RuntimeError("frozen manifest file inventories are missing")
    failures: list[str] = []
    for scope, base in (("run", run_dir), ("project", root)):
        for relative, expected in manifest.get("files", {}).get(scope, {}).items():
            candidate = _safe_child(base, relative, f"manifest {scope}")
            if not candidate.exists() or sha256_file(candidate) != expected:
                failures.append(f"{scope}:{relative}")
    if failures:
        raise RuntimeError(f"frozen package checksum mismatch: {failures}")

    plan_counts = manifest.get("plans")
    shard_count = manifest.get("shards_per_phase")
    if (
        not isinstance(plan_counts, dict)
        or set(plan_counts) != {"gate", "pilot"}
        or not all(isinstance(plan_counts[phase], int) and plan_counts[phase] > 0 for phase in plan_counts)
        or not isinstance(shard_count, int)
        or shard_count < 1
    ):
        raise RuntimeError("frozen manifest plan or shard inventory is invalid")
    run_inventory = files["run"]
    required = {"package/experiment.json"}
    for phase in ("gate", "pilot"):
        required.add(f"plans/{phase}.jsonl")
        required.update(
            f"shards/{phase}/shard-{index:03d}.jsonl" for index in range(shard_count)
        )
    if not required.issubset(run_inventory):
        raise RuntimeError("frozen manifest omits required package, plan, or shard files")

    frozen_experiment = json.loads((run_dir / "package" / "experiment.json").read_text(encoding="utf-8"))
    if (
        frozen_experiment.get("frozen") is not True
        or frozen_experiment.get("status") != "ready"
        or frozen_experiment.get("experiment_id") != manifest["experiment_id"]
        or frozen_experiment.get("package_id") != package_id
    ):
        raise RuntimeError("frozen experiment metadata differs from the manifest")
    for phase in ("gate", "pilot"):
        plan = _read_jsonl(run_dir / "plans" / f"{phase}.jsonl", f"{phase} plan")
        if len(plan) != plan_counts[phase]:
            raise RuntimeError(f"frozen {phase} plan count differs from the manifest")
        planned_ids = [row.get("run_unit_id") for row in plan]
        if (
            any(row.get("phase") != phase or row.get("package_id") != package_id for row in plan)
            or any(not isinstance(value, str) or not value for value in planned_ids)
            or len(set(planned_ids)) != len(planned_ids)
        ):
            raise RuntimeError(f"frozen {phase} plan metadata is invalid")
        sharded_ids: list[str] = []
        for index in range(shard_count):
            shard = _read_jsonl(
                run_dir / "shards" / phase / f"shard-{index:03d}.jsonl",
                f"{phase} shard",
            )
            sharded_ids.extend(str(row.get("run_unit_id")) for row in shard)
        if sorted(sharded_ids) != sorted(planned_ids):
            raise RuntimeError(f"frozen {phase} shards do not exactly partition the plan")
    if CONFIG.frozen:
        if CONFIG.package_id != manifest.get("package_id"):
            raise RuntimeError("active frozen experiment and manifest package IDs differ")
        expected_config = (run_dir / "package" / "experiment.json").resolve()
        if CONFIG.path.resolve() != expected_config:
            raise RuntimeError("active configuration is not the run package experiment")
    return {**manifest, "manifest_sha256": sha256_file(manifest_path)}
