from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .resources import AgentDefinition, GraphPipeline, PipelineEdge


class GraphExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NodeResult:
    node_id: str
    agent_id: str
    input_payload: dict[str, Any]
    output: dict[str, Any]


@dataclass(frozen=True)
class GraphResult:
    pipeline_id: str
    output_node: str
    output: dict[str, Any]
    nodes: tuple[NodeResult, ...]


def _order(pipeline: GraphPipeline) -> tuple[str, ...]:
    node_ids = [node.node_id for node in pipeline.nodes]
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in pipeline.edges:
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    queue = [node_id for node_id in node_ids if incoming[node_id] == 0]
    output: list[str] = []
    while queue:
        current = queue.pop(0)
        output.append(current)
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if len(output) != len(node_ids):
        raise GraphExecutionError("pipeline graph is cyclic")
    return tuple(output)


def _handoff(
    edge: PipelineEdge,
    upstream: dict[str, Any],
    original_request: str,
) -> dict[str, Any]:
    if edge.payload == "verbatim":
        return {"verbatim_request": original_request}
    if edge.payload == "summary":
        return {"summary": upstream}
    if edge.payload == "summary_and_original":
        return {"summary": upstream, "original_request": original_request}
    if edge.payload == "structured":
        return {"structured": upstream}
    raise GraphExecutionError(f"unsupported handoff payload: {edge.payload}")


class GraphPipelineEngine:
    """Execute a validated agent graph using a caller-supplied model function."""

    def __init__(
        self,
        pipeline: GraphPipeline,
        agents: dict[str, AgentDefinition],
    ):
        self.pipeline = pipeline
        self.agents = agents
        missing = set(pipeline.agent_roles) - set(agents)
        if missing:
            raise GraphExecutionError(f"pipeline references missing agents: {sorted(missing)}")

    def run(
        self,
        *,
        original_request: str,
        trusted_evidence: dict[str, Any],
        invoke: Callable[[AgentDefinition, str, dict[str, Any]], dict[str, Any]],
    ) -> GraphResult:
        nodes = {node.node_id: node for node in self.pipeline.nodes}
        incoming: dict[str, list[PipelineEdge]] = {node_id: [] for node_id in nodes}
        for edge in self.pipeline.edges:
            incoming[edge.target].append(edge)
        outputs: dict[str, dict[str, Any]] = {}
        results: list[NodeResult] = []
        for node_id in _order(self.pipeline):
            node = nodes[node_id]
            agent = self.agents[node.agent]
            edges = incoming[node_id]
            payload: dict[str, Any] = {
                "trusted_evidence": trusted_evidence,
                "handoffs": [
                    {
                        "from": edge.source,
                        "template": edge.template,
                        **_handoff(edge, outputs[edge.source], original_request),
                    }
                    for edge in edges
                ],
            }
            if not edges:
                payload["original_request"] = original_request
            value = invoke(agent, node_id, payload)
            if not isinstance(value, dict):
                raise GraphExecutionError(f"agent node {node_id} returned a non-object")
            outputs[node_id] = value
            results.append(NodeResult(node_id, agent.agent_id, payload, value))
        return GraphResult(
            pipeline_id=self.pipeline.pipeline_id,
            output_node=self.pipeline.output_node,
            output=outputs[self.pipeline.output_node],
            nodes=tuple(results),
        )
