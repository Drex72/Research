#!/usr/bin/env python3
"""Prove the runner routes each stimulus to its own scenario.

Standard library plus the repo. No model calls, no network. Run from the repo
root:

    python3 scripts/check_adapter_routing.py

Every check is a claim that was false before the adapter resolver existed.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS  " if condition else "FAIL  ") + name + (
        "" if condition else f"\n        {detail}"
    ))
    if not condition:
        failures.append(name)


def stimulus(**overrides):
    """A stimulus row shaped the way the runner reads one."""
    row = {
        "semantic_id": "probe-001",
        "pair_id": "probe",
        "property_id": "V1_limit_bypass",
        "frame": "authority_impersonation",
        "intent": "adversarial",
        "texts": {"EN": "text"},
        "text_sha256": {"EN": "0" * 64},
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. importing the runner must not import scenario 00's sandbox
# ---------------------------------------------------------------------------

import csrt_mas.runner  # noqa: E402,F401

check(
    "importing the runner does not import sandbox_00",
    "sandbox_00.environment" not in sys.modules,
    f"loaded: {[m for m in sys.modules if m.startswith('sandbox_')]}",
)
check(
    "importing the runner does not import the legacy adapter module",
    "csrt_mas.finvault" not in sys.modules,
)

from csrt_mas.adapters import (  # noqa: E402
    AdapterResolutionError,
    default_catalog,
    resolve_adapter,
    resolve_case,
)

# ---------------------------------------------------------------------------
# 2. a stimulus with no provenance is refused, not defaulted
# ---------------------------------------------------------------------------

for name, row in (
    ("no scenario_id", stimulus()),
    ("no dataset", stimulus(scenario_id="13", case_id="x")),
    ("no case_id", stimulus(scenario_id="13", dataset="attack_datasets")),
):
    try:
        resolve_adapter(row, "text")
        check(f"refuses a stimulus with {name}", False, "it resolved something")
    except AdapterResolutionError as exc:
        check(f"refuses a stimulus with {name}", True)
    except Exception as exc:  # noqa: BLE001
        check(f"refuses a stimulus with {name}", False, f"{type(exc).__name__}: {exc}")

# ---------------------------------------------------------------------------
# 3. the legacy adapter refuses a stimulus from another scenario
# ---------------------------------------------------------------------------

try:
    resolve_adapter(stimulus(scenario_id="13"), "text", allow_legacy=True)
    check("legacy adapter refuses a scenario-13 stimulus", False, "it accepted it")
except AdapterResolutionError as exc:
    check(
        "legacy adapter refuses a scenario-13 stimulus",
        "only implements scenario" in str(exc),
        str(exc),
    )

# ---------------------------------------------------------------------------
# 4. real cases resolve to their own scenario
# ---------------------------------------------------------------------------

try:
    catalog = default_catalog()
except Exception as exc:  # noqa: BLE001
    print(f"\nSKIPPED the catalog checks: {type(exc).__name__}: {exc}")
    catalog = None

if catalog is not None:
    print(f"\n  scenarios available : {len(catalog.scenario_ids)}")
    print(f"  synthesis families  : {len(catalog.synthesis_families)}")

    for scenario_id in ("00", "13"):
        try:
            cases = catalog.load_cases("attack_datasets", scenario_id)
        except Exception as exc:  # noqa: BLE001
            check(f"loads scenario {scenario_id} cases", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"loads scenario {scenario_id} cases", bool(cases), "no cases returned")
        if not cases:
            continue
        case = cases[0]
        row = stimulus(
            semantic_id=f"probe-{scenario_id}",
            scenario_id=scenario_id,
            dataset="attack_datasets",
            case_id=case.case_id,
            property_id=case.property_id,
        )
        resolved = resolve_case(row, catalog)
        check(
            f"scenario {scenario_id} stimulus resolves to a scenario {scenario_id} case",
            resolved.scenario_id == scenario_id and resolved.case_id == case.case_id,
            f"got {resolved.scenario_id}/{resolved.case_id}",
        )

        spec = catalog.spec(scenario_id, required=False)
        if spec is not None:
            check(
                f"scenario {scenario_id} declares its own terminal tools",
                bool(spec.terminal_tools),
                "spec has no terminal_tools",
            )

    # a case id from one scenario must not resolve inside another
    try:
        first = catalog.load_cases("attack_datasets", "00")[0]
        resolve_case(
            stimulus(scenario_id="13", dataset="attack_datasets", case_id=first.case_id),
            catalog,
        )
        check("a scenario-00 case id does not resolve inside scenario 13", False,
              "it resolved")
    except AdapterResolutionError:
        check("a scenario-00 case id does not resolve inside scenario 13", True)
    except Exception as exc:  # noqa: BLE001
        check("a scenario-00 case id does not resolve inside scenario 13", False,
              f"{type(exc).__name__}: {exc}")

    # spec gating: an unvalidated scenario must not run conclusion-bearing
    unvalidated = [
        s for s in catalog.scenario_ids
        if (catalog.spec(s, required=False) is None
            or not catalog.spec(s, required=False).conclusion_ready)
    ]
    print(f"  scenarios without a conclusion-ready spec : {len(unvalidated)}"
          f" of {len(catalog.scenario_ids)}")

# ---------------------------------------------------------------------------
# 5. the terminal-tool set is no longer a literal in the runner
# ---------------------------------------------------------------------------

runner_source = (ROOT / "src" / "csrt_mas" / "runner.py").read_text(encoding="utf-8")
check(
    "runner no longer hardcodes scenario 00's terminal tools",
    '{"approve_loan", "reject_loan", "escalate_to_human"}' not in runner_source,
)
check(
    "runner takes terminal tools from the adapter",
    "adapter.terminal_tools" in runner_source,
)
check(
    "runner records which scenario actually executed",
    '"scenario_id": adapter.scenario_id' in runner_source,
)

print(f"\nRESULT: {len(failures)} failed")
sys.exit(1 if failures else 0)
