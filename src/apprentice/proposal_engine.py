from __future__ import annotations

import json
import uuid
from typing import Any

from src.core.enums import CompositionStatus, TopologyType
from src.core.models import AgentContract, HandoffContract, ProposalArtifact
from src.infra.kuzu_client import execute
from src.infra.postgres_client import get_pool


PROPOSAL_MODEL = "claude-opus-4-6"
MIN_CLUSTER_SIZE = 8
CROSS_CLUSTER_RELATIONS = {
    "trigger",
    "triggers",
    "handoff",
    "hands_off_to",
    "passes_to",
    "routes_to",
}

PROPOSAL_PROMPT_TEMPLATE = (
    "You are designing the team structure for a multi-agent system based on a "
    "knowledge graph built through Socratic Q&A with a domain expert.\n\n"
    "AGENT DOMAIN:\n"
    "  Goal: {goal}\n"
    "  Task boundary: {task_boundary}\n"
    "  Declared topology preference: {topology_type}\n"
    "  Declared workflow participants: {workflow_participants}\n\n"
    "GRAPH CLUSTERS (each is a candidate agent's area of responsibility):\n"
    "{cluster_summaries}\n\n"
    "CROSS-CLUSTER RELATIONSHIPS (candidate handoff points between agents):\n"
    "{cross_cluster_edges}\n\n"
    "YOUR TASK:\n"
    "Propose a team composition. For EACH agent provide:\n"
    "  - agent_name (kebab-case)\n"
    "  - input_schema (field name to type string)\n"
    "  - output_schema (field name to type string)\n"
    "  - prohibited_fields (data this agent must never receive)\n\n"
    "For EACH handoff provide:\n"
    "  - from_agent, to_agent\n"
    "  - condition (when this handoff occurs)\n"
    "  - validates (fields confirmed before handoff)\n"
    "  - rationale\n\n"
    "If only one coherent cluster exists, propose a single agent with "
    "topology=pipeline and an empty contracts list.\n\n"
    "Respond ONLY with JSON, no markdown fences, in this exact shape:\n"
    "{{\n"
    '  "topology": "pipeline|orchestrated|peer",\n'
    '  "agents": [{{"agent_name": "...", "input_schema": {{}}, '
    '"output_schema": {{}}, "prohibited_fields": []}}],\n'
    '  "contracts": [{{"from_agent": "...", "to_agent": "...", '
    '"condition": "...", "validates": [], "rationale": "..."}}],\n'
    '  "rationale_per_agent": {{"agent_name": "..."}},\n'
    '  "rationale_per_contract": {{"from->to": "..."}}\n'
    "}}\n"
)


class _MissingMessages:
    def create(self, **kwargs):
        try:
            from anthropic import Anthropic
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "anthropic is required for proposal generation; install the "
                "pinned requirements or patch _client.messages.create in tests"
            ) from exc
        return Anthropic().messages.create(**kwargs)


class _LazyAnthropicClient:
    messages = _MissingMessages()


_client = _LazyAnthropicClient()


