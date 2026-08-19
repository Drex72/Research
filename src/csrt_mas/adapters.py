"""Choose the execution adapter for one stimulus, without guessing.

The runner used to import ``FinVaultAdapter`` directly, and that adapter does
``from sandbox_00.environment import CreditLoanEnvironment`` at module scope.
Two consequences followed. Importing the runner imported scenario 00's sandbox
whether or not it was the scenario under test, and every stimulus was executed
against that one environment. A case drawn from scenario 13 was scored by
scenario 00's tools and vulnerability oracle, which is not a weaker measurement
but a meaningless one.

This module resolves the adapter from the stimulus instead. A stimulus that
names its scenario runs in that scenario. A stimulus that names none is an
error, unless the caller explicitly asks for the legacy single-sandbox path.
There is no fallback: an unresolvable stimulus raises rather than quietly
executing somewhere else, because a silently misrouted run produces numbers
that look valid.

``FinVaultAdapter`` is imported lazily, inside the legacy branch only, so
importing this module never pulls in ``sandbox_00``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .config import CONFIG
from .finvault_dynamic.catalog import DatasetCase, FinVaultCatalog, FinVaultCatalogError
from .finvault_dynamic.runtime import DynamicFinVaultAdapter


# The scenario the legacy adapter is hardwired to, and its terminal tools. The
# runner previously carried this tool set as a literal, which is the same
# scenario-00 assumption in a second place.
LEGACY_SCENARIO_ID = "00"
LEGACY_TERMINAL_TOOLS = ("approve_loan", "reject_loan", "escalate_to_human")


class AdapterResolutionError(RuntimeError):
    """The stimulus does not say which scenario it belongs to, or it cannot run."""


@runtime_checkable
class ScenarioAdapter(Protocol):
    """What the runner needs from an adapter, whichever one it gets."""

    @property
    def scenario_id(self) -> str: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def terminal_tools(self) -> tuple[str, ...]: ...

    def trusted_evidence(self) -> dict[str, Any]: ...

    def execute(self, action: dict[str, Any]) -> Any: ...


# ---------------------------------------------------------------------------
# catalog and case lookup
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def default_catalog() -> FinVaultCatalog:
    """The catalog described by the active experiment configuration.

    The integration root is the directory holding ``scenario.json`` and
    ``specs/``. It is taken from the resolved scenario path rather than from
    ``CONFIG.scenario_id``, which is the FinVault *instance* number ("00") and
    not a folder name.
    """
    return FinVaultCatalog(
        Path(CONFIG.finvault_root), Path(CONFIG.scenario.path).parent
    )


@lru_cache(maxsize=256)
def _cases(
    catalog: FinVaultCatalog, dataset: str, scenario_id: str, family: str | None
) -> dict[str, DatasetCase]:
    return {
        case.case_id: case
        for case in catalog.load_cases(dataset, scenario_id, family=family)
    }


def case_provenance(stimulus: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """Read ``(scenario_id, dataset, case_id, family)`` off a stimulus.

    Pure and catalog-free, so a stimulus missing provenance fails with that
    reason rather than with whatever the catalog complains about first.
    """
    label = stimulus.get("semantic_id", "<unknown>")
    scenario_id = stimulus.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise AdapterResolutionError(
            f"stimulus {label!r} does not name a scenario_id; it cannot be "
            "executed without one"
        )
    dataset = stimulus.get("dataset")
    if not isinstance(dataset, str) or not dataset.strip():
        raise AdapterResolutionError(f"stimulus {label!r} does not name a dataset")
    case_id = stimulus.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise AdapterResolutionError(f"stimulus {label!r} does not name a case_id")
    family = stimulus.get("family")
    if family is not None and not isinstance(family, str):
        raise AdapterResolutionError(f"stimulus {label!r} has a non-string family")
    return scenario_id.strip(), dataset.strip(), case_id.strip(), family


def resolve_case(stimulus: dict[str, Any], catalog: FinVaultCatalog) -> DatasetCase:
    """Find the dataset case a stimulus was built from.

    The stimulus must carry enough provenance to name exactly one case. Missing
    provenance is an error here rather than a default, because the default is
    what routed scenario 13 into scenario 00's sandbox.
    """
    scenario_id, dataset, case_id, family = case_provenance(stimulus)
    try:
        table = _cases(catalog, dataset, scenario_id, family)
    except FinVaultCatalogError as exc:
        raise AdapterResolutionError(
            f"cannot load {dataset} scenario {scenario_id}"
            + (f" family {family}" if family else "")
            + f": {exc}"
        ) from exc
    case = table.get(case_id)
    if case is None:
        raise AdapterResolutionError(
            f"case {case_id!r} is not in {dataset} scenario {scenario_id}"
            + (f" family {family}" if family else "")
        )
    return case


# ---------------------------------------------------------------------------
# the legacy adapter, wrapped to the same interface
# ---------------------------------------------------------------------------


class DynamicAdapterView:
    """``DynamicFinVaultAdapter`` behind the shared interface.

    It carries its scenario on ``case.scenario_id`` rather than on itself, so a
    thin view supplies the attribute the runner records. Wrapping here keeps
    the interface adaptation in one place instead of editing the scenario
    runtime.
    """

    def __init__(self, inner: DynamicFinVaultAdapter) -> None:
        self._inner = inner

    @property
    def scenario_id(self) -> str:
        return self._inner.case.scenario_id

    @property
    def system_prompt(self) -> str:
        return self._inner.system_prompt

    @property
    def terminal_tools(self) -> tuple[str, ...]:
        return tuple(self._inner.terminal_tools)

    @property
    def available_tools(self) -> tuple[str, ...]:
        return tuple(self._inner.available_tools)

    def trusted_evidence(self) -> dict[str, Any]:
        return self._inner.trusted_evidence()

    def execute(self, action: dict[str, Any]) -> Any:
        return self._inner.execute(action)


class LegacyFinVaultAdapter:
    """The original scenario-00 adapter, behind the shared interface.

    Kept so frozen v1 packages stay reproducible. It is never selected
    implicitly: the caller has to ask for it and the stimulus has to be from
    scenario 00.
    """

    def __init__(self, stimulus: dict[str, Any], text: str) -> None:
        from .finvault import FinVaultAdapter  # imported here so sandbox_00 stays lazy

        self._inner = FinVaultAdapter(stimulus, text)

    @property
    def scenario_id(self) -> str:
        return LEGACY_SCENARIO_ID

    @property
    def system_prompt(self) -> str:
        return self._inner.system_prompt

    @property
    def terminal_tools(self) -> tuple[str, ...]:
        return LEGACY_TERMINAL_TOOLS

    def trusted_evidence(self) -> dict[str, Any]:
        return self._inner.trusted_evidence()

    def execute(self, action: dict[str, Any]) -> Any:
        return self._inner.execute(action)


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def resolve_adapter(
    stimulus: dict[str, Any],
    text: str,
    *,
    catalog: FinVaultCatalog | None = None,
    allow_legacy: bool = False,
    allow_exploratory: bool = False,
) -> ScenarioAdapter:
    """Build the adapter this stimulus must run in.

    ``allow_legacy`` permits the original scenario-00 adapter for stimuli that
    predate scenario provenance. It still refuses a stimulus that names a
    different scenario, so a v1 package cannot be replayed against scenario 13
    by accident.

    ``allow_exploratory`` lets a scenario run before its spec is marked
    conclusion-ready. Use it to look, never to report.
    """
    scenario_id = stimulus.get("scenario_id")

    if allow_legacy and (scenario_id is None or scenario_id == LEGACY_SCENARIO_ID):
        return LegacyFinVaultAdapter(stimulus, text)

    if allow_legacy and scenario_id != LEGACY_SCENARIO_ID:
        raise AdapterResolutionError(
            f"legacy execution was requested but stimulus "
            f"{stimulus.get('semantic_id', '<unknown>')!r} belongs to scenario "
            f"{scenario_id!r}; the legacy adapter only implements scenario "
            f"{LEGACY_SCENARIO_ID}"
        )

    # Validate provenance before touching the catalog, so a stimulus that never
    # named its scenario fails with that reason and not with a catalog error.
    case_provenance(stimulus)
    resolved = catalog or default_catalog()
    case = resolve_case(stimulus, resolved)
    try:
        return DynamicAdapterView(
            DynamicFinVaultAdapter(
                resolved, case, allow_exploratory=allow_exploratory
            )
        )
    except FinVaultCatalogError as exc:
        raise AdapterResolutionError(
            f"scenario {case.scenario_id} cannot execute case {case.case_id}: {exc}"
        ) from exc
