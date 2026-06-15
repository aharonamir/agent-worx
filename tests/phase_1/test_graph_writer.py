from __future__ import annotations

import pytest

from src.apprentice.graph_writer import (
    DIRECT_HIGH_CONFIDENCE,
    FOLLOWUP_CONFIDENCE,
    write_to_graph,
)
from src.core.models import (
    AnswerProcessorResult,
    ExtractedEntity,
    ExtractedRelation,
)
from src.infra.kuzu_client import close_connections, execute, initialize_schema


@pytest.fixture
def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-graph-writer"
    initialize_schema(atype)
    yield atype
    close_connections()


def _write_result(
    entities: list[dict],
    relations: list[dict],
    confidence: float = 0.9,
) -> AnswerProcessorResult:
    return AnswerProcessorResult(
        status="write",
        entities=[ExtractedEntity.model_validate(entity) for entity in entities],
        relations=[
            ExtractedRelation.model_validate(relation) for relation in relations
        ],
        confidence=confidence,
    )


def _rows(agent_type: str, query: str) -> list[list]:
    result = execute(agent_type, query)
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


def test_creates_nodes_and_edge(agent_type: str) -> None:
    result = _write_result(
        entities=[
            {"label": "cheeseburger", "entity_type": "menu_item", "confidence": 0.9},
            {"label": "cheddar cheese", "entity_type": "ingredient", "confidence": 0.9},
        ],
        relations=[
            {
                "source": "cheeseburger",
                "target": "cheddar cheese",
                "relation_type": "includes",
                "confidence": 0.9,
            },
        ],
    )

    summary = write_to_graph(agent_type, result)

    assert summary["nodes_created"] == 2
    assert summary["edges_created"] == 1

    nodes = _rows(agent_type, "MATCH (c:Concept) RETURN c.label")
    assert {row[0] for row in nodes} == {"cheeseburger", "cheddar cheese"}

    edges = _rows(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        RETURN r.relation, r.confidence, r.version
        """,
    )
    assert edges[0][0] == "includes"
    assert edges[0][1] == pytest.approx(DIRECT_HIGH_CONFIDENCE)
    assert edges[0][2] == 1


def test_updates_existing_root_concept_confidence(agent_type: str) -> None:
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: 'root-1',
            label: 'allergens',
            namespace: 'task',
            confidence: 0.0,
            created_at: '2025-01-01'
        })
        """,
    )
    result = _write_result(
        entities=[{"label": "allergens", "entity_type": "topic", "confidence": 0.85}],
        relations=[],
    )

    summary = write_to_graph(agent_type, result)

    assert summary["nodes_created"] == 0
    assert summary["nodes_matched"] == 1

    rows = _rows(
        agent_type,
        "MATCH (c:Concept) WHERE c.label = 'allergens' RETURN c.confidence",
    )
    assert rows[0][0] == pytest.approx(0.85)


def test_repeated_relation_increments_version_and_takes_max_confidence(
    agent_type: str,
) -> None:
    result1 = _write_result(
        entities=[
            {"label": "burger", "entity_type": "menu_item", "confidence": 0.6},
            {"label": "lettuce", "entity_type": "ingredient", "confidence": 0.6},
        ],
        relations=[
            {
                "source": "burger",
                "target": "lettuce",
                "relation_type": "includes",
                "confidence": 0.6,
            },
        ],
    )
    write_to_graph(agent_type, result1)

    result2 = _write_result(
        entities=[
            {"label": "burger", "entity_type": "menu_item", "confidence": 0.95},
            {"label": "lettuce", "entity_type": "ingredient", "confidence": 0.95},
        ],
        relations=[
            {
                "source": "burger",
                "target": "lettuce",
                "relation_type": "includes",
                "confidence": 0.95,
            },
        ],
    )
    summary2 = write_to_graph(agent_type, result2)

    assert summary2["edges_updated"] == 1
    assert summary2["edges_created"] == 0

    edges = _rows(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        WHERE a.label = 'burger' AND b.label = 'lettuce'
        RETURN r.confidence, r.version
        """,
    )
    assert edges[0][0] == pytest.approx(DIRECT_HIGH_CONFIDENCE)
    assert edges[0][1] == 2


def test_followup_confidence_overrides_extraction_confidence(agent_type: str) -> None:
    result = _write_result(
        entities=[
            {"label": "fries", "entity_type": "menu_item", "confidence": 0.95},
            {"label": "ketchup", "entity_type": "ingredient", "confidence": 0.95},
        ],
        relations=[
            {
                "source": "fries",
                "target": "ketchup",
                "relation_type": "served_with",
                "confidence": 0.95,
            },
        ],
    )

    write_to_graph(agent_type, result, is_followup=True)

    edges = _rows(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        WHERE a.label = 'fries' AND b.label = 'ketchup'
        RETURN r.confidence
        """,
    )
    assert edges[0][0] == pytest.approx(FOLLOWUP_CONFIDENCE)


def test_raises_on_non_write_status(agent_type: str) -> None:
    result = AnswerProcessorResult(status="conflict", confidence=0.9)

    with pytest.raises(ValueError):
        write_to_graph(agent_type, result)


def test_relation_to_unresolvable_concept_skipped_silently(agent_type: str) -> None:
    result = _write_result(
        entities=[
            {"label": "burger", "entity_type": "menu_item", "confidence": 0.9},
        ],
        relations=[
            {
                "source": "burger",
                "target": "mystery-item",
                "relation_type": "pairs_with",
                "confidence": 0.9,
            },
        ],
    )

    summary = write_to_graph(agent_type, result)

    assert summary["nodes_created"] == 1
    assert summary["edges_created"] == 0
    assert summary["edges_updated"] == 0
