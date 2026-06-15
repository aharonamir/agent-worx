from __future__ import annotations

import pytest

from src.apprentice.gap_detector import detect_gaps
from src.infra.kuzu_client import close_connections, execute, initialize_schema


@pytest.fixture
def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-gaps"
    initialize_schema(atype)
    yield atype
    close_connections()


def _add_concept(
    agent_type: str,
    concept_id: str,
    label: str,
    namespace: str = "task",
) -> None:
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: $id,
            label: $label,
            namespace: $namespace,
            confidence: 0.9,
            created_at: '2025-01-01'
        })
        """,
        {"id": concept_id, "label": label, "namespace": namespace},
    )


def _add_edge(
    agent_type: str,
    source_id: str,
    target_id: str,
    confidence: float,
) -> None:
    execute(
        agent_type,
        """
        MATCH (a:Concept {id: $source_id}), (b:Concept {id: $target_id})
        CREATE (a)-[:RELATES_TO {
            relation: 'related',
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


def test_detects_orphan_nodes(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "burger")
    _add_concept(agent_type, "c2", "fries")
    _add_concept(agent_type, "c3", "shake")

    result = detect_gaps(agent_type)

    assert result.total_nodes == 3
    assert result.orphan_count == 3
    assert all(gap.gap_type == "orphan" for gap in result.gaps)


def test_detects_low_confidence_edge(agent_type: str) -> None:
    _add_concept(agent_type, "c1", "order")
    _add_concept(agent_type, "c2", "payment")
    _add_edge(agent_type, "c1", "c2", 0.2)

    result = detect_gaps(agent_type)

    assert result.low_confidence_count >= 1
    assert any(
        gap.concept_id == "c1" and gap.gap_type == "low_confidence"
        for gap in result.gaps
    )


def test_top_gap_has_highest_priority(agent_type: str) -> None:
    _add_concept(agent_type, "root", "root")
    _add_concept(agent_type, "child-1", "child 1")
    _add_concept(agent_type, "child-2", "child 2")
    _add_concept(agent_type, "shallow", "shallow")
    _add_concept(agent_type, "leaf", "leaf")

    _add_edge(agent_type, "root", "child-1", 0.2)
    _add_edge(agent_type, "child-1", "child-2", 0.9)
    _add_edge(agent_type, "shallow", "leaf", 0.39)

    result = detect_gaps(agent_type)

    assert result.gaps[0].priority_score == max(
        gap.priority_score for gap in result.gaps
    )
    assert result.gaps[0].concept_id == "root"


def test_empty_graph_returns_no_gaps(agent_type: str) -> None:
    result = detect_gaps(agent_type)

    assert result.gaps == []
    assert result.total_nodes == 0
    assert result.orphan_count == 0
    assert result.low_confidence_count == 0
    assert result.unexplored_count == 0


def test_gaps_sorted_by_priority_descending(agent_type: str) -> None:
    for index in range(5):
        _add_concept(agent_type, f"c{index}", f"concept-{index}")
    _add_edge(agent_type, "c0", "c1", 0.2)
    _add_edge(agent_type, "c1", "c2", 0.9)

    result = detect_gaps(agent_type)

    scores = [gap.priority_score for gap in result.gaps]
    assert scores == sorted(scores, reverse=True)
