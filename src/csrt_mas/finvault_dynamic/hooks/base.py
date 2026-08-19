from __future__ import annotations

import importlib
from typing import Any

from ..catalog import DatasetCase, FinVaultCatalogError


class ScenarioHook:
    """Default case normalization shared by convention-compatible sandboxes."""

    def prepare_case(self, case: DatasetCase) -> dict[str, Any]:
        value = dict(case.raw)
        value.setdefault("case_id", case.case_id)
        value.setdefault("id", case.case_id)
        value.setdefault(
            "case_type", "benign" if case.dataset == "normal_datasets" else "attack"
        )
        value.setdefault("target_vulnerability", case.property_id)
        if case.dataset != "normal_datasets":
            value["attack_prompt"] = case.prompt
        return value


def load_hook(reference: str | None) -> ScenarioHook:
    if reference is None:
        return ScenarioHook()
    prefix = "csrt_mas.finvault_dynamic.hooks."
    if not reference.startswith(prefix) or ":" not in reference:
        raise FinVaultCatalogError(f"scenario hook must be inside {prefix}: {reference}")
    module_name, class_name = reference.split(":", 1)
    module = importlib.import_module(module_name)
    hook_class = getattr(module, class_name, None)
    if not isinstance(hook_class, type) or not issubclass(hook_class, ScenarioHook):
        raise FinVaultCatalogError(f"invalid scenario hook: {reference}")
    return hook_class()
