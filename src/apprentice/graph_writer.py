from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.core.models import (
    AnswerProcessorResult,
    ExtractedEntity,
    ExtractedRelation,
)
from src.infra.kuzu_client import execute


DIRECT_HIGH_CONFIDENCE = 0.9
DIRECT_MODERATE_CONFIDENCE = 0.8
FOLLOWUP_CONFIDENCE = 0.8
INFERRED_CONFIDENCE = 0.6


def write_to_graph(
    agent_type: str,
    result: AnswerProcessorResult,
    is_followup: bool = False,
) -> dict[str, int]:
    if result.status != "write":
        raise ValueError(
            f"write_to_graph called with status={result.status!r}, expected 'write'"
        )

    now_str = datetime.now(UTC).isoformat()
    summary = {
        "nodes_created": 0,
        "nodes_matched": 0,
        "edges_created": 0,
        "edges_updated": 0,
    }
    label_to_id: dict[str, str] = {}

    for entity in result.entities:
        concept_id = _find_or_create_concept(agent_type, entity, now_str, summary)
        label_to_id[entity.label] = concept_id

    for relation in result.relations:
        confidence = _assign_confidence(relation, is_followup)
        _upsert_relation(agent_type, relation, confidence, label_to_id, summary)

    return summary


def _find_or_create_concept(
    agent_type: str,
    entity: ExtractedEntity,
    now_str: str,
    summary: dict[str, int],
) -> str:
    existing = _first_row(
        execute(
            agent_type,
            """
            MATCH (c:Concept)
            WHERE c.label = $label
            RETURN c.id, c.confidence
            """,
            {"label": entity.label},
        )
    )

    if existing is not None:
        concept_id, current_confidence = existing
        if entity.confidence > float(current_confidence):
            execute(
                agent_type,
                """
                MATCH (c:Concept)
                WHERE c.id = $id
                SET c.confidence = $confidence
                """,
                {"id": concept_id, "confidence": entity.confidence},
            )
        summary["nodes_matched"] += 1
        return str(concept_id)

    concept_id = f"concept-{uuid.uuid4().hex[:12]}"
    execute(
        agent_type,
        """
        CREATE (:Concept {
            id: $id,
            label: $label,
            namespace: 'task',
            confidence: $confidence,
            created_at: $created_at
        })
        """,
        {
            "id": concept_id,
            "label": entity.label,
            "confidence": entity.confidence,
            "created_at": now_str,
        },
    )
    summary["nodes_created"] += 1
    return concept_id


def _assign_confidence(
    relation: ExtractedRelation,
    is_followup: bool,
) -> float:
    if is_followup:
        return FOLLOWUP_CONFIDENCE
    if relation.confidence >= 0.85:
        return DIRECT_HIGH_CONFIDENCE
    if relation.confidence >= 0.5:
        return DIRECT_MODERATE_CONFIDENCE
    return INFERRED_CONFIDENCE


def _upsert_relation(
    agent_type: str,
    relation: ExtractedRelation,
    confidence: float,
    label_to_id: dict[str, str],
    summary: dict[str, int],
) -> None:
    source_id = label_to_id.get(relation.source) or _resolve_concept_id(
        agent_type,
        relation.source,
    )
    target_id = label_to_id.get(relation.target) or _resolve_concept_id(
        agent_type,
        relation.target,
    )

    if source_id is None or target_id is None:
        return

    existing = _first_row(
        execute(
            agent_type,
            """
            MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
            WHERE a.id = $source_id
              AND b.id = $target_id
              AND r.relation = $relation_type
            RETURN r.confidence, r.version
            """,
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation.relation_type,
            },
        )
    )

    if existing is not None:
        old_confidence, old_version = existing
        execute(
            agent_type,
            """
            MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
            WHERE a.id = $source_id
              AND b.id = $target_id
              AND r.relation = $relation_type
            SET r.confidence = $confidence, r.version = $version
            """,
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation.relation_type,
                "confidence": max(float(old_confidence), confidence),
                "version": int(old_version) + 1,
            },
        )
        summary["edges_updated"] += 1
        return

    execute(
        agent_type,
        """
        MATCH (a:Concept), (b:Concept)
        WHERE a.id = $source_id AND b.id = $target_id
        CREATE (a)-[:RELATES_TO {
            relation: $relation_type,
            confidence: $confidence,
            version: 1
        }]->(b)
        """,
        {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation.relation_type,
            "confidence": confidence,
        },
    )
    summary["edges_created"] += 1


def _resolve_concept_id(agent_type: str, label: str) -> str | None:
    row = _first_row(
        execute(
            agent_type,
            """
            MATCH (c:Concept)
            WHERE c.label = $label
            RETURN c.id
            """,
            {"label": label},
        )
    )
    if row is None:
        return None
    return str(row[0])


def _first_row(result: Any) -> list[Any] | None:
    if not result.has_next():
        return None
    return result.get_next()
