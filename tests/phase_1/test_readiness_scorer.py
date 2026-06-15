from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest

from src.api.main import app
from src.apprentice.readiness_scorer import EDGE_DENSITY_CAP, compute_and_store
from src.core.enums import Phase, TopologyType
from src.core.models import AgentTypeResponse, ReadinessScore
from src.core.redis_keys import (
    agent_cert_ready_key,
    agent_proposal_ready_key,
    agent_readiness_score_key,
)
from src.infra.kuzu_client import close_connections, execute, initialize_schema
from src.infra.redis_client import close_client, redis_delete, redis_get


@pytest.fixture
def agent(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    monkeypatch.setenv("READINESS_PROPOSAL_THRESHOLD", "0.55")
    monkeypatch.setenv("READINESS_CERT1_THRESHOLD", "0.80")
    atype = "scorer-test"
    initialize_schema(atype)
    _clear_redis(atype)
    yield atype
    _clear_redis(atype)
    close_connections()
    close_client()


def _clear_redis(agent_type: str) -> None:
    redis_delete(agent_readiness_score_key(agent_type))
    redis_delete(agent_proposal_ready_key(agent_type))
    redis_delete(agent_cert_ready_key(agent_type))


def _create_concept(agent_type: str, concept_id: str, label: str | None = None) -> None:
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: $id,
            label: $label,
            namespace: 'task',
            confidence: 0.9,
            created_at: '2025-01-01'
        })
        """,
        {"id": concept_id, "label": label or concept_id},
    )


def _create_edge(
    agent_type: str,
    source_id: str,
    target_id: str,
    confidence: float = 0.85,
) -> None:
    execute(
        agent_type,
        """
        MATCH (a:Concept), (b:Concept)
        WHERE a.id = $source_id AND b.id = $target_id
        CREATE (a)-[:RELATES_TO {
            relation: 'relates',
            confidence: $confidence,
            version: 1
        }]->(b)
        """,
        {
            "source_id": source_id,
            "target_id": target_id,
            "confidence": confidence,
        },
    )


def _agent(agent_type_id: str) -> AgentTypeResponse:
    return AgentTypeResponse(
        agent_type_id="id-1",
        name=agent_type_id,
        goal="Take burger orders end-to-end",
        task_boundary="Burger ordering only, no payments",
        topic_list=["menu"],
        topology_type=TopologyType.PIPELINE,
        workflow_participants=[],
        phase=Phase.APPRENTICE,
        learning_rate=1.0,
        readiness_score=0.0,
        graph_initialized=True,
        created_at=datetime.now(UTC),
    )


def test_empty_graph_scores_zero(agent: str) -> None:
    result = compute_and_store(agent)

    assert result.score == 0.0
    assert result.proposal_ready is False
    assert result.cert_ready is False


def test_fully_connected_graph_scores_one(agent: str) -> None:
    concept_ids = [f"c{i}" for i in range(5)]
    for concept_id in concept_ids:
        _create_concept(agent, concept_id)
    for source_id in concept_ids:
        for target_id in concept_ids:
            _create_edge(agent, source_id, target_id, confidence=1.0)

    result = compute_and_store(agent)

    assert result.node_coverage == 1.0
    assert result.edge_density == 1.0
    assert result.confidence_mean == 1.0
    assert result.score == 1.0
    assert result.proposal_ready is True
    assert result.cert_ready is True


def test_score_increases_monotonically(agent: str) -> None:
    scores: list[float] = []

    for index in range(5):
        _create_concept(agent, f"c{index}")
        if index > 0:
            _create_edge(agent, f"c{index - 1}", f"c{index}", confidence=0.85)
        scores.append(compute_and_store(agent).score)

    for index in range(1, len(scores)):
        assert scores[index] >= scores[index - 1], scores


def test_proposal_ready_at_threshold(agent: str, monkeypatch) -> None:
    monkeypatch.setenv("READINESS_PROPOSAL_THRESHOLD", "0.0")

    result = compute_and_store(agent)

    assert result.proposal_ready is True


def test_cert_ready_at_threshold(agent: str, monkeypatch) -> None:
    monkeypatch.setenv("READINESS_CERT1_THRESHOLD", "0.0")

    result = compute_and_store(agent)

    assert result.cert_ready is True


def test_redis_updated_after_compute(agent: str) -> None:
    _create_concept(agent, "c1")
    result = compute_and_store(agent)

    assert redis_get(agent_readiness_score_key(agent)) == str(result.score)
    assert redis_get(agent_proposal_ready_key(agent)) == "false"
    assert redis_get(agent_cert_ready_key(agent)) == "false"


def test_formula_correctness() -> None:
    node_coverage = 0.8
    avg_edges = 3.0
    edge_density = min(avg_edges / EDGE_DENSITY_CAP, 1.0)
    confidence_mean = 0.9
    expected = round(
        (0.40 * node_coverage)
        + (0.35 * edge_density)
        + (0.25 * confidence_mean),
        4,
    )

    assert expected == pytest.approx(0.755, abs=0.001)


@pytest.mark.asyncio
async def test_get_readiness_route_returns_score(monkeypatch) -> None:
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return _agent(agent_type_id)

    score = ReadinessScore(
        agent_type_id="burger",
        score=0.62,
        node_coverage=0.8,
        edge_density=0.2,
        confidence_mean=0.92,
        proposal_ready=True,
        cert_ready=False,
        computed_at=datetime.now(UTC),
    )
    scorer = MagicMock(return_value=score)
    monkeypatch.setattr(
        "src.api.routes.apprentice.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )
    monkeypatch.setattr("src.api.routes.apprentice.compute_and_store", scorer)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agent-types/burger/readiness")

    assert resp.status_code == 200
    assert resp.json()["score"] == 0.62
    scorer.assert_called_once_with("burger")
