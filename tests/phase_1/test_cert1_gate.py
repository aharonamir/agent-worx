from __future__ import annotations

import re
from pathlib import Path

import pytest
import pytest_asyncio

from src.apprentice.cert1_service import (
    approve_cert1,
    get_cert1_status,
    reject_cert1,
)
from src.core.enums import Phase
from src.core.exceptions import AgentNotInPhase
from src.core.models import CertApproveRequest, CertRejectRequest
from src.core.redis_keys import (
    agent_cert_ready_key,
    agent_learning_rate_key,
    agent_phase_key,
    agent_readiness_score_key,
)
from src.infra.postgres_client import (
    close_pool,
    get_pool,
    init_pool,
    initialize_knowledge_schema,
)
from src.infra.redis_client import (
    close_client,
    get_agent_state,
    redis_delete,
    redis_set,
)


@pytest_asyncio.fixture
async def cert_db():
    pool = await init_pool()
    await initialize_knowledge_schema(pool)
    yield pool
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM cert_events WHERE agent_type LIKE 'test-cert-%'")
        await conn.execute(
            "DELETE FROM simulation_session_summaries "
            "WHERE agent_type LIKE 'test-cert-%'"
        )
    await close_pool()
    close_client()


@pytest.fixture
def redis_state():
    def setup(
        agent_type: str,
        readiness: float,
        phase: str = Phase.APPRENTICE.value,
    ) -> None:
        redis_set(agent_phase_key(agent_type), phase)
        redis_set(agent_learning_rate_key(agent_type), "1.0")
        redis_set(agent_readiness_score_key(agent_type), str(readiness))
        redis_set(agent_cert_ready_key(agent_type), str(readiness >= 0.80).lower())

    yield setup

    for suffix in "abcdef":
        agent_type = f"test-cert-{suffix}"
        redis_delete(agent_phase_key(agent_type))
        redis_delete(agent_learning_rate_key(agent_type))
        redis_delete(agent_readiness_score_key(agent_type))
        redis_delete(agent_cert_ready_key(agent_type))


async def _insert_sim_summary(agent_type: str, unresolved: int) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO simulation_session_summaries (
                agent_type,
                session_id,
                composition_version,
                coord_edges_written,
                observations_captured,
                violations_total,
                violations_unresolved
            )
            VALUES ($1, 'sess-1', 1, 2, 5, 1, $2)
            """,
            agent_type,
            unresolved,
        )


@pytest.mark.asyncio
async def test_status_not_ready_without_simulation(redis_state, cert_db) -> None:
    redis_state("test-cert-a", readiness=0.85)

    status = await get_cert1_status("test-cert-a")

    assert status["readiness_score"] == 0.85
    assert status["simulation_runs_completed"] == 0
    assert status["violations_unresolved"] == 1
    assert status["cert_ready"] is False


@pytest.mark.asyncio
async def test_status_ready_with_clean_simulation(redis_state, cert_db) -> None:
    redis_state("test-cert-b", readiness=0.85)
    await _insert_sim_summary("test-cert-b", unresolved=0)

    status = await get_cert1_status("test-cert-b")

    assert status["cert_ready"] is True
    assert status["violations_unresolved"] == 0
    assert status["simulation_runs_completed"] == 1


@pytest.mark.asyncio
async def test_approve_succeeds_below_threshold(redis_state, cert_db) -> None:
    redis_state("test-cert-c", readiness=0.30)

    result = await approve_cert1(
        "test-cert-c",
        CertApproveRequest(expert_id="expert-jane", notes="ship it"),
    )

    assert result["new_phase"] == "journeyman"
    assert result["new_learning_rate"] == 0.5


@pytest.mark.asyncio
async def test_approve_updates_redis_and_writes_cert_event(
    redis_state,
    cert_db,
) -> None:
    redis_state("test-cert-d", readiness=0.85)

    await approve_cert1("test-cert-d", CertApproveRequest(expert_id="expert-jane"))

    state = get_agent_state("test-cert-d")
    assert state["phase"] == "journeyman"
    assert state["learning_rate"] == 0.5

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cert_events WHERE agent_type = 'test-cert-d'"
        )
    assert row["gate"] == "cert1"
    assert row["decision"] == "approved"
    assert row["expert_id"] == "expert-jane"


@pytest.mark.asyncio
async def test_approve_already_journeyman_raises(redis_state, cert_db) -> None:
    redis_state("test-cert-e", readiness=0.85, phase=Phase.JOURNEYMAN.value)

    with pytest.raises(AgentNotInPhase):
        await approve_cert1(
            "test-cert-e",
            CertApproveRequest(expert_id="expert-jane"),
        )


@pytest.mark.asyncio
async def test_reject_writes_event_and_keeps_apprentice(
    redis_state,
    cert_db,
) -> None:
    redis_state("test-cert-f", readiness=0.60)

    result = await reject_cert1(
        "test-cert-f",
        CertRejectRequest(
            expert_id="expert-jane",
            reason="Allergen coverage is too thin, needs more Q&A",
        ),
    )

    assert result["phase"] == "apprentice"
    assert get_agent_state("test-cert-f")["phase"] == "apprentice"

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cert_events WHERE agent_type = 'test-cert-f'"
        )
    assert row["decision"] == "rejected"


def test_no_other_codepath_writes_journeyman_phase() -> None:
    pattern = re.compile(r"set_agent_phase\([^)]*Phase\.JOURNEYMAN", re.DOTALL)
    allowed_files = {"cert1_service.py"}
    violations: list[str] = []

    for path in Path("src").rglob("*.py"):
        if path.name in allowed_files:
            continue
        if pattern.search(path.read_text()):
            violations.append(str(path))

    assert violations == []
