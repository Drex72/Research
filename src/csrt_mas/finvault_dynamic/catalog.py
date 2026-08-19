from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCENARIO_ID = re.compile(r"^\d{2}$")
DATASET_NAMES = {
    "attack_datasets",
    "attack_datasets_synthesis",
    "normal_datasets",
}
CASE_KEYS = ("attacks", "queries", "scenarios", "attack_cases")


class FinVaultCatalogError(ValueError):
    """Raised when a FinVault resource cannot be resolved safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FinVaultCatalogError(f"{name} does not exist: {path}") from None
    except json.JSONDecodeError as exc:
        raise FinVaultCatalogError(f"{name} is invalid JSON: {path}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise FinVaultCatalogError(f"{name} must contain a JSON object: {path}")
    return value


def _scenario_id(value: str) -> str:
    value = str(value)
    if not SCENARIO_ID.fullmatch(value):
        raise FinVaultCatalogError(f"scenario ID must be two digits: {value}")
    return value


def _case_rows(value: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    for key in CASE_KEYS:
        rows = value.get(key)
        if isinstance(rows, list):
            if not all(isinstance(row, dict) for row in rows):
                raise FinVaultCatalogError(f"{path}:{key} must contain JSON objects")
            return rows
    raise FinVaultCatalogError(f"{path} has no supported case collection: {CASE_KEYS}")


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    status: str
    terminal_tools: tuple[str, ...]
    language_oracle_audit: str
    utility_rules: dict[str, dict[str, Any]]
    hook: str | None
    path: Path

    @property
    def conclusion_ready(self) -> bool:
        return self.status == "validated"


@dataclass(frozen=True)
class ScenarioRecord:
    scenario_id: str
    name: str
    industry: str
    tools: tuple[str, ...]
    vulnerabilities: tuple[str, ...]
    status: str
    spec_path: Path | None
    import_error: str | None = None


@dataclass(frozen=True)
class DatasetCase:
    scenario_id: str
    dataset: str
    family: str | None
    case_id: str
    property_id: str
    prompt: str
    follow_up_prompts: tuple[str, ...]
    source_path: Path
    source_sha256: str
    raw: dict[str, Any]

    @property
    def turns(self) -> tuple[str, ...]:
        return (self.prompt, *self.follow_up_prompts)


class FinVaultCatalog:
    """Resolve upstream FinVault resources without modifying the vendor tree."""

    def __init__(self, finvault_root: Path, integration_root: Path):
        self.finvault_root = finvault_root.resolve()
        self.sandbox_root = self.finvault_root / "sandbox"
        self.integration_root = integration_root.resolve()
        if not self.sandbox_root.is_dir():
            raise FinVaultCatalogError(f"FinVault sandbox root does not exist: {self.sandbox_root}")
        if not self.integration_root.is_dir():
            raise FinVaultCatalogError(
                f"FinVault integration root does not exist: {self.integration_root}"
            )

    @property
    def synthesis_families(self) -> tuple[str, ...]:
        root = self.sandbox_root / "attack_datasets_synthesis"
        return tuple(sorted(path.name for path in root.iterdir() if path.is_dir()))

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name.removeprefix("sandbox_")
                for path in self.sandbox_root.glob("sandbox_[0-9][0-9]")
                if path.is_dir() and SCENARIO_ID.fullmatch(path.name.removeprefix("sandbox_"))
            )
        )

    def spec(self, scenario_id: str, *, required: bool = False) -> ScenarioSpec | None:
        scenario_id = _scenario_id(scenario_id)
        path = self.integration_root / "specs" / f"{scenario_id}.json"
        if not path.exists():
            if required:
                raise FinVaultCatalogError(
                    f"scenario {scenario_id} is discovered but has no CSRT integration specification"
                )
            return None
        raw = _read_json(path, f"scenario {scenario_id} specification")
        if raw.get("schema_version") != 1:
            raise FinVaultCatalogError(f"unsupported scenario specification schema: {path}")
        if raw.get("scenario_id") != scenario_id:
            raise FinVaultCatalogError(f"scenario specification ID mismatch: {path}")
        status = raw.get("status")
        if status not in {"integrated", "validated"}:
            raise FinVaultCatalogError(f"invalid scenario integration status in {path}")
        terminal = raw.get("terminal_tools", [])
        if not isinstance(terminal, list) or not all(
            isinstance(item, str) and item for item in terminal
        ):
            raise FinVaultCatalogError(f"terminal_tools must be a list of names: {path}")
        audit = raw.get("language_oracle_audit", "required")
        if audit not in {"passed", "required", "prompt_dependent"}:
            raise FinVaultCatalogError(f"invalid language_oracle_audit in {path}")
        utility_rules = raw.get("utility_rules", {})
        if not isinstance(utility_rules, dict) or not all(
            isinstance(key, str) and isinstance(value, dict)
            for key, value in utility_rules.items()
        ):
            raise FinVaultCatalogError(f"utility_rules must be an object: {path}")
        hook = raw.get("hook")
        if hook is not None and (not isinstance(hook, str) or not hook):
            raise FinVaultCatalogError(f"hook must be a non-empty import reference: {path}")
        return ScenarioSpec(
            scenario_id=scenario_id,
            status=status,
            terminal_tools=tuple(terminal),
            language_oracle_audit=audit,
            utility_rules=utility_rules,
            hook=hook,
            path=path,
        )

    def dataset_path(
        self,
        dataset: str,
        scenario_id: str,
        *,
        family: str | None = None,
    ) -> Path:
        scenario_id = _scenario_id(scenario_id)
        if dataset not in DATASET_NAMES:
            raise FinVaultCatalogError(f"unknown FinVault dataset: {dataset}")
        if dataset == "attack_datasets_synthesis":
            if family not in self.synthesis_families:
                raise FinVaultCatalogError(f"unknown synthesis family: {family}")
            path = (
                self.sandbox_root
                / dataset
                / str(family)
                / f"scenario_{scenario_id}_attacks.json"
            )
        elif dataset == "normal_datasets":
            if family is not None:
                raise FinVaultCatalogError("normal_datasets does not accept a synthesis family")
            path = self.sandbox_root / dataset / f"scenario_{scenario_id}_normal.json"
        else:
            if family is not None:
                raise FinVaultCatalogError("attack_datasets does not accept a synthesis family")
            path = self.sandbox_root / dataset / f"scenario_{scenario_id}_attacks.json"
        try:
            path.resolve().relative_to(self.sandbox_root)
        except ValueError as exc:
            raise FinVaultCatalogError("resolved dataset path escapes FinVault") from exc
        if not path.is_file():
            raise FinVaultCatalogError(f"FinVault dataset file does not exist: {path}")
        return path

    def load_cases(
        self,
        dataset: str,
        scenario_id: str,
        *,
        family: str | None = None,
    ) -> list[DatasetCase]:
        path = self.dataset_path(dataset, scenario_id, family=family)
        value = _read_json(path, f"{dataset} scenario {scenario_id}")
        rows = _case_rows(value, path)
        digest = _sha256(path)
        output: list[DatasetCase] = []
        for index, raw in enumerate(rows):
            prompt = raw.get("attack_prompt") or raw.get("query_prompt") or raw.get("attack_input")
            if not isinstance(prompt, str) or not prompt.strip():
                raise FinVaultCatalogError(f"{path}: case {index} has no prompt")
            case_id = raw.get("id") or raw.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise FinVaultCatalogError(f"{path}: case {index} has no ID")
            property_id = (
                raw.get("vulnerability")
                or raw.get("target_vulnerability")
                or raw.get("related_vulnerability")
                or ""
            )
            follow_ups = raw.get("follow_up_prompts", [])
            if follow_ups is None:
                follow_ups = []
            if not isinstance(follow_ups, list) or not all(
                isinstance(item, str) and item.strip() for item in follow_ups
            ):
                raise FinVaultCatalogError(f"{path}: {case_id} has invalid follow_up_prompts")
            output.append(
                DatasetCase(
                    scenario_id=_scenario_id(str(value.get("scenario_id", scenario_id))),
                    dataset=dataset,
                    family=family,
                    case_id=case_id,
                    property_id=str(property_id),
                    prompt=prompt,
                    follow_up_prompts=tuple(follow_ups),
                    source_path=path,
                    source_sha256=digest,
                    raw=dict(raw),
                )
            )
        return output

    def _import_scenario(self, scenario_id: str):
        scenario_id = _scenario_id(scenario_id)
        sandbox_path = str(self.sandbox_root)
        if sandbox_path not in sys.path:
            sys.path.insert(0, sandbox_path)
        return importlib.import_module(f"sandbox_{scenario_id}.scenario")

    def scenario_class(self, scenario_id: str):
        module = self._import_scenario(scenario_id)
        scenario = getattr(module, "Scenario", None)
        if scenario is None:
            raise FinVaultCatalogError(f"scenario {scenario_id} exports no Scenario class")
        return scenario

    def scenario_record(self, scenario_id: str) -> ScenarioRecord:
        scenario_id = _scenario_id(scenario_id)
        spec = self.spec(scenario_id)
        try:
            scenario = self.scenario_class(scenario_id)
            meta = scenario.get_meta()
            tools = tuple(sorted(str(item) for item in getattr(meta, "tools", []) or []))
            vulnerabilities = tuple(
                sorted(str(item) for item in getattr(meta, "vulnerabilities", []) or [])
            )
            return ScenarioRecord(
                scenario_id=scenario_id,
                name=str(getattr(meta, "scenario_name", f"Scenario {scenario_id}")),
                industry=str(getattr(meta, "industry", "")),
                tools=tools,
                vulnerabilities=vulnerabilities,
                status=spec.status if spec else "discovered",
                spec_path=spec.path if spec else None,
            )
        except Exception as exc:
            return ScenarioRecord(
                scenario_id=scenario_id,
                name=f"Scenario {scenario_id}",
                industry="",
                tools=(),
                vulnerabilities=(),
                status="discovery_error",
                spec_path=spec.path if spec else None,
                import_error=f"{type(exc).__name__}: {exc}",
            )

    def records(self, scenario_ids: Iterable[str] | None = None) -> list[ScenarioRecord]:
        selected = self.scenario_ids if scenario_ids is None else tuple(scenario_ids)
        return [self.scenario_record(value) for value in selected]

    def summary(self) -> dict[str, Any]:
        records = self.records()
        return {
            "scenario_count": len(records),
            "synthesis_families": list(self.synthesis_families),
            "status_counts": {
                status: sum(record.status == status for record in records)
                for status in sorted({record.status for record in records})
            },
            "scenarios": [
                {
                    "scenario_id": record.scenario_id,
                    "name": record.name,
                    "industry": record.industry,
                    "status": record.status,
                    "tool_count": len(record.tools),
                    "vulnerability_count": len(record.vulnerabilities),
                    "import_error": record.import_error,
                }
                for record in records
            ],
        }
