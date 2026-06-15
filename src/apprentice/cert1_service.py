from __future__ import annotations

from src.core.enums import CertDecision, CertGate, Phase
from src.core.exceptions import AgentNotInPhase
from src.core.models import CertApproveRequest, CertEvent, CertRejectRequest
from src.infra.postgres_client import get_pool, insert_cert_event
from src.infra.redis_client import get_agent_state, set_agent_phase


JOURNEYMAN_LEARNING_RATE = 0.5


async def get_cert1_status(agent_type: str) -> dict:
    state = get_agent_state(agent_type)
    violations_unresolved = await _latest_simulation_unresolved_violations(agent_type)
    simulation_runs = await _count_simulation_sessions(agent_type)

    return {
        "readiness_score": state["readiness_score"],
        "simulation_runs_completed": simulation_runs,
        "violations_unresolved": violations_unresolved,
        "cert_ready": bool(state["cert_ready"]) and violations_unresolved == 0,
    }


async def approve_cert1(agent_type: str, request: CertApproveRequest) -> dict:
    state = get_agent_state(agent_type)
    if state["phase"] != Phase.APPRENTICE.value:
        raise AgentNotInPhase(
            agent_type,
            expected=Phase.APPRENTICE,
            actual=Phase(state["phase"]),
        )

    event = CertEvent(
        agent_type=agent_type,
        gate=CertGate.CERT1,
        decision=CertDecision.APPROVED,
        expert_id=request.expert_id,
        readiness_score=state["readiness_score"],
        notes=request.notes,
    )
    await insert_cert_event(event)
    set_agent_phase(agent_type, Phase.JOURNEYMAN, JOURNEYMAN_LEARNING_RATE)

    return {
        "cert_event_id": event.id,
        "previous_phase": Phase.APPRENTICE.value,
        "new_phase": Phase.JOURNEYMAN.value,
        "new_learning_rate": JOURNEYMAN_LEARNING_RATE,
    }


async def reject_cert1(agent_type: str, request: CertRejectRequest) -> dict:
    state = get_agent_state(agent_type)
    if state["phase"] != Phase.APPRENTICE.value:
        raise AgentNotInPhase(
            agent_type,
            expected=Phase.APPRENTICE,
            actual=Phase(state["phase"]),
        )

    event = CertEvent(
        agent_type=agent_type,
        gate=CertGate.CERT1,
        decision=CertDecision.REJECTED,
        expert_id=request.expert_id,
        readiness_score=state["readiness_score"],
        notes=request.reason,
    )
    await insert_cert_event(event)
    return {"cert_event_id": event.id, "phase": Phase.APPRENTICE.value}


async def _latest_simulation_unresolved_violations(agent_type: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT violations_unresolved
            FROM simulation_session_summaries
            WHERE agent_type = $1
            ORDER BY closed_at DESC
            LIMIT 1
            """,
            agent_type,
        )
    if row is None:
        return 1
    return int(row["violations_unresolved"])


async def _count_simulation_sessions(agent_type: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM simulation_session_summaries
            WHERE agent_type = $1
            """,
            agent_type,
        )
    return int(count or 0)
