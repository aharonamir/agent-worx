from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from src.apprentice.proposal_engine import (
    _find_clusters,
    _find_cross_cluster_edges,
    generate_proposal,
)
from src.core.enums import TopologyType
from src.infra.kuzu_client import close_connections, execute, initialize_schema
from src.infra.postgres_client import (
    close_pool,
    get_pool,
    init_pool,
    initialize_knowledge_schema,
)


@pytest_asyncio.fixture
async def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-proposal"
    initialize_schema(atype)
    pool = await init_pool()
    await initialize_knowledge_schema(pool)
    await _delete_proposals(atype)
    yield atype
    await _delete_proposals(atype)
    close_connections()
    await close_pool()


async def _delete_proposals(agent_type: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM team_compositions WHERE agent_type = $1",
            agent_type,
        )


def _add_concept(agent_type: str, concept_id: str, label: str) -> None:
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: $id,
            label: $label,
            namespace: 'task',
            confidence: 0.85,
            created_at: '2025-01-01'
        })
        """,
        {"id": concept_id, "label": label},
    )


def _add_edge(
    agent_type: str,
    source_id: str,
    target_id: str,
    relation: str = "relates_to",
    confidence: float = 0.85,
) -> None:
    execute(
        agent_type,
        """
        MATCH (a:Concept), (b:Concept)
        WHERE a.id = $source_id AND b.id = $target_id
        CREATE (a)-[:RELATES_TO {
            relation: $relation,
            confidence: $confidence,
            version: 1
        }]->(b)
        """,
        {
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation,
            "confidence": confidence,
        },
    )


def _mock_response(payload: dict):
    mock = MagicMock()
    mock.content = [MagicMock(text=json.dumps(payload))]
    return mock


@pytest.mark.asyncio
async def test_single_cluster_produces_single_agent(agent_type: str) -> None:
    for index in range(5):
        _add_concept(agent_type, f"c{index}", f"concept-{index}")
    for index in range(4):
        _add_edge(agent_type, f"c{index}", f"c{index + 1}")

    clusters = _find_clusters(agent_type)
    assert len(clusters) == 1

    mock_payload = {
        "topology": "pipeline",
        "agents": [
            {
                "agent_name": "burger-order-agent",
                "input_schema": {"order": "dict"},
                "output_schema": {"confirmation": "dict"},
                "prohibited_fields": [],
            }
        ],
        "contracts": [],
        "rationale_per_agent": {
            "burger-order-agent": "Single coherent domain, no natural split",
        },
        "rationale_per_contract": {},
    }

    with patch(
        "src.apprentice.proposal_engine._client.messages.create",
        return_value=_mock_response(mock_payload),
    ):
        artifact = await generate_proposal(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
            TopologyType.PIPELINE,
            [],
        )

    assert len(artifact.agents) == 1
    assert artifact.topology == TopologyType.PIPELINE
    assert "burger-order-agent" in artifact.rationale_per_agent


@pytest.mark.asyncio
async def test_two_clusters_produce_multi_agent_proposal(agent_type: str) -> None:
    for index in range(10):
        _add_concept(agent_type, f"order-{index}", f"order-concept-{index}")
    for index in range(9):
        _add_edge(agent_type, f"order-{index}", f"order-{index + 1}")

    for index in range(8):
        _add_concept(agent_type, f"pay-{index}", f"payment-concept-{index}")
    for index in range(7):
        _add_edge(agent_type, f"pay-{index}", f"pay-{index + 1}")

    _add_edge(agent_type, "order-9", "pay-0", relation="triggers")

    clusters = _find_clusters(agent_type)
    assert len(clusters) == 2

    cross_edges = _find_cross_cluster_edges(agent_type, clusters)
    assert len(cross_edges) == 1
    assert cross_edges[0]["relation"] == "triggers"

    mock_payload = {
        "topology": "orchestrated",
        "agents": [
            {
                "agent_name": "order-agent",
                "input_schema": {"items": "list[str]"},
                "output_schema": {"order_id": "str"},
                "prohibited_fields": ["card_token"],
            },
            {
                "agent_name": "payment-agent",
                "input_schema": {"order_id": "str", "card_token": "str"},
                "output_schema": {"receipt": "dict"},
                "prohibited_fields": [],
            },
        ],
        "contracts": [
            {
                "from_agent": "order-agent",
                "to_agent": "payment-agent",
                "condition": "order confirmed",
                "validates": ["order_id"],
                "rationale": "Payment must occur after order confirmation",
            }
        ],
        "rationale_per_agent": {
            "order-agent": "10-concept cluster focused on order intake",
            "payment-agent": "8-concept cluster focused on payment processing",
        },
        "rationale_per_contract": {
            "order-agent->payment-agent": (
                "Order must be confirmed before payment is triggered"
            ),
        },
    }

    with patch(
        "src.apprentice.proposal_engine._client.messages.create",
        return_value=_mock_response(mock_payload),
    ):
        artifact = await generate_proposal(
            agent_type,
            "Take burger orders",
            "Burger ordering and payment",
            TopologyType.ORCHESTRATED,
            ["payment-agent"],
        )

    assert len(artifact.agents) == 2
    assert len(artifact.contracts) == 1
    assert artifact.topology == TopologyType.ORCHESTRATED
    assert "order-agent->payment-agent" in artifact.rationale_per_contract
    order_agent = next(agent for agent in artifact.agents if agent.agent_name == "order-agent")
    assert "card_token" in order_agent.prohibited_fields


@pytest.mark.asyncio
async def test_version_increments_and_status_is_proposed(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "concept-1")
    mock_payload = {
        "topology": "pipeline",
        "agents": [
            {
                "agent_name": "test-agent",
                "input_schema": {},
                "output_schema": {},
                "prohibited_fields": [],
            }
        ],
        "contracts": [],
        "rationale_per_agent": {"test-agent": "r"},
        "rationale_per_contract": {},
    }

    with patch(
        "src.apprentice.proposal_engine._client.messages.create",
        return_value=_mock_response(mock_payload),
    ):
        first = await generate_proposal(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
            TopologyType.PIPELINE,
            [],
        )
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE team_compositions
                SET status = 'approved'
                WHERE agent_type = $1 AND version = 1
                """,
                agent_type,
            )
        second = await generate_proposal(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
            TopologyType.PIPELINE,
            [],
        )

    assert first.version == 1
    assert second.version == 2

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT version, status
            FROM team_compositions
            WHERE agent_type = $1
            ORDER BY version
            """,
            agent_type,
        )

    assert [(row["version"], row["status"]) for row in rows] == [
        (1, "approved"),
        (2, "proposed"),
    ]
