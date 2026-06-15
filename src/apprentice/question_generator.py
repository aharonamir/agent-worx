from __future__ import annotations

import re
from typing import Any

from src.apprentice.gap_detector import detect_gaps
from src.core.models import (
    GapDetectorResult,
    KnowledgeGap,
    QuestionGeneratorResult,
)
from src.infra.kuzu_client import execute


QUESTION_MODEL = "claude-sonnet-4-6"

QUESTION_PROMPT = """You are the learning module for a specialized AI agent being trained \
in apprentice phase. Your job is to ask a domain expert ONE precise question that will \
resolve a specific gap in your knowledge graph.

AGENT DOMAIN:
  Goal: {goal}
  Task boundary: {task_boundary}

KNOWLEDGE GAP TO RESOLVE:
  Concept: "{concept_label}"
  Gap type: {gap_type}
  Namespace: {namespace}

WHAT YOU ALREADY KNOW (do not ask about these -- already covered with high confidence):
{known_concepts}

RULES:
- Ask exactly ONE question.
- The question must stay strictly within the task boundary above.
- The question must target the specific gap -- not a generic "tell me about X".
- If gap_type is "orphan", ask how this concept relates to other concepts in the domain.
- If gap_type is "low_confidence", ask for clarification or confirmation of the existing relation.
- If gap_type is "unexplored", ask an opening question about this topic.
- Output ONLY the question text. No preamble, no quotes, no explanation.
"""


class NoGapsRemaining(Exception):
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        super().__init__(
            f"No knowledge gaps remaining for '{agent_type}' -- graph may be saturated"
        )


class _MissingMessages:
    def create(self, **kwargs):
        try:
            from anthropic import Anthropic
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "anthropic is required for question generation; install the "
                "pinned requirements or patch _client.messages.create in tests"
            ) from exc
        return Anthropic().messages.create(**kwargs)


class _LazyAnthropicClient:
    messages = _MissingMessages()


_client = _LazyAnthropicClient()


def generate_question(
    agent_type: str,
    agent_goal: str,
    task_boundary: str,
) -> QuestionGeneratorResult:
    gap_result: GapDetectorResult = detect_gaps(agent_type)
    if not gap_result.gaps:
        raise NoGapsRemaining(agent_type)

    top_gap = gap_result.gaps[0]
    known_concepts = _get_high_confidence_concepts(
        agent_type,
        exclude_id=top_gap.concept_id,
    )
    prompt = QUESTION_PROMPT.format(
        goal=agent_goal,
        task_boundary=task_boundary,
        concept_label=top_gap.concept_label,
        gap_type=top_gap.gap_type,
        namespace=top_gap.namespace,
        known_concepts="\n".join(f"- {concept}" for concept in known_concepts)
        or "(none yet)",
    )
    question_text = _extract_text(
        _client.messages.create(
            model=QUESTION_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    question_text = _remove_known_concept_mentions(question_text, known_concepts)

    return QuestionGeneratorResult(
        agent_type_id=agent_type,
        question=question_text,
        targeting_gap=top_gap,
        is_followup=False,
    )


def generate_followup(
    agent_type: str,
    agent_goal: str,
    task_boundary: str,
    original_question: str,
    ambiguous_answer: str,
    targeting_gap: KnowledgeGap,
) -> QuestionGeneratorResult:
    prompt = f"""You asked: "{original_question}"
The expert answered: "{ambiguous_answer}"

This answer was too ambiguous to extract structured knowledge from. Ask ONE \
follow-up question that would clarify the ambiguity. Stay within this task boundary: \
{task_boundary}

Output ONLY the follow-up question text."""

    question_text = _extract_text(
        _client.messages.create(
            model=QUESTION_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    if question_text == original_question:
        question_text = f"Could you clarify: {ambiguous_answer}?"

    return QuestionGeneratorResult(
        agent_type_id=agent_type,
        question=question_text,
        targeting_gap=targeting_gap,
        is_followup=True,
    )


def _get_high_confidence_concepts(
    agent_type: str,
    exclude_id: str,
    threshold: float = 0.75,
    limit: int = 20,
) -> list[str]:
    result = execute(
        agent_type,
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        WHERE r.confidence >= $threshold
        RETURN a.id, a.label, b.id, b.label
        """,
        {"threshold": threshold},
    )
    concepts: list[str] = []
    while result.has_next() and len(concepts) < limit:
        source_id, source_label, target_id, target_label = result.get_next()
        for concept_id, label in (
            (source_id, source_label),
            (target_id, target_label),
        ):
            if concept_id == exclude_id or not label:
                continue
            label_text = str(label)
            if label_text not in concepts:
                concepts.append(label_text)
    return concepts


def _extract_text(response: Any) -> str:
    return str(response.content[0].text).strip()


def _remove_known_concept_mentions(question: str, known_concepts: list[str]) -> str:
    cleaned = question
    for concept in known_concepts:
        cleaned = re.sub(
            re.escape(concept),
            "the already covered concept",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip()
