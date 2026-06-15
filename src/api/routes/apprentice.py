from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.apprentice.answer_processor import process_answer
from src.apprentice.question_generator import NoGapsRemaining, generate_question
from src.apprentice.question_generator import generate_followup
from src.core.agent_type_service import get_agent_type_by_name
from src.core.enums import Phase
from src.core.models import AnswerProcessorInput, AnswerProcessorResult


router = APIRouter(prefix="/agent-types", tags=["apprentice"])


@router.post("/{agent_type_id}/qa/question")
async def get_next_question(agent_type_id: str):
    agent = await get_agent_type_by_name(agent_type_id)
    if agent.phase != Phase.APPRENTICE:
        raise HTTPException(
            status_code=409,
            detail=f"Agent is in {agent.phase.value} phase, not apprentice",
        )

    try:
        return generate_question(agent.name, agent.goal, agent.task_boundary)
    except NoGapsRemaining as exc:
        return {"detail": "no_gaps_remaining", "agent_type": exc.agent_type}


@router.post("/{agent_type_id}/qa/answer")
async def submit_answer(agent_type_id: str, body: dict):
    agent = await get_agent_type_by_name(agent_type_id)
    if agent.phase != Phase.APPRENTICE:
        raise HTTPException(
            status_code=409,
            detail=f"Agent is in {agent.phase.value} phase, not apprentice",
        )

    if not str(body.get("answer", "")).strip():
        raise HTTPException(status_code=400, detail="answer must not be empty")

    payload = AnswerProcessorInput(
        agent_type_id=agent.name,
        question=body["question"],
        answer=body["answer"],
        gap_context=body["gap_context"],
    )
    result = process_answer(payload)
    response = {"status": result.status, "processor_result": result}

    if result.status == "write":
        write_to_graph(agent.name, result)
        response["readiness_score"] = compute_and_store(agent.name)
    elif result.status == "follow_up":
        followup = generate_followup(
            agent.name,
            agent.goal,
            agent.task_boundary,
            original_question=payload.question,
            ambiguous_answer=payload.answer,
            targeting_gap=payload.gap_context,
        )
        result.follow_up_question = followup.question
        response["processor_result"] = result

    return response


def write_to_graph(agent_type: str, result: AnswerProcessorResult) -> None:
    raise NotImplementedError("Graph writer is implemented in T1.5")


def compute_and_store(agent_type: str):
    raise NotImplementedError("Readiness scorer is implemented in T1.6")
