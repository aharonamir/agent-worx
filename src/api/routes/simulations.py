from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.apprentice.simulation.session_manager import (
    SessionNotFound,
    SessionPausedForViolation,
    close_session,
    get_session,
    resolve_violation,
    start_session,
    submit_turn,
)
from src.core.models import SimulationTurnInput


router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("", status_code=201)
async def create_session(body: dict):
    try:
        return await start_session(body["agent_type_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}")
async def read_session(session_id: str):
    try:
        return get_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/turn")
async def post_turn(session_id: str, body: dict):
    turn_input = SimulationTurnInput(
        role=body["role"],
        message=body["message"],
    )
    try:
        return submit_turn(
            session_id,
            turn_input,
            to_agent=body["to_agent"],
            message_fields=body["message_fields"],
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionPausedForViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/violations/{violation_index}/resolve")
async def resolve_turn_violation(session_id: str, violation_index: int, body: dict):
    try:
        return resolve_violation(
            session_id,
            violation_index,
            resolution=body["resolution"],
            clarification=body.get("clarification"),
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/close")
async def close(session_id: str):
    try:
        return await close_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
