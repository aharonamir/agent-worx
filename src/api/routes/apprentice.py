from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.apprentice.question_generator import NoGapsRemaining, generate_question
from src.core.agent_type_service import get_agent_type_by_name
from src.core.enums import Phase


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
