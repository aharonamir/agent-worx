from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from src.apprentice.proposal_review_service import get_latest_proposal
from src.apprentice.simulation.contract_validator import (
    apply_resolution,
    validate_message,
)
from src.core.enums import CompositionStatus, ObservationType
from src.core.models import (
    AgentContract,
    SimulationObservation,
    SimulationSession,
    SimulationTurnInput,
    SimulationTurnResult,
)
from src.infra.kuzu_client import execute


_sessions: dict[str, SimulationSession] = {}
_session_agents: dict[str, list[AgentContract]] = {}


class SessionNotFound(Exception):
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Simulation session '{session_id}' not found")


class SessionPausedForViolation(Exception):
    def __init__(self, session_id: str, unresolved_count: int):
        self.session_id = session_id
        self.unresolved_count = unresolved_count
        super().__init__(
            f"Session '{session_id}' has {unresolved_count} unresolved "
            "violation(s)"
        )


async def start_session(agent_type: str) -> SimulationSession:
    proposal = await get_latest_proposal(agent_type)
    if proposal is None or proposal.status != CompositionStatus.APPROVED:
        raise ValueError(f"No approved composition for '{agent_type}'")

    session = SimulationSession(
        agent_type_id=agent_type,
        composition_version=proposal.version,
    )
    _sessions[session.id] = session
    _session_agents[session.id] = [
        agent.model_copy(deep=True) for agent in proposal.agents
    ]
    return session


def get_session(session_id: str) -> SimulationSession:
    session = _sessions.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def submit_turn(
    session_id: str,
    turn_input: SimulationTurnInput,
    to_agent: str,
    message_fields: dict,
) -> SimulationTurnResult:
    session = get_session(session_id)
    if session.status == "closed":
        raise ValueError(f"Session '{session_id}' is closed")

    unresolved = _count_unresolved_violations(session)
    if unresolved:
        raise SessionPausedForViolation(session_id, unresolved)

    agents = _session_agents[session_id]
    violations = validate_message(
        message_fields,
        turn_input.role,
        to_agent,
        agents,
    )
    turn_index = len(session.turn_history)
    observations = _observations_for_turn(
        turn_input.role,
        to_agent,
        turn_index,
        violations,
    )
    result = SimulationTurnResult(
        turn_index=turn_index,
        role=turn_input.role,
        message=turn_input.message,
        violations=violations,
        observations=observations,
        paused_for_violation=bool(violations),
    )

    session.turn_history.append(result)
    session.observations.extend(observations)
    session.current_role = turn_input.role
    return result


def resolve_violation(
    session_id: str,
    violation_index: int,
    resolution: str,
    clarification: str | None,
) -> dict:
    session = get_session(session_id)
    if not session.turn_history:
        raise ValueError("No turns recorded yet")

    last_turn = session.turn_history[-1]
    if violation_index >= len(last_turn.violations):
        raise IndexError(
            f"violation_index {violation_index} out of range "
            f"(turn has {len(last_turn.violations)} violations)"
        )

    violation = last_turn.violations[violation_index]
    updated_agents, coord_edge_written = apply_resolution(
        violation,
        resolution,
        clarification,
        _session_agents[session_id],
    )
    _session_agents[session_id] = updated_agents
    violation.resolution = resolution

    if coord_edge_written:
        session.coord_namespace_writes.append(
            {
                "type": "input_schema_update",
                "agent_name": violation.to_agent,
                "field": violation.field,
                "field_type": clarification,
                "turn_index": last_turn.turn_index,
            }
        )
        for observation in last_turn.observations:
            if (
                observation.type == ObservationType.VIOLATION
                and violation.from_agent in observation.roles_involved
                and violation.to_agent in observation.roles_involved
            ):
                observation.coord_edge_written = True

    last_turn.paused_for_violation = _count_unresolved_violations(session) > 0
    return {"resolved": True, "coord_edge_written": coord_edge_written}


async def close_session(session_id: str) -> dict:
    session = get_session(session_id)
    if session.status == "closed":
        raise ValueError(f"Session '{session_id}' already closed")

    agent_type = session.agent_type_id
    for agent in _session_agents[session_id]:
        _upsert_agent_role(agent_type, agent)

    coord_edges_written = len(session.coord_namespace_writes)
    coord_edges_written += _write_handoff_edges(agent_type, session)
    violations_total = sum(len(turn.violations) for turn in session.turn_history)
    violations_unresolved = _count_unresolved_violations(session)

    session.status = "closed"
    session.closed_at = datetime.now(UTC)
    return {
        "session_id": session_id,
        "coord_edges_written": coord_edges_written,
        "observations_captured": len(session.observations),
        "violations_total": violations_total,
        "violations_unresolved": violations_unresolved,
    }