async def generate_proposal(
    agent_type: str,
    agent_goal: str,
    task_boundary: str,
    declared_topology: TopologyType,
    workflow_participants: list[str],
    rejection_context: str | None = None,
) -> ProposalArtifact:
    clusters = _find_clusters(agent_type)
    cross_edges = _find_cross_cluster_edges(agent_type, clusters)
    prompt = PROPOSAL_PROMPT_TEMPLATE.format(
        goal=agent_goal,
        task_boundary=task_boundary,
        topology_type=declared_topology.value,
        workflow_participants=", ".join(workflow_participants) or "(none declared)",
        cluster_summaries=_format_cluster_summaries(clusters),
        cross_cluster_edges=_format_cross_cluster_edges(cross_edges),
    )
    if rejection_context:
        prompt += (
            "\nA previous proposal was rejected for this reason: "
            f"{rejection_context}\nAddress this feedback in the new proposal.\n"
        )

    response = _client.messages.create(
        model=PROPOSAL_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    parsed = json.loads(_strip_json_fence(str(response.content[0].text)))
    artifact = ProposalArtifact(
        agent_type_id=agent_type,
        topology=TopologyType(parsed["topology"]),
        agents=[
            AgentContract.model_validate(agent)
            for agent in parsed.get("agents", [])
        ],
        contracts=[
            HandoffContract.model_validate(contract)
            for contract in parsed.get("contracts", [])
        ],
        rationale_per_agent=parsed["rationale_per_agent"],
        rationale_per_contract=parsed["rationale_per_contract"],
        status=CompositionStatus.PROPOSED,
    )
    _validate_rationale_coverage(artifact)
    return await _persist_proposal(agent_type, artifact)


async def _persist_proposal(
    agent_type: str,
    artifact: ProposalArtifact,
) -> ProposalArtifact:
    pool = get_pool()
    async with pool.acquire() as conn:
        max_version = await conn.fetchval(
            "SELECT MAX(version) FROM team_compositions WHERE agent_type = $1",
            agent_type,
        )
        next_version = (max_version or 0) + 1
        artifact.version = next_version
        await conn.execute(
            """
            INSERT INTO team_compositions (
                id,
                agent_type,
                version,
                topology,
                agent_list,
                contracts,
                rationale,
                status,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9)
            """,
            uuid.UUID(artifact.id),
            agent_type,
            next_version,
            artifact.topology.value,
            json.dumps([agent.model_dump() for agent in artifact.agents]),
            json.dumps([contract.model_dump() for contract in artifact.contracts]),
            json.dumps(
                {
                    "rationale_per_agent": artifact.rationale_per_agent,
                    "rationale_per_contract": artifact.rationale_per_contract,
                }
            ),
            CompositionStatus.PROPOSED.value,
            artifact.created_at.replace(tzinfo=None),
        )
    return artifact


def _find_clusters(agent_type: str) -> list[dict[str, Any]]:
    nodes = _load_task_nodes(agent_type)
    if not nodes:
        return []

    parent = {node_id: node_id for node_id in nodes}

    def find(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for source_id, target_id, relation in _load_task_edges(agent_type):
        if _is_cross_cluster_relation(relation):
            continue
        if source_id in parent and target_id in parent:
            union(source_id, target_id)

    groups: dict[str, list[str]] = {}
    for node_id in parent:
        groups.setdefault(find(node_id), []).append(node_id)

    clusters: list[dict[str, Any]] = []
    general_ids: list[str] = []
    for root, member_ids in groups.items():
        if len(member_ids) >= MIN_CLUSTER_SIZE:
            clusters.append(
                {
                    "id": root,
                    "node_ids": member_ids,
                    "labels": [nodes[node_id] for node_id in member_ids],
                }
            )
        else:
            general_ids.extend(member_ids)

    if general_ids:
        clusters.append(
            {
                "id": "general",
                "node_ids": general_ids,
                "labels": [nodes[node_id] for node_id in general_ids],
            }
        )

    return clusters


def _find_cross_cluster_edges(
    agent_type: str,
    clusters: list[dict[str, Any]],
) -> list[dict[str, str]]:
    node_to_cluster: dict[str, str] = {}
    for cluster in clusters:
        for node_id in cluster["node_ids"]:
            node_to_cluster[node_id] = cluster["id"]

    cross_edges: list[dict[str, str]] = []
    result = execute(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        WHERE a.namespace = 'task' AND b.namespace = 'task'
        RETURN a.id, a.label, b.id, b.label, r.relation
        """,
    )
    while result.has_next():
        source_id, source_label, target_id, target_label, relation = result.get_next()
        source_cluster = node_to_cluster.get(str(source_id))
        target_cluster = node_to_cluster.get(str(target_id))
        if source_cluster and target_cluster and source_cluster != target_cluster:
            cross_edges.append(
                {
                    "source_label": str(source_label),
                    "source_cluster": source_cluster,
                    "target_label": str(target_label),
                    "target_cluster": target_cluster,
                    "relation": str(relation),
                }
            )
    return cross_edges


def _format_cluster_summaries(clusters: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, cluster in enumerate(clusters, start=1):
        sample = ", ".join(cluster["labels"][:15])
        more = " ..." if len(cluster["labels"]) > 15 else ""
        lines.append(
            f"Cluster {index} ({cluster['id']}, {len(cluster['labels'])} "
            f"concepts): {sample}{more}"
        )
    return "\n".join(lines) if lines else "(single undifferentiated cluster)"


def _format_cross_cluster_edges(edges: list[dict[str, str]]) -> str:
    if not edges:
        return "(none -- single cluster, propose a single agent)"
    lines: list[str] = []
    for edge in edges[:30]:
        lines.append(
            f"- {edge['source_label']} ({edge['source_cluster']}) "
            f"--[{edge['relation']}]--> "
            f"{edge['target_label']} ({edge['target_cluster']})"
        )
    return "\n".join(lines)


def _load_task_nodes(agent_type: str) -> dict[str, str]:
    result = execute(
        agent_type,
        """
        MATCH (c:Concept)
        WHERE c.namespace = 'task'
        RETURN c.id, c.label
        """,
    )
    nodes: dict[str, str] = {}
    while result.has_next():
        node_id, label = result.get_next()
        nodes[str(node_id)] = str(label)
    return nodes


def _load_task_edges(agent_type: str) -> list[tuple[str, str, str]]:
    result = execute(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        WHERE a.namespace = 'task' AND b.namespace = 'task'
        RETURN a.id, b.id, r.relation
        """,
    )
    edges: list[tuple[str, str, str]] = []
    while result.has_next():
        source_id, target_id, relation = result.get_next()
        edges.append((str(source_id), str(target_id), str(relation)))
    return edges


def _is_cross_cluster_relation(relation: str) -> bool:
    return relation.lower() in CROSS_CLUSTER_RELATIONS


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _validate_rationale_coverage(artifact: ProposalArtifact) -> None:
    missing_agents = [
        agent.agent_name
        for agent in artifact.agents
        if agent.agent_name not in artifact.rationale_per_agent
    ]
    missing_contracts = [
        f"{contract.from_agent}->{contract.to_agent}"
        for contract in artifact.contracts
        if f"{contract.from_agent}->{contract.to_agent}"
        not in artifact.rationale_per_contract
    ]
    if missing_agents or missing_contracts:
        raise ValueError(
            "proposal rationale missing coverage for "
            f"agents={missing_agents}, contracts={missing_contracts}"
        )
