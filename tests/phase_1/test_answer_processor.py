from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api.main import app
from src.apprentice.answer_processor import _check_contradictions, process_answer
from src.core.enums import Phase, TopologyType
from src.core.models import (
    AgentTypeResponse,
    AnswerProcessorInput,
    AnswerProcessorResult,
    ExtractedRelation,
    KnowledgeGap,
    QuestionGeneratorResult,
)
from src.infra.kuzu_client import close_connections, execute, initialize_schema


@pytest.fixture
def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-answer-proc"
    initialize_schema(atype)
    yield atype
    close_connections()


def _gap(
    label: str = "cheeseburger",
    gap_type: str = "unexplored",
    namespace: str = "task",
) -> KnowledgeGap:
    return KnowledgeGap(
        concept_id="c1",
        concept_label=label,
        gap_type=gap_type,
        severity=0.8,
        breadth=2,
        priority_score=1.6,
        namespace=namespace,
    )


def _payload(agent_type: str, answer: str) -> AnswerProcessorInput:
    return AnswerProcessorInput(
        agent_type_id=agent_type,
        question="What belongs on a cheeseburger?",
        answer=answer,
        gap_context=_gap(),
    )


def _mock_extraction(
    entities: list[dict],
    relations: list[dict],
    confidence: float = 0.9,
    ambiguous: bool = False,
):
    payload = {
        "entities": entities,
        "relations": relations,
        "overall_confidence": confidence,
        "is_ambiguous": ambiguous,
    }
    mock = MagicMock()
    mock.content = [MagicMock(text=json.dumps(payload))]
    return mock


def _create_concept(agent_type: str, concept_id: str, label: str) -> None:
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
        {"id": concept_id, "label": label},
    )


