from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.apprentice.proposal_review_service import (
    approve_proposal,
    edit_proposal,
    get_latest_proposal,
    reject_proposal,
)
from src.core.agent_type_service import get_agent_type_by_name
from src.core.exceptions import NoProposalFound, ProposalAlreadyApproved
from src.core.models import ProposalArtifact
from src.core.redis_keys import agent_proposal_ready_key
from src.infra.redis_client import redis_get


router = APIRouter(prefix="/agent-types", tags=["proposals"])


@router.get("/{agent_type_id}/proposal")
async def get_proposal(agent_type_id: str):
    agent = await get_agent_type_by_name(agent_type_id)
    proposal = await get_latest_proposal(agent.name)
    if proposal is None or not _is_proposal_ready(agent.name):
        return None
    return proposal


@router.put("/{agent_type_id}/proposal")
async def review_proposal(agent_type_id: str, body: dict):
    agent = await get_agent_type_by_name(agent_type_id)
    action = body.get("action")

    try:
        if action == "approve":
            result = await approve_proposal(agent.name, expert_id=body["expert_id"])
            return {
                "composition_id": result.id,
                "status": "approved",
                "new_proposal": None,
            }
        if action == "edit":
            result = await edit_proposal(
                agent.name,
                expert_id=body["expert_id"],
                edits=ProposalArtifact.model_validate(body["edits"]),
            )
            return {
                "composition_id": result.id,
                "status": "approved",
                "new_proposal": None,
            }
        if action == "reject":
            new_proposal = await reject_proposal(
                agent.name,
                rejection_reason=body["rejection_reason"],
                agent_goal=agent.goal,
                task_boundary=agent.task_boundary,
                declared_topology=agent.topology_type,
                workflow_participants=agent.workflow_participants,
            )
            return {
                "composition_id": new_proposal.id,
                "status": "re_proposed",
                "new_proposal": new_proposal,
            }
        raise HTTPException(
            status_code=400,
            detail="action must be one of: approve, edit, reject",
        )
    except NoProposalFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProposalAlreadyApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _is_proposal_ready(agent_name: str) -> bool:
    return redis_get(agent_proposal_ready_key(agent_name)) == "true"
