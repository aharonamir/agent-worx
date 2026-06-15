from __future__ import annotations

import json
from typing import Any

from src.core.models import (
    AnswerProcessorInput,
    AnswerProcessorResult,
    ConflictDetail,
    ExtractedEntity,
    ExtractedRelation,
)
from src.infra.kuzu_client import execute


EXTRACTION_MODEL = "claude-sonnet-4-6"
MIN_WRITE_CONFIDENCE = 0.5

EXTRACTION_PROMPT = """Extract structured knowledge from this expert answer.

QUESTION ASKED: "{question}"
GAP BEING RESOLVED: "{concept_label}" (type: {gap_type}, namespace: {namespace})
EXPERT ANSWER: "{answer}"

Extract:
1. ENTITIES - distinct concepts mentioned (new or referencing existing ones)
2. RELATIONS - relationships between entities, in the form (source, relation_type, target)
3. CONFIDENCE - your confidence (0.0-1.0) that this extraction accurately represents
   what the expert said. Use 0.9+ only for direct, unambiguous statements.
4. AMBIGUITY - true if the answer is too vague, off-topic, or unclear to extract
   meaningful structured knowledge.

Respond ONLY with JSON in this exact format, no markdown fences:
{{
  "entities": [{{"label": "...", "entity_type": "...", "confidence": 0.0}}],
  "relations": [{{"source": "...", "target": "...", "relation_type": "...", "confidence": 0.0}}],
  "overall_confidence": 0.0,
  "is_ambiguous": false
}}
"""

CONTRADICTION_CHECK_QUERY = """
MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
WHERE a.label = $source_label AND r.relation <> $relation_type
RETURN a.label, b.label, r.relation, r.confidence
"""


class _MissingMessages:
    def create(self, **kwargs):
        try:
            from anthropic import Anthropic
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "anthropic is required for answer processing; install the "
                "pinned requirements or patch _client.messages.create in tests"
            ) from exc
        return Anthropic().messages.create(**kwargs)


class _LazyAnthropicClient:
    messages = _MissingMessages()


_client = _LazyAnthropicClient()


def process_answer(payload: AnswerProcessorInput) -> AnswerProcessorResult:
    extraction = _extract(payload)
    confidence = float(extraction["overall_confidence"])

    if extraction["is_ambiguous"] or confidence < MIN_WRITE_CONFIDENCE:
        return AnswerProcessorResult(
            status="follow_up",
            confidence=confidence,
        )

    entities = [
        ExtractedEntity.model_validate(entity)
        for entity in extraction.get("entities", [])
    ]
    relations = [
        ExtractedRelation.model_validate(relation)
        for relation in extraction.get("relations", [])
    ]

    conflict = _check_contradictions(payload.agent_type_id, relations)
    if conflict is not None:
        return AnswerProcessorResult(
            status="conflict",
            entities=entities,
            relations=relations,
            confidence=confidence,
            conflict=conflict,
        )

    return AnswerProcessorResult(
        status="write",
        entities=entities,
        relations=relations,
        confidence=confidence,
    )


def _extract(payload: AnswerProcessorInput) -> dict[str, Any]:
    prompt = EXTRACTION_PROMPT.format(
        question=payload.question,
        concept_label=payload.gap_context.concept_label,
        gap_type=payload.gap_context.gap_type,
        namespace=payload.gap_context.namespace,
        answer=payload.answer,
    )

    response = _client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(_strip_json_fence(str(response.content[0].text)))


def _check_contradictions(
    agent_type: str,
    relations: list[ExtractedRelation],
) -> ConflictDetail | None:
    for relation in relations:
        result = execute(
            agent_type,
            CONTRADICTION_CHECK_QUERY,
            {
                "source_label": relation.source,
                "relation_type": relation.relation_type,
            },
        )
        while result.has_next():
            (
                existing_source,
                existing_target,
                existing_relation,
                existing_confidence,
            ) = result.get_next()
            confidence = float(existing_confidence)
            if existing_target == relation.target and confidence > MIN_WRITE_CONFIDENCE:
                return ConflictDetail(
                    existing_source=existing_source,
                    existing_target=existing_target,
                    existing_relation=existing_relation,
                    existing_confidence=confidence,
                    conflict_description=(
                        f"New answer implies '{relation.source}' "
                        f"{relation.relation_type} '{relation.target}', but the "
                        f"graph already has '{existing_source}' "
                        f"{existing_relation} '{existing_target}' at confidence "
                        f"{confidence:.2f}."
                    ),
                )
    return None


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
