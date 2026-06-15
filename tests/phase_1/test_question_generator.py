from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api.main import app
from src.apprentice.question_generator import (
    NoGapsRemaining,
    generate_followup,
    generate_question,
)
from src.core.enums import Phase, TopologyType
from src.core.models import AgentTypeResponse, KnowledgeGap
from src.infra.kuzu_client import close_connections, execute, initialize_schema


@pytest.fixture
def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-qgen"
    initialize_schema(atype)
    yield atype
    close_connections()


def _mock_response(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


def _add_concept(
    agent_type: str,
    concept_id: str,
    label: str,
    confidence: float = 0.0,
) -> None:
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: $id,
            label: $label,
            namespace: 'task',
            confidence: $confidence,
            created_at: '2025-01-01'
        })
        """,
        {"id": concept_id, "label": label, "confidence": confidence},
    )


def test_question_targets_top_gap(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "allergens")

    with patch(
        "src.apprentice.question_generator._client.messages.create",
        return_value=_mock_response(
            "What allergens are commonly present in the menu items?"
        ),
    ):
        result = generate_question(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
        )

    assert result.targeting_gap.concept_label == "allergens"
    assert "allergen" in result.question.lower()


def test_no_gaps_raises(agent_type: str) -> None:
    with pytest.raises(NoGapsRemaining):
        generate_question(agent_type, "Take burger orders", "Burger ordering only")


def test_prompt_includes_task_boundary(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "menu")
    captured: dict[str, str] = {}

    def fake_create(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        return _mock_response("What items are on the menu?")

    with patch(
        "src.apprentice.question_generator._client.messages.create",
        side_effect=fake_create,
    ):
        generate_question(
            agent_type,
            "Take burger orders",
            "Burger ordering only, no payments",
        )

    assert "Burger ordering only, no payments" in captured["prompt"]


def test_followup_differs_from_original(agent_type: str) -> None:
    gap = KnowledgeGap(
        concept_id="c1",
        concept_label="allergens",
        gap_type="unexplored",
        severity=0.8,
        breadth=2,
        priority_score=1.6,
        namespace="task",
    )

    with patch(
        "src.apprentice.question_generator._client.messages.create",
        return_value=_mock_response(
            "Could you specify which of the 8 major allergens apply?"
        ),
    ):
        result = generate_followup(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
            original_question="What allergens are present?",
            ambiguous_answer="some of them I guess",
            targeting_gap=gap,
        )

    assert result.is_followup is True
    assert result.question != "What allergens are present?"


def test_deduplication_excludes_high_confidence_concepts(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "cheeseburger", confidence=0.9)
    _add_concept(agent_type, "c2", "cheddar cheese", confidence=0.9)
    _add_concept(agent_type, "c3", "fries")
    execute(
        agent_type,
        """
        MATCH (a:Concept {id: 'c1'}), (b:Concept {id: 'c2'})
        CREATE (a)-[:RELATES_TO {
            relation: 'includes',
            confidence: 0.9,
            version: 1
        }]->(b)
        """,
    )

    captured: dict[str, str] = {}

    def fake_create(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        return _mock_response("How do fries relate to the rest of the menu?")

    with patch(
        "src.apprentice.question_generator._client.messages.create",
        side_effect=fake_create,
    ):
        result = generate_question(
            agent_type,
            "Take burger orders",
            "Burger ordering only",
        )

    assert "cheeseburger" in captured["prompt"]
    assert "cheeseburger" not in result.question
    assert "cheddar cheese" not in result.question


@pytest.mark.asyncio
async def test_qa_question_non_apprentice_returns_409(monkeypatch) -> None:
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return AgentTypeResponse(
            agent_type_id="id-1",
            name=agent_type_id,
            goal="Take burger orders end-to-end",
            task_boundary="Burger ordering only, no payments",
            topic_list=["menu"],
            topology_type=TopologyType.PIPELINE,
            workflow_participants=[],
            phase=Phase.JOURNEYMAN,
            learning_rate=0.5,
            readiness_score=0.9,
            graph_initialized=True,
            created_at=datetime.utcnow(),
        )

    monkeypatch.setattr(
        "src.api.routes.apprentice.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/agent-types/test-agent/qa/question")

    assert resp.status_code == 409
