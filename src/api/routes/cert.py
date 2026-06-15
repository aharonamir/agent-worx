from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.apprentice.cert1_service import (
    approve_cert1,
    get_cert1_status,
    reject_cert1,
)
from src.core.agent_type_service import get_agent_type_by_name
from src.core.exceptions import AgentNotInPhase
from src.core.models import CertApproveRequest, CertRejectRequest


router = APIRouter(prefix="/agent-types", tags=["cert"])


@router.get("/{agent_type_id}/cert1-status")
async def cert1_status(agent_type_id: str):
    agent = await get_agent_type_by_name(agent_type_id)
    return await get_cert1_status(agent.name)


@router.post("/{agent_type_id}/cert1/approve")
async def cert1_approve(agent_type_id: str, body: CertApproveRequest):
    agent = await get_agent_type_by_name(agent_type_id)
    try:
        return await approve_cert1(agent.name, body)
    except AgentNotInPhase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{agent_type_id}/cert1/reject")
async def cert1_reject(agent_type_id: str, body: CertRejectRequest):
    agent = await get_agent_type_by_name(agent_type_id)
    try:
        return await reject_cert1(agent.name, body)
    except AgentNotInPhase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
