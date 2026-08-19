"""Resolve the right sandbox for the configured scenario.

This is the fix for the thing that makes the platform a scenario-00 wrapper
rather than a FinVault wrapper. ``csrt_mas.finvault`` does this at module
scope::

    from prompts.prompt_00 import SYSTEM_PROMPT
    from sandbox_00.environment import CreditLoanEnvironment

So importing it binds scenario 00's environment and prompt for the life of the
process, and a run configured for scenario 13 would still execute scenario 00's
world. FinVault ships everything needed to rebuild each scenario, and
``DynamicFinVaultAdapter`` already resolves it correctly through the catalog.
It simply had no caller.

This module is that caller. It takes a stimulus, reads the scenario it belongs
to, and returns an adapter bound to that scenario's environment, prompt, tools
and vulnerability checks. The legacy adapter is imported lazily and only when a
stimulus carries no scenario, so nothing about scenario 00 is loaded unless a
scenario-00 run asks for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class SandboxAdapter(Protocol):
    """What the runner needs from any scenario's sandbox."""

    @property
    def system_prompt(self) -> str: ...

    @property
    def available_tools(self) -> Sequence[str]: ...

    @property
    def terminal_tools(self) -> Sequence[str]: ...

    def trusted_evidence(self) -> Mapping[str, Any]: ...

    def execute(self, action: Mapping[str, Any]) -> Any: ...


class AdapterResolutionError(RuntimeError):
    """Raised when the scenario in a stimulus cannot be built."""


@dataclass
class AdapterFactory:
    """Builds one adapter per run unit, for whichever scenario it names.

    Holding the catalog rather than a scenario means a single run can span
    scenarios, which is what the matrix needs: ``dataset.scenarios`` is a list
    and always was.
    """

    catalog: Any
    allow_exploratory: bool = False
    allow_legacy: bool = False
    _case_cache: dict[tuple[str, str, str | None], Any] | None = None

    def __post_init__(self) -> None:
        if self._case_cache is None:
            self._case_cache = {}

    # -- case lookup ------------------------------------------------------

    def _case_for(self, stimulus: Mapping[str, Any]) -> Any:
        """Find the catalog case a stimulus was built from.

        The corpus records dataset, scenario, family and case id, so this is a
        lookup rather than a reconstruction. Results are cached per file
        because ``load_cases`` re-reads and re-hashes the whole dataset.
        """
        scenario_id = str(stimulus.get("scenario_id") or "")
        dataset = str(stimulus.get("dataset") or "")
        family = stimulus.get("family")
        case_id = str(stimulus.get("case_id") or "")
        if not (scenario_id and dataset and case_id):
            raise AdapterResolutionError(
                "stimulus lacks scenario_id, dataset or case_id; it was not built "
                "by csrt_mas.matrix.corpus"
            )
        key = (dataset, scenario_id, family)
        assert self._case_cache is not None
        if key not in self._case_cache:
            cases = self.catalog.load_cases(dataset, scenario_id, family=family)
            self._case_cache[key] = {str(case.case_id): case for case in cases}
        table = self._case_cache[key]
        case = table.get(case_id)
        if case is None:
            raise AdapterResolutionError(
                f"case {case_id} is not present in {dataset}/{scenario_id}"
                + (f"/{family}" if family else "")
            )
        return case

    # -- construction -----------------------------------------------------

    def build(self, stimulus: Mapping[str, Any], text: str) -> SandboxAdapter:
        """Return an adapter bound to this stimulus's scenario."""
        if stimulus.get("scenario_id"):
            from ..finvault_dynamic.runtime import DynamicFinVaultAdapter

            case = self._case_for(stimulus)
            return DynamicFinVaultAdapter(
                self.catalog, case, allow_exploratory=self.allow_exploratory
            )
        if not self.allow_legacy:
            # Falling back silently would run scenario 00's world for a unit
            # that never said which scenario it belonged to, which is the exact
            # confusion this factory exists to prevent.
            raise AdapterResolutionError(
                "stimulus lacks scenario_id; refusing to guess a scenario. "
                "Build the corpus with csrt_mas.matrix.corpus, or set "
                "allow_legacy=True to use the compatibility scenario-00 adapter."
            )
        # Imported here rather than at module scope so scenario 00 is never
        # loaded for a run that does not use it.
        from ..finvault import FinVaultAdapter

        return FinVaultAdapter(dict(stimulus), text)


def terminal_tools_for(adapter: Any, fallback: Sequence[str] = ()) -> tuple[str, ...]:
    """The scenario's own terminal tools, never a hardcoded set.

    ``runner`` previously hardcoded ``{approve_loan, reject_loan,
    escalate_to_human}``, which are scenario 00's. Scenario 13's terminal tools
    are ``add_to_blacklist``, ``remove_from_blacklist``,
    ``update_blacklist_reason``, ``reject_request`` and ``escalate_to_human``:
    an overlapping but different set, so the hardcoded version would
    misclassify every scenario-13 decision.
    """
    tools = getattr(adapter, "terminal_tools", None)
    if tools:
        return tuple(str(item) for item in tools)
    return tuple(fallback)


def available_tools_for(adapter: Any) -> tuple[str, ...]:
    tools = getattr(adapter, "available_tools", None)
    return tuple(str(item) for item in (tools or ()))


def scenario_of(adapter: Any, stimulus: Mapping[str, Any]) -> str:
    """Which scenario actually got built, for the trace.

    Recorded per unit so a run that spans scenarios can be split in analysis,
    and so a mismatch between the configured and executed scenario is visible
    in the evidence rather than assumed away.
    """
    case = getattr(adapter, "case", None)
    if case is not None and getattr(case, "scenario_id", None):
        return str(case.scenario_id)
    return str(stimulus.get("scenario_id") or "")