def _create_relation(
    agent_type: str,
    source_id: str,
    target_id: str,
    relation: str,
    confidence: float,
) -> None:
    execute(
        agent_type,
        """
        MATCH (a:Concept {id: $source_id}), (b:Concept {id: $target_id})
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


def _count_graph(agent_type: str) -> tuple[int, int]:
    node_result = execute(agent_type, "MATCH (c:Concept) RETURN count(c)")
    edge_result = execute(
        agent_type,
        "MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept) RETURN count(r)",
    )
    return node_result.get_next()[0], edge_result.get_next()[0]


def _agent(agent_type_id: str, phase: Phase = Phase.APPRENTICE) -> AgentTypeResponse:
    return AgentTypeResponse(
        agent_type_id="id-1",
        name=agent_type_id,
        goal="Take burger orders end-to-end",
        task_boundary="Burger ordering only, no payments",
        topic_list=["menu"],
        topology_type=TopologyType.PIPELINE,
        workflow_participants=[],
        phase=phase,
        learning_rate=1.0,
        readiness_score=0.0,
        graph_initialized=True,
        created_at=datetime.now(UTC),
    )


def _route_body(answer: str = "Cheeseburgers include cheddar cheese") -> dict:
    return {
        "question": "What belongs on a cheeseburger?",
        "answer": answer,
        "gap_context": _gap().model_dump(),
    }


def test_clear_answer_returns_write(agent_type: str) -> None:
    extraction = _mock_extraction(
        entities=[
            {"label": "cheeseburger", "entity_type": "menu_item", "confidence": 0.95},
            {"label": "cheddar cheese", "entity_type": "ingredient", "confidence": 0.95},
        ],
        relations=[
            {
                "source": "cheeseburger",
                "target": "cheddar cheese",
                "relation_type": "includes",
                "confidence": 0.9,
            }
        ],
    )

    with patch(
        "src.apprentice.answer_processor._client.messages.create",
        return_value=extraction,
    ):
        result = process_answer(
            _payload(agent_type, "Cheeseburgers always include cheddar cheese")
        )

    assert result.status == "write"
    assert result.confidence >= 0.5
    assert len(result.relations) == 1


def test_ambiguous_answer_returns_followup(agent_type: str) -> None:
    extraction = _mock_extraction([], [], confidence=0.7, ambiguous=True)

    with patch(
        "src.apprentice.answer_processor._client.messages.create",
        return_value=extraction,
    ):
        result = process_answer(_payload(agent_type, "I'm not sure, maybe sometimes"))

    assert result.status == "follow_up"
    assert result.relations == []


def test_low_confidence_answer_returns_followup(agent_type: str) -> None:
    extraction = _mock_extraction([], [], confidence=0.4, ambiguous=False)

    with patch(
        "src.apprentice.answer_processor._client.messages.create",
        return_value=extraction,
    ):
        result = process_answer(_payload(agent_type, "maybe cheese"))

    assert result.status == "follow_up"


def test_contradiction_returns_conflict(agent_type: str) -> None:
    _create_concept(agent_type, "c1", "cheeseburger")
    _create_concept(agent_type, "c2", "pickles")
    _create_relation(agent_type, "c1", "c2", "excludes", 0.85)

    extraction = _mock_extraction(
        entities=[
            {"label": "cheeseburger", "entity_type": "menu_item", "confidence": 0.95},
            {"label": "pickles", "entity_type": "ingredient", "confidence": 0.95},
        ],
        relations=[
            {
                "source": "cheeseburger",
                "target": "pickles",
                "relation_type": "includes",
                "confidence": 0.9,
            }
        ],
    )

    with patch(
        "src.apprentice.answer_processor._client.messages.create",
        return_value=extraction,
    ):
        result = process_answer(_payload(agent_type, "Cheeseburgers include pickles"))

    assert result.status == "conflict"
    assert result.conflict is not None
    assert result.conflict.existing_relation == "excludes"
    assert "includes" in result.conflict.conflict_description


def test_matching_existing_relation_is_not_conflict(agent_type: str) -> None:
    _create_concept(agent_type, "c1", "cheeseburger")
    _create_concept(agent_type, "c2", "cheddar cheese")
    _create_relation(agent_type, "c1", "c2", "includes", 0.85)

    conflict = _check_contradictions(
        agent_type,
        [
            ExtractedRelation(
                source="cheeseburger",
                target="cheddar cheese",
                relation_type="includes",
                confidence=0.9,
            )
        ],
    )

    assert conflict is None


def test_conflict_status_does_not_write_to_graph(agent_type: str) -> None:
    _create_concept(agent_type, "c1", "cheeseburger")
    _create_concept(agent_type, "c2", "pickles")
    _create_relation(agent_type, "c1", "c2", "excludes", 0.85)
    before = _count_graph(agent_type)

    extraction = _mock_extraction(
        entities=[
            {"label": "cheeseburger", "entity_type": "menu_item", "confidence": 0.95},
            {"label": "pickles", "entity_type": "ingredient", "confidence": 0.95},
        ],
        relations=[
            {
                "source": "cheeseburger",
                "target": "pickles",
                "relation_type": "includes",
                "confidence": 0.9,
            }
        ],
    )

    with patch(
        "src.apprentice.answer_processor._client.messages.create",
        return_value=extraction,
    ):
        result = process_answer(_payload(agent_type, "Cheeseburgers include pickles"))

    assert result.status == "conflict"
    assert _count_graph(agent_type) == before


@pytest.mark.asyncio
async def test_answer_route_write_calls_graph_writer_and_readiness(monkeypatch) -> None:
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return _agent(agent_type_id)

    result = AnswerProcessorResult(
        status="write",
        relations=[
            ExtractedRelation(
                source="cheeseburger",
                target="cheddar cheese",
                relation_type="includes",
                confidence=0.9,
            )
        ],
        confidence=0.9,
    )
    writer = MagicMock()
    scorer = MagicMock(return_value={"agent_type_id": "burger", "score": 0.2})

    monkeypatch.setattr(
        "src.api.routes.apprentice.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )
    monkeypatch.setattr(
        "src.api.routes.apprentice.process_answer",
        MagicMock(return_value=result),
    )
    monkeypatch.setattr("src.api.routes.apprentice.write_to_graph", writer)
    monkeypatch.setattr("src.api.routes.apprentice.compute_and_store", scorer)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/agent-types/burger/qa/answer",
            json=_route_body(),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "write"
    writer.assert_called_once()
    scorer.assert_called_once_with("burger")


@pytest.mark.asyncio
async def test_answer_route_followup_populates_question(monkeypatch) -> None:
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return _agent(agent_type_id)

    result = AnswerProcessorResult(status="follow_up", confidence=0.4)
    followup = QuestionGeneratorResult(
        agent_type_id="burger",
        question="Could you clarify when cheese is included?",
        targeting_gap=_gap(),
        is_followup=True,
    )
    writer = MagicMock()

    monkeypatch.setattr(
        "src.api.routes.apprentice.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )
    monkeypatch.setattr(
        "src.api.routes.apprentice.process_answer",
        MagicMock(return_value=result),
    )
    monkeypatch.setattr(
        "src.api.routes.apprentice.generate_followup",
        MagicMock(return_value=followup),
    )
    monkeypatch.setattr("src.api.routes.apprentice.write_to_graph", writer)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/agent-types/burger/qa/answer",
            json=_route_body("maybe sometimes"),
        )

    assert resp.status_code == 200
    assert resp.json()["processor_result"]["follow_up_question"] == followup.question
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_answer_route_empty_answer_returns_400(monkeypatch) -> None:
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return _agent(agent_type_id)

    monkeypatch.setattr(
        "src.api.routes.apprentice.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )

    body = _route_body("")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/agent-types/burger/qa/answer", json=body)

    assert resp.status_code == 400
