from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.api.main import app
from src.apprentice.simulation import session_manager as sm
from src.core.enums import CompositionStatus, ObservationType, TopologyType
from src.core.models import AgentContract, ProposalArtifact, SimulationTurnInput
from src.infra.kuzu_client import close_connections, execute, initialize_schema


@pytest.fixture(autouse=True)
def clear_sessions():
    sm._sessions.clear()
    sm._session_agents.clear()
    yield
    sm._sessions.clear()
    sm._session_agents.clear()


@pytest.fixture
def agent_type(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    atype = "test-sim"
    initialize_schema(atype)
    yield atype
    close_connections()


def _approved_proposal(agent_type: str) -> ProposalArtifact:
    return ProposalArtifact(
        agent_type_id=agent_type,
        version=1,
        topology=TopologyType.ORCHESTRATED,
        agents=[
            AgentContract(
                agent_name="order-agent",
                input_schema={"items": "list[str]"},
                output_schema={"order_id": "str", "items": "list[str]"},
            ),
            AgentContract(
                agent_name="kitchen-agent",
                input_schema={"order_id": "str", "items": "list[str]"},
                output_schema={"est_minutes": "int"},
                prohibited_fields=["card_token"],
            ),
        ],
        contracts=[],
        rationale_per_agent={},
        rationale_per_contract={},
        status=CompositionStatus.APPROVED,
    )


def _rows(agent_type: str, query: str) -> list[list]:
    result = execute(agent_type, query)
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


async def _start(agent_type: str):
    with patch(
        "src.apprentice.simulation.session_manager.get_latest_proposal",
        new_callable=AsyncMock,
        return_value=_approved_proposal(agent_type),
    ):
        return await sm.start_session(agent_type)


@pytest.mark.asyncio
async def test_start_session_requires_approved_composition(agent_type: str) -> None:
    with patch(
        "src.apprentice.simulation.session_manager.get_latest_proposal",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(ValueError):
            await sm.start_session(agent_type)


@pytest.mark.asyncio
async def test_compliant_turn_produces_learned_observation(agent_type: str) -> None:
    session = await _start(agent_type)

    result = sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order placed: 2 burgers"),
        to_agent="kitchen-agent",
        message_fields={"order_id": "ord-1", "items": ["burger", "burger"]},
    )

    assert result.paused_for_violation is False
    assert len(result.observations) == 1
    assert result.observations[0].type == ObservationType.LEARNED


@pytest.mark.asyncio
async def test_violating_turn_pauses_session(agent_type: str) -> None:
    session = await _start(agent_type)

    result = sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order placed with card"),
        to_agent="kitchen-agent",
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "card_token": "tok_123",
        },
    )

    assert result.paused_for_violation is True
    assert len(result.violations) == 1
    assert result.violations[0].field == "card_token"
    assert result.violations[0].resolution == "pending"

    with pytest.raises(sm.SessionPausedForViolation):
        sm.submit_turn(
            session.id,
            SimulationTurnInput(role="order-agent", message="another message"),
            to_agent="kitchen-agent",
            message_fields={"order_id": "ord-2", "items": ["fries"]},
        )


@pytest.mark.asyncio
async def test_resolve_clarify_contract_unblocks_session(agent_type: str) -> None:
    session = await _start(agent_type)
    sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order placed with card"),
        to_agent="kitchen-agent",
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "card_token": "tok_123",
        },
    )

    resolution = sm.resolve_violation(
        session.id,
        0,
        resolution="clarify_contract",
        clarification="str",
    )

    assert resolution == {"resolved": True, "coord_edge_written": True}
    assert session.turn_history[-1].paused_for_violation is False
    assert session.turn_history[-1].observations[0].coord_edge_written is True
    assert sm._session_agents[session.id][1].input_schema["card_token"] == "str"

    result = sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="retry with card"),
        to_agent="kitchen-agent",
        message_fields={
            "order_id": "ord-2",
            "items": ["fries"],
            "card_token": "tok_456",
        },
    )
    assert result.paused_for_violation is False


@pytest.mark.asyncio
async def test_resolve_mark_edge_case_unblocks_without_contract_change(
    agent_type: str,
) -> None:
    session = await _start(agent_type)
    sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order placed with card"),
        to_agent="kitchen-agent",
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "card_token": "tok_123",
        },
    )

    resolution = sm.resolve_violation(
        session.id,
        0,
        resolution="mark_edge_case",
        clarification=None,
    )

    assert resolution == {"resolved": True, "coord_edge_written": False}
    assert "card_token" not in sm._session_agents[session.id][1].input_schema
    assert session.turn_history[-1].paused_for_violation is False


@pytest.mark.asyncio
async def test_close_session_writes_roles_and_handoff_edges(agent_type: str) -> None:
    session = await _start(agent_type)
    sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order ready for kitchen"),
        to_agent="kitchen-agent",
        message_fields={"order_id": "ord-1", "items": ["burger"]},
    )

    result = await sm.close_session(session.id)

    assert result["violations_unresolved"] == 0
    assert result["coord_edges_written"] == 1

    roles = _rows(agent_type, "MATCH (r:AgentRole) RETURN r.name")
    assert {row[0] for row in roles} == {"order-agent", "kitchen-agent"}

    edges = _rows(
        agent_type,
        """
        MATCH (a:AgentRole)-[h:HANDS_OFF_TO]->(b:AgentRole)
        RETURN a.name, b.name, h.confidence
        """,
    )
    assert edges[0][0] == "order-agent"
    assert edges[0][1] == "kitchen-agent"
    assert edges[0][2] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_submit_turn_round_trip_under_two_seconds(agent_type: str) -> None:
    session = await _start(agent_type)
    started = time.perf_counter()

    sm.submit_turn(
        session.id,
        SimulationTurnInput(role="order-agent", message="Order ready for kitchen"),
        to_agent="kitchen-agent",
        message_fields={"order_id": "ord-1", "items": ["burger"]},
    )

    assert time.perf_counter() - started < 2.0


@pytest.mark.asyncio
async def test_simulation_routes_create_and_read_session(agent_type: str) -> None:
    with patch(
        "src.apprentice.simulation.session_manager.get_latest_proposal",
        new_callable=AsyncMock,
        return_value=_approved_proposal(agent_type),
    ):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/api/v1/simulations",
                json={"agent_type_id": agent_type},
            )
            fetched = await client.get(
                f"/api/v1/simulations/{created.json()['id']}",
            )

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["agent_type_id"] == agent_type