def _count_unresolved_violations(session: SimulationSession) -> int:
    if not session.turn_history:
        return 0
    return sum(
        1
        for violation in session.turn_history[-1].violations
        if violation.resolution == "pending"
    )


def _observations_for_turn(
    from_agent: str,
    to_agent: str,
    turn_index: int,
    violations,
) -> list[SimulationObservation]:
    if not violations:
        return [
            SimulationObservation(
                type=ObservationType.LEARNED,
                description=f"{from_agent} -> {to_agent}: message conforms",
                turn_index=turn_index,
                roles_involved=[from_agent, to_agent],
            )
        ]

    return [
        SimulationObservation(
            type=ObservationType.VIOLATION,
            description=violation.reason,
            turn_index=turn_index,
            roles_involved=[violation.from_agent, violation.to_agent],
        )
        for violation in violations
    ]


def _upsert_agent_role(agent_type: str, agent: AgentContract) -> None:
    existing = _first_row(
        execute(
            agent_type,
            """
            MATCH (r:AgentRole)
            WHERE r.name = $name
            RETURN r.id
            """,
            {"name": agent.agent_name},
        )
    )
    payload = {
        "name": agent.agent_name,
        "input_schema": json.dumps(agent.input_schema),
        "output_schema": json.dumps(agent.output_schema),
        "prohibited_fields": json.dumps(agent.prohibited_fields),
    }

    if existing is not None:
        execute(
            agent_type,
            """
            MATCH (r:AgentRole)
            WHERE r.id = $id
            SET r.input_schema = $input_schema,
                r.output_schema = $output_schema,
                r.prohibited_fields = $prohibited_fields
            """,
            {"id": existing[0], **payload},
        )
        return

    execute(
        agent_type,
        """
        CREATE (:AgentRole {
            id: $id,
            name: $name,
            input_schema: $input_schema,
            output_schema: $output_schema,
            prohibited_fields: $prohibited_fields
        })
        """,
        {"id": f"role-{uuid.uuid4().hex[:12]}", **payload},
    )


def _write_handoff_edges(agent_type: str, session: SimulationSession) -> int:
    pair_stats: dict[tuple[str, str], dict[str, int]] = {}
    for turn in session.turn_history:
        for observation in turn.observations:
            if len(observation.roles_involved) != 2:
                continue
            pair = (observation.roles_involved[0], observation.roles_involved[1])
            stats = pair_stats.setdefault(pair, {"clean": 0, "total": 0})
            stats["total"] += 1
            if observation.type == ObservationType.LEARNED:
                stats["clean"] += 1

    edges_written = 0
    for (from_role, to_role), stats in pair_stats.items():
        confidence = stats["clean"] / stats["total"] if stats["total"] else 0.0
        if confidence <= 0:
            continue
        _upsert_handoff_edge(agent_type, from_role, to_role, round(confidence, 3))
        edges_written += 1
    return edges_written


def _upsert_handoff_edge(
    agent_type: str,
    from_role: str,
    to_role: str,
    confidence: float,
) -> None:
    existing = _first_row(
        execute(
            agent_type,
            """
            MATCH (a:AgentRole)-[h:HANDS_OFF_TO]->(b:AgentRole)
            WHERE a.name = $from_role AND b.name = $to_role
            RETURN h.confidence
            """,
            {"from_role": from_role, "to_role": to_role},
        )
    )
    if existing is not None:
        execute(
            agent_type,
            """
            MATCH (a:AgentRole)-[h:HANDS_OFF_TO]->(b:AgentRole)
            WHERE a.name = $from_role AND b.name = $to_role
            SET h.confidence = $confidence
            """,
            {
                "from_role": from_role,
                "to_role": to_role,
                "confidence": confidence,
            },
        )
        return

    execute(
        agent_type,
        """
        MATCH (a:AgentRole), (b:AgentRole)
        WHERE a.name = $from_role AND b.name = $to_role
        CREATE (a)-[:HANDS_OFF_TO {
            condition: 'observed during simulation',
            validates: '[]',
            confidence: $confidence
        }]->(b)
        """,
        {
            "from_role": from_role,
            "to_role": to_role,
            "confidence": confidence,
        },
    )


def _first_row(result):
    if not result.has_next():
        return None
    return result.get_next()
