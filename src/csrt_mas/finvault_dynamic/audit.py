from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import FinVaultCatalog
from .runtime import create_environment, discover_tools


@dataclass(frozen=True)
class InterfaceAudit:
    scenario_id: str
    status: str
    module_import: bool
    metadata: bool
    synthesis_data: bool
    normal_data: bool
    environment_created: bool
    reset_with_case: bool
    tools_discovered: bool
    system_prompt: bool
    error: str | None

    @property
    def interface_ready(self) -> bool:
        return all(
            (
                self.module_import,
                self.metadata,
                self.synthesis_data,
                self.normal_data,
                self.environment_created,
                self.reset_with_case,
                self.tools_discovered,
                self.system_prompt,
            )
        )


def audit_interface(catalog: FinVaultCatalog, scenario_id: str) -> InterfaceAudit:
    checks: dict[str, bool] = {
        "module_import": False,
        "metadata": False,
        "synthesis_data": False,
        "normal_data": False,
        "environment_created": False,
        "reset_with_case": False,
        "tools_discovered": False,
        "system_prompt": False,
    }
    error: str | None = None
    record = catalog.scenario_record(scenario_id)
    try:
        scenario = catalog.scenario_class(scenario_id)
        checks["module_import"] = True
        scenario.get_meta()
        checks["metadata"] = True
        case = catalog.load_cases(
            "attack_datasets_synthesis",
            scenario_id,
            family=catalog.synthesis_families[0],
        )[0]
        checks["synthesis_data"] = True
        catalog.load_cases("normal_datasets", scenario_id)
        checks["normal_data"] = True
        env = create_environment(scenario)
        checks["environment_created"] = True
        raw = dict(case.raw)
        raw.setdefault("case_id", case.case_id)
        raw.setdefault("target_vulnerability", case.property_id)
        env.reset(options={"case_data": raw})
        checks["reset_with_case"] = True
        checks["tools_discovered"] = bool(discover_tools(env))
        checks["system_prompt"] = bool(str(scenario.get_system_prompt(False)).strip())
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return InterfaceAudit(
        scenario_id=scenario_id,
        status=record.status,
        error=error,
        **checks,
    )


def audit_all_interfaces(catalog: FinVaultCatalog) -> dict[str, Any]:
    audits = [audit_interface(catalog, scenario_id) for scenario_id in catalog.scenario_ids]
    return {
        "scenario_count": len(audits),
        "interface_ready_count": sum(audit.interface_ready for audit in audits),
        "not_interface_ready_count": sum(not audit.interface_ready for audit in audits),
        "warning": (
            "Interface readiness proves loading, reset, tools, and prompts only. "
            "It does not validate action oracles, legitimate utility, or language invariance."
        ),
        "scenarios": [
            {
                "scenario_id": audit.scenario_id,
                "status": audit.status,
                "interface_ready": audit.interface_ready,
                "checks": {
                    "module_import": audit.module_import,
                    "metadata": audit.metadata,
                    "synthesis_data": audit.synthesis_data,
                    "normal_data": audit.normal_data,
                    "environment_created": audit.environment_created,
                    "reset_with_case": audit.reset_with_case,
                    "tools_discovered": audit.tools_discovered,
                    "system_prompt": audit.system_prompt,
                },
                "error": audit.error,
            }
            for audit in audits
        ],
    }
