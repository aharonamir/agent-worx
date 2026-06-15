from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from src.core.models import GapDetectorResult, KnowledgeGap
from src.infra.kuzu_client import execute


LOW_CONFIDENCE_THRESHOLD = 0.4
UNEXPLORED_OUTGOING_EDGE_TARGET = 2


@dataclass(frozen=True)
class ConceptRecord:
    id: str
    label: str
    namespace: str


@dataclass(frozen=True)
class EdgeRecord:
    source_id: str
    target_id: str
    confidence: float


def detect_gaps(agent_type: str) -> GapDetectorResult:
    concepts = _load_concepts(agent_type)
    edges = _load_edges(agent_type)
    outgoing = _group_outgoing_edges(edges)
    incoming = _group_incoming_edges(edges)

    orphans = _find_orphan_nodes(concepts, outgoing, incoming)
    low_confidence = _find_low_confidence_edges(concepts, outgoing)
    unexplored = _find_unexplored_branches(concepts, outgoing, incoming)

    all_gaps = orphans + low_confidence + unexplored
    all_gaps.sort(key=lambda gap: gap.priority_score, reverse=True)

    return GapDetectorResult(
        agent_type_id=agent_type,
        gaps=all_gaps,
        total_nodes=len(concepts),
        orphan_count=len(orphans),
        low_confidence_count=len(low_confidence),
        unexplored_count=len(unexplored),
    )


def _load_concepts(agent_type: str) -> dict[str, ConceptRecord]:
    result = execute(
        agent_type,
        """
        MATCH (c:Concept)
        RETURN c.id, c.label, c.namespace
        """,
    )
    concepts: dict[str, ConceptRecord] = {}
    while result.has_next():
        concept_id, label, namespace = result.get_next()
        concepts[concept_id] = ConceptRecord(
            id=concept_id,
            label=label,
            namespace=namespace,
        )
    return concepts


def _load_edges(agent_type: str) -> list[EdgeRecord]:
    result = execute(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        RETURN a.id, b.id, r.confidence
        """,
    )
    edges: list[EdgeRecord] = []
    while result.has_next():
        source_id, target_id, confidence = result.get_next()
        edges.append(
            EdgeRecord(
                source_id=source_id,
                target_id=target_id,
                confidence=float(confidence),
            )
        )
    return edges


def _group_outgoing_edges(edges: list[EdgeRecord]) -> dict[str, list[EdgeRecord]]:
    grouped: dict[str, list[EdgeRecord]] = defaultdict(list)
    for edge in edges:
        grouped[edge.source_id].append(edge)
    return grouped


def _group_incoming_edges(edges: list[EdgeRecord]) -> dict[str, list[EdgeRecord]]:
    grouped: dict[str, list[EdgeRecord]] = defaultdict(list)
    for edge in edges:
        grouped[edge.target_id].append(edge)
    return grouped


def _find_orphan_nodes(
    concepts: dict[str, ConceptRecord],
    outgoing: dict[str, list[EdgeRecord]],
    incoming: dict[str, list[EdgeRecord]],
) -> list[KnowledgeGap]:
    gaps: list[KnowledgeGap] = []
    for concept in concepts.values():
        if outgoing.get(concept.id) or incoming.get(concept.id):
            continue
        gaps.append(
            KnowledgeGap(
                concept_id=concept.id,
                concept_label=concept.label,
                gap_type="orphan",
                severity=1.0,
                breadth=0,
                priority_score=0.0,
                namespace=_namespace(concept.namespace),
            )
        )
    return gaps


def _find_low_confidence_edges(
    concepts: dict[str, ConceptRecord],
    outgoing: dict[str, list[EdgeRecord]],
    threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> list[KnowledgeGap]:
    gaps: list[KnowledgeGap] = []
    for concept_id, edges in outgoing.items():
        low_edges = [edge for edge in edges if edge.confidence < threshold]
        if not low_edges:
            continue
        concept = concepts[concept_id]
        min_confidence = min(edge.confidence for edge in low_edges)
        severity = round(1.0 - min_confidence, 3)
        breadth = _count_dependent_concepts(concept_id, outgoing)
        gaps.append(
            KnowledgeGap(
                concept_id=concept.id,
                concept_label=concept.label,
                gap_type="low_confidence",
                severity=severity,
                breadth=breadth,
                priority_score=round(severity * breadth, 3),
                namespace=_namespace(concept.namespace),
            )
        )
    return gaps


def _find_unexplored_branches(
    concepts: dict[str, ConceptRecord],
    outgoing: dict[str, list[EdgeRecord]],
    incoming: dict[str, list[EdgeRecord]],
) -> list[KnowledgeGap]:
    gaps: list[KnowledgeGap] = []
    for concept in concepts.values():
        if concept.namespace != "task":
            continue
        outgoing_count = len(outgoing.get(concept.id, []))
        if outgoing_count == 0 and not incoming.get(concept.id):
            continue
        if outgoing_count >= UNEXPLORED_OUTGOING_EDGE_TARGET:
            continue
        severity = 0.5 + (
            0.5
            * (
                1
                - outgoing_count / UNEXPLORED_OUTGOING_EDGE_TARGET
            )
        )
        breadth = max(_count_dependent_concepts(concept.id, outgoing), 1)
        gaps.append(
            KnowledgeGap(
                concept_id=concept.id,
                concept_label=concept.label,
                gap_type="unexplored",
                severity=round(severity, 3),
                breadth=breadth,
                priority_score=round(severity * breadth, 3),
                namespace="task",
            )
        )
    return gaps


def _count_dependent_concepts(
    concept_id: str,
    outgoing: dict[str, list[EdgeRecord]],
    max_depth: int = 3,
) -> int:
    seen: set[str] = set()
    queue = deque((edge.target_id, 1) for edge in outgoing.get(concept_id, []))

    while queue:
        current_id, depth = queue.popleft()
        if current_id in seen or depth > max_depth:
            continue
        seen.add(current_id)
        if depth == max_depth:
            continue
        queue.extend(
            (edge.target_id, depth + 1)
            for edge in outgoing.get(current_id, [])
        )

    return len(seen)


def _namespace(value: str) -> str:
    if value in {"task", "coordination"}:
        return value
    return "task"
