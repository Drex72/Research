from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..resources import (
    AgentDefinition,
    GraphPipeline,
    LanguageProfile,
    load_agent_definition,
    load_graph_pipeline,
    load_language_profile,
)
from .catalog import DATASET_NAMES, FinVaultCatalog, FinVaultCatalogError


def _relative_path(root: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FinVaultCatalogError(f"{name} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute():
        raise FinVaultCatalogError(f"{name} must be relative to the project root")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise FinVaultCatalogError(f"{name} escapes the project root") from exc
    return resolved


@dataclass(frozen=True)
class DynamicFinVaultDesign:
    dataset: str
    families: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    include_normal_controls: bool
    preserve_multi_turn: bool
    exploratory: bool
    agents: dict[str, AgentDefinition]
    surfaces: dict[str, LanguageProfile]
    graph_pipelines: tuple[GraphPipeline, ...]

    def summary(self, catalog: FinVaultCatalog) -> dict[str, Any]:
        attack_cases = 0
        normal_cases = 0
        multi_turn_cases = 0
        for scenario_id in self.scenario_ids:
            for family in self.families or (None,):
                cases = catalog.load_cases(self.dataset, scenario_id, family=family)
                attack_cases += len(cases)
                multi_turn_cases += sum(bool(case.follow_up_prompts) for case in cases)
            if self.include_normal_controls:
                normal_cases += len(catalog.load_cases("normal_datasets", scenario_id))
        return {
            "dataset": self.dataset,
            "families": list(self.families),
            "scenarios": list(self.scenario_ids),
            "include_normal_controls": self.include_normal_controls,
            "preserve_multi_turn": self.preserve_multi_turn,
            "exploratory": self.exploratory,
            "attack_cases": attack_cases,
            "normal_cases": normal_cases,
            "multi_turn_cases": multi_turn_cases,
            "agents": {
                role: {
                    "agent_id": agent.agent_id,
                    "model_profile": agent.model_profile,
                    "tool_policy": agent.tool_policy,
                }
                for role, agent in self.agents.items()
            },
            "surfaces": {
                key: {
                    "surface_id": profile.surface_id,
                    "type": profile.kind,
                    "languages": list(profile.languages),
                    "application_point": profile.application_point,
                    "review_status": profile.review_status,
                }
                for key, profile in self.surfaces.items()
            },
            "graph_pipelines": [
                {
                    "pipeline_id": pipeline.pipeline_id,
                    "nodes": len(pipeline.nodes),
                    "edges": len(pipeline.edges),
                    "agent_roles": list(pipeline.agent_roles),
                    "output_node": pipeline.output_node,
                }
                for pipeline in self.graph_pipelines
            ],
        }


def load_dynamic_design(
    experiment: dict[str, Any],
    root: Path,
    catalog: FinVaultCatalog,
) -> DynamicFinVaultDesign:
    value = experiment.get("dynamic_finvault")
    if not isinstance(value, dict):
        raise FinVaultCatalogError("experiment.dynamic_finvault must be an object")
    dataset = value.get("dataset")
    if not isinstance(dataset, dict):
        raise FinVaultCatalogError("dynamic_finvault.dataset must be an object")
    name = dataset.get("name")
    if name not in DATASET_NAMES or name == "normal_datasets":
        raise FinVaultCatalogError("dynamic dataset must be an attack dataset")
    scenarios = dataset.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios or not all(
        isinstance(item, str) for item in scenarios
    ):
        raise FinVaultCatalogError("dynamic_finvault.dataset.scenarios must be a list")
    if len(set(scenarios)) != len(scenarios):
        raise FinVaultCatalogError("dynamic scenario selection contains duplicates")
    families_value = dataset.get("families", [])
    if not isinstance(families_value, list) or not all(
        isinstance(item, str) for item in families_value
    ):
        raise FinVaultCatalogError("dynamic_finvault.dataset.families must be a list")
    families = tuple(families_value)
    if name == "attack_datasets_synthesis":
        if not families:
            raise FinVaultCatalogError("synthesized attacks require at least one family")
        unknown = set(families) - set(catalog.synthesis_families)
        if unknown:
            raise FinVaultCatalogError(f"unknown synthesis families: {sorted(unknown)}")
    elif families:
        raise FinVaultCatalogError("base attack datasets do not accept synthesis families")
    exploratory = value.get("exploratory", False)
    if not isinstance(exploratory, bool):
        raise FinVaultCatalogError("dynamic_finvault.exploratory must be a boolean")
    for scenario_id in scenarios:
        spec = catalog.spec(scenario_id, required=True)
        if spec is None or (not spec.conclusion_ready and not exploratory):
            raise FinVaultCatalogError(
                f"dynamic experiment requires a validated scenario: {scenario_id}"
            )

    agents_raw = value.get("agent_definitions")
    if not isinstance(agents_raw, dict) or not agents_raw:
        raise FinVaultCatalogError("dynamic_finvault.agent_definitions must be an object")
    agents = {
        str(role): load_agent_definition(
            _relative_path(root, reference, f"agent definition {role}")
        )
        for role, reference in agents_raw.items()
    }
    for role, agent in agents.items():
        for field, reference in (
            ("model_profile", agent.model_profile),
            ("system_prompt", agent.system_prompt),
        ):
            path = _relative_path(root, reference, f"agent {role} {field}")
            if not path.is_file():
                raise FinVaultCatalogError(f"agent {role} {field} does not exist: {path}")
    surfaces_raw = value.get("language_profiles")
    if not isinstance(surfaces_raw, dict) or not surfaces_raw:
        raise FinVaultCatalogError("dynamic_finvault.language_profiles must be an object")
    surfaces = {
        str(surface): load_language_profile(
            _relative_path(root, reference, f"language profile {surface}")
        )
        for surface, reference in surfaces_raw.items()
    }
    for surface, profile in surfaces.items():
        if profile.surface_id != surface:
            raise FinVaultCatalogError(
                f"language profile key and surface_id differ: {surface} != {profile.surface_id}"
            )
    graph_raw = value.get("graph_pipelines", [])
    if not isinstance(graph_raw, list) or not all(isinstance(item, str) for item in graph_raw):
        raise FinVaultCatalogError("dynamic_finvault.graph_pipelines must be a list")
    graph_pipelines = tuple(
        load_graph_pipeline(
            _relative_path(root, reference, f"graph pipeline {index}")
        )
        for index, reference in enumerate(graph_raw)
    )
    available_roles = set(agents)
    for pipeline in graph_pipelines:
        missing = set(pipeline.agent_roles) - available_roles
        if missing:
            raise FinVaultCatalogError(
                f"pipeline {pipeline.pipeline_id} references undefined agent roles: {sorted(missing)}"
            )
        for edge in pipeline.edges:
            if edge.template is not None:
                template = _relative_path(
                    root,
                    edge.template,
                    f"pipeline {pipeline.pipeline_id} edge template",
                )
                if not template.is_file():
                    raise FinVaultCatalogError(
                        f"pipeline {pipeline.pipeline_id} template does not exist: {template}"
                    )
    include_normal = dataset.get("include_normal_controls", True)
    preserve_multi = dataset.get("preserve_multi_turn", True)
    if not isinstance(include_normal, bool) or not isinstance(preserve_multi, bool):
        raise FinVaultCatalogError("dynamic dataset control flags must be booleans")
    return DynamicFinVaultDesign(
        dataset=name,
        families=families,
        scenario_ids=tuple(scenarios),
        include_normal_controls=include_normal,
        preserve_multi_turn=preserve_multi,
        exploratory=exploratory,
        agents=agents,
        surfaces=surfaces,
        graph_pipelines=graph_pipelines,
    )
