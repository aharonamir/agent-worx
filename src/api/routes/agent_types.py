from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.core.agent_type_service import create_agent_type, get_agent_type
from src.core.exceptions import AgentTypeAlreadyExists, AgentTypeNotFound
from src.core.models import AgentTypeCreate, AgentTypeResponse


router = APIRouter(prefix="/agent-types", tags=["agent-types"])


@router.post("", response_model=AgentTypeResponse, status_code=status.HTTP_201_CREATED)
async def create(payload: AgentTypeCreate) -> AgentTypeResponse:
    if len(payload.topic_list) == 0:
        raise HTTPException(status_code=400, detail="topic_list must not be empty")
    try:
        return await create_agent_type(payload)
    except AgentTypeAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{agent_type_id}", response_model=AgentTypeResponse)
async def get(agent_type_id: str) -> AgentTypeResponse:
    try:
        return await get_agent_type(agent_type_id)
    except AgentTypeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
