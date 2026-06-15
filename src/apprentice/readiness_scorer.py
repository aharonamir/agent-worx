from __future__ import annotations

import os
from datetime import UTC, datetime

from src.core.models import ReadinessScore
from src.core.redis_keys import (
    agent_cert_ready_key,
    agent_proposal_ready_key,
    agent_readiness_score_key,
)
from src.infra.kuzu_client import execute
from src.infra.redis_client import redis_set


DEFAULT_PROPOSAL_THRESHOLD = 0.55
DEFAULT_CERT1_THRESHOLD = 0.80
EDGE_DENSITY_CAP = 5.0


def compute_and_store(agent_type: str) -> ReadinessScore:
    node_coverage = _compute_node_coverage(agent_type)
    edge_density = _compute_edge_density(agent_type)
    confidence_mean = _compute_confidence_mean(agent_type)
    score = round(
        (0.40 * node_coverage)
        + (0.35 * edge_density)
        + (0.25 * confidence_mean),
        4,
    )

    result = ReadinessScore(
        agent_type_id=agent_type,
        score=score,
        node_coverage=round(node_coverage, 4),
        edge_density=round(edge_density, 4),
        confidence_mean=round(confidence_mean, 4),
        proposal_ready=score >= _proposal_threshold(),
        cert_ready=score >= _cert1_threshold(),
        computed_at=datetime.now(UTC),
    )

    redis_set(agent_readiness_score_key(agent_type), str(result.score))
    redis_set(agent_proposal_ready_key(agent_type), str(result.proposal_ready).lower())
    redis_set(agent_cert_ready_key(agent_type), str(result.cert_ready).lower())

    return result


def _compute_node_coverage(agent_type: str) -> float:
    task_concepts = _task_concept_ids(agent_type)
    if not task_concepts:
        return 0.0

    covered: set[str] = set()
    result = execute(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        RETURN a.id, a.namespace, b.id, b.namespace
        """,
    )
    while result.has_next():
        source_id, source_namespace, target_id, target_namespace = result.get_next()
        if source_namespace == "task":
            covered.add(str(source_id))
        if target_namespace == "task":
            covered.add(str(target_id))

    return len(covered & task_concepts) / len(task_concepts)


def _compute_edge_density(agent_type: str) -> float:
    node_count = _count_rows(agent_type, "MATCH (c:Concept) RETURN c")
    if node_count == 0:
        return 0.0
    edge_count = _count_rows(
        agent_type,
        "MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept) RETURN r",
    )
    return min((edge_count / node_count) / EDGE_DENSITY_CAP, 1.0)


def _compute_confidence_mean(agent_type: str) -> float:
    result = execute(
        agent_type,
        "MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept) RETURN r.confidence",
    )
    confidences: list[float] = []
    while result.has_next():
        confidences.append(float(result.get_next()[0]))
    if not confidences:
        return 0.0
    return sum(confidences) / len(confidences)


def _task_concept_ids(agent_type: str) -> set[str]:
    result = execute(
        agent_type,
        """
        MATCH (c:Concept)
        WHERE c.namespace = 'task'
        RETURN c.id
        """,
    )
    concept_ids: set[str] = set()
    while result.has_next():
        concept_ids.add(str(result.get_next()[0]))
    return concept_ids


def _count_rows(agent_type: str, query: str) -> int:
    result = execute(agent_type, query)
    count = 0
    while result.has_next():
        result.get_next()
        count += 1
    return count


def _proposal_threshold() -> float:
    return float(os.getenv("READINESS_PROPOSAL_THRESHOLD", DEFAULT_PROPOSAL_THRESHOLD))


def _cert1_threshold() -> float:
    return float(os.getenv("READINESS_CERT1_THRESHOLD", DEFAULT_CERT1_THRESHOLD))
