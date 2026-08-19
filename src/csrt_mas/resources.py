from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ResourceError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ResourceError(f"resource does not exist: {path}") from None
    except json.JSONDecodeError as exc:
        raise ResourceError(f"resource is invalid JSON: {path}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ResourceError(f"resource must contain an object: {path}")
    return value


def _text(value: Any, name: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResourceError(f"{name} must be a non-empty string: {path}")
    return value


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    model_profile: str
    system_prompt: str
    tool_policy: str
    input_contract: str
    output_contract: str
    path: Path


@dataclass(frozen=True)
class LanguageProfile:
    surface_id: str
    kind: str
    languages: tuple[str, ...]
    application_point: str
    construction: str
    review_status: str
    preserve: tuple[str, ...]
    path: Path


@dataclass(frozen=True)
class PipelineNode:
    node_id: str
    agent: str


@dataclass(frozen=True)
class PipelineEdge:
    source: str
    target: str
    payload: str
    template: str | None


@dataclass(frozen=True)
class GraphPipeline:
    pipeline_id: str
    nodes: tuple[PipelineNode, ...]
    edges: tuple[PipelineEdge, ...]
    output_node: str
    path: Path

    @property
    def agent_roles(self) -> tuple[str, ...]:
        return tuple(node.agent for node in self.nodes)


def load_agent_definition(path: Path) -> AgentDefinition:
    raw = _load(path)
    if raw.get("schema_version") != 1:
        raise ResourceError(f"unsupported agent schema: {path}")
    return AgentDefinition(
        agent_id=_text(raw.get("agent_id"), "agent_id", path),
        model_profile=_text(raw.get("model_profile"), "model_profile", path),
        system_prompt=_text(raw.get("system_prompt"), "system_prompt", path),
        tool_policy=_text(raw.get("tool_policy"), "tool_policy", path),
        input_contract=_text(raw.get("input_contract"), "input_contract", path),
        output_contract=_text(raw.get("output_contract"), "output_contract", path),
        path=path.resolve(),
    )


def load_language_profile(path: Path) -> LanguageProfile:
    raw = _load(path)
    if raw.get("schema_version") not in {1, 2}:
        raise ResourceError(f"unsupported language profile schema: {path}")
    languages = raw.get("languages")
    preserve = raw.get("preserve", [])
    if not isinstance(languages, list) or not languages or not all(
        isinstance(item, str) and item for item in languages
    ):
        raise ResourceError(f"languages must be a non-empty list: {path}")
    if not isinstance(preserve, list) or not all(isinstance(item, str) for item in preserve):
        raise ResourceError(f"preserve must be a list: {path}")
    kind = _text(raw.get("type"), "type", path)
    if kind not in {"source", "monolingual", "code_switched"}:
        raise ResourceError(f"unsupported language profile type: {path}")
    application = _text(raw.get("application_point"), "application_point", path)
    if application not in {"user_request", "handoff", "system_prompt", "tool_description"}:
        raise ResourceError(f"unsupported language application point: {path}")
    return LanguageProfile(
        surface_id=_text(raw.get("surface_id"), "surface_id", path),
        kind=kind,
        languages=tuple(languages),
        application_point=application,
        construction=_text(raw.get("construction"), "construction", path),
        review_status=_text(raw.get("review_status"), "review_status", path),
        preserve=tuple(preserve),
        path=path.resolve(),
    )


def load_graph_pipeline(path: Path) -> GraphPipeline:
    raw = _load(path)
    if raw.get("schema_version") != 2:
        raise ResourceError(f"graph pipelines require schema_version 2: {path}")
    nodes_raw = raw.get("nodes")
    edges_raw = raw.get("edges")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ResourceError(f"pipeline nodes must be a non-empty list: {path}")
    if not isinstance(edges_raw, list):
        raise ResourceError(f"pipeline edges must be a list: {path}")
    nodes: list[PipelineNode] = []
    for index, value in enumerate(nodes_raw):
        if not isinstance(value, dict):
            raise ResourceError(f"pipeline node {index} must be an object: {path}")
        nodes.append(
            PipelineNode(
                node_id=_text(value.get("id"), f"nodes[{index}].id", path),
                agent=_text(value.get("agent"), f"nodes[{index}].agent", path),
            )
        )
    node_ids = [node.node_id for node in nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ResourceError(f"pipeline contains duplicate node IDs: {path}")
    edges: list[PipelineEdge] = []
    for index, value in enumerate(edges_raw):
        if not isinstance(value, dict):
            raise ResourceError(f"pipeline edge {index} must be an object: {path}")
        source = _text(value.get("from"), f"edges[{index}].from", path)
        target = _text(value.get("to"), f"edges[{index}].to", path)
        if source not in node_ids or target not in node_ids:
            raise ResourceError(f"pipeline edge references an unknown node: {path}")
        payload = _text(value.get("payload"), f"edges[{index}].payload", path)
        if payload not in {"verbatim", "summary", "summary_and_original", "structured"}:
            raise ResourceError(f"unsupported pipeline payload: {path}")
        template = value.get("template")
        if template is not None and (not isinstance(template, str) or not template):
            raise ResourceError(f"pipeline edge template must be a path string: {path}")
        edges.append(PipelineEdge(source, target, payload, template))
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    queue = [node_id for node_id, count in incoming.items() if count == 0]
    visited: list[str] = []
    while queue:
        current = queue.pop(0)
        visited.append(current)
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if len(visited) != len(nodes):
        raise ResourceError(f"pipeline graph contains a cycle: {path}")
    output_node = _text(raw.get("output_node"), "output_node", path)
    if output_node not in node_ids:
        raise ResourceError(f"pipeline output_node is unknown: {path}")
    return GraphPipeline(
        pipeline_id=_text(raw.get("pipeline_id"), "pipeline_id", path),
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_node=output_node,
        path=path.resolve(),
    )
