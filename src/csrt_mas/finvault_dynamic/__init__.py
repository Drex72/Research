"""Dynamic access to the pinned FinVault scenarios and datasets."""

from .catalog import (
    DatasetCase,
    FinVaultCatalog,
    FinVaultCatalogError,
    ScenarioRecord,
    ScenarioSpec,
)
from .audit import InterfaceAudit, audit_all_interfaces, audit_interface
from .design import DynamicFinVaultDesign, load_dynamic_design
from .runtime import DynamicExecutionOutcome, DynamicFinVaultAdapter
from .code_switching import (
    AuthoredSurface,
    FinVaultCodeSwitchAdapter,
    FinVaultCodeSwitchError,
)

__all__ = [
    "DatasetCase",
    "DynamicExecutionOutcome",
    "DynamicFinVaultDesign",
    "DynamicFinVaultAdapter",
    "FinVaultCatalog",
    "FinVaultCatalogError",
    "ScenarioRecord",
    "ScenarioSpec",
    "InterfaceAudit",
    "audit_all_interfaces",
    "audit_interface",
    "AuthoredSurface",
    "FinVaultCodeSwitchAdapter",
    "FinVaultCodeSwitchError",
    "load_dynamic_design",
]
