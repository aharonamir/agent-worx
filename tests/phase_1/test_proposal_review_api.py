from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from src.api.main import app
from src.core.enums import Phase, TopologyType
from src.core.models import AgentTypeResponse, ProposalArtifact
from src.core.redis_keys import agent_proposal_ready_key
from src.infra.postgres_client import (
    close_pool,
    get_pool,
    init_pool,
    initialize_knowledge_schema,
)
from src.infra.redis_client import close_client, redis_delete, redis_set


@pytest_asyncio.fixture
async def review_db(monkeypatch):
    pool = await init_pool()
    await initialize_knowledge_schema(pool)
    yield pool
    await _delete_test_proposals()
    await close_pool()
    close_client()


@pytest.fixture(autouse=True)
def proposal_agent_lookup(monkeypatch):
    async def fake_get_agent_type_by_name(agent_type_id: str) -> AgentTypeResponse:
        return AgentTypeResponse(
            agent_type_id="id-1",
            name=agent_type_id,
            goal="Take burger orders end-to-end",
            task_boundary="Burger ordering only, no payments",
            topic_list=["menu"],
            topology_type=TopologyType.PIPELINE,
            workflow_participants=[],
            phase=Phase.APPRENTICE,
            learning_rate=1.0,
            readiness_score=0.7,
            graph_initialized=True,
            created_at=datetime.now(UTC),
        )

    monkeypatch.setattr(
        "src.api.routes.proposals.get_agent_type_by_name",
        fake_get_agent_type_by_name,
    )


async def _delete_test_proposals() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM team_compositions WHERE agent_type LIKE 'review-agent-%'"
        )
    for suffix in "abcdefghi":
        redis_delete(agent_proposal_ready_key(f"review-agent-{suffix}"))


async def _seed_proposal(
    agent_type: str,
    version: int = 1,
    status: str = "proposed",
    expert_signature: str | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO team_compositions (
                agent_type,
                version,
                topology,
                agent_list,
                contracts,
                rationale,
                status,
                expert_signature,
                signed_at
            )
            VALUES (
                $1, $2, 'pipeline', $3::jsonb, '[]'::jsonb, $4::jsonb,
                $5, $6, $7
            )
            """,
            agent_type,
            version,
            json.dumps(
                [
                    {
                        "agent_name": "test-agent",
                        "input_schema": {},
                        "output_schema": {},
                        "prohibited_fields": [],
                    }
                ]
            ),
            json.dumps(
                {
                    "rationale_per_agent": {"test-agent": "r"},
                    "rationale_per_contract": {},
                }
            ),
            status,
            expert_signature,
            datetime.now(UTC).replace(tzinfo=None) if expert_signature else None,
        )


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_proposal_returns_null_when_not_ready(review_db) -> None:
    agent_type = "review-agent-a"
    await _seed_proposal(agent_type)
    redis_set(agent_proposal_ready_key(agent_type), "false")

    async with _client() as client:
        resp = await client.get(f"/api/v1/agent-types/{agent_type}/proposal")

    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_get_proposal_returns_artifact_when_ready(review_db) -> None:
    agent_type = "review-agent-b"
    await _seed_proposal(agent_type)
    redis_set(agent_proposal_ready_key(agent_type), "true")

    async with _client() as client:
        resp = await client.get(f"/api/v1/agent-types/{agent_type}/proposal")

    data = resp.json()
    assert data["version"] == 1
    assert data["status"] == "proposed"


@pytest.mark.asyncio
async def test_approve_sets_signature(review_db) -> None:
    agent_type = "review-agent-c"
    await _seed_proposal(agent_type)

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={"action": "approve", "expert_id": "expert-jane"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM team_compositions WHERE agent_type = $1",
            agent_type,
        )

    assert row["status"] == "approved"
    assert row["expert_signature"] == "expert-jane"
    assert row["signed_at"] is not None


@pytest.mark.asyncio
async def test_approve_already_approved_returns_409(review_db) -> None:
    agent_type = "review-agent-d"
    await _seed_proposal(agent_type, status="approved", expert_signature="expert-jane")

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={"action": "approve", "expert_id": "expert-jane"},
        )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_edit_archives_old_and_creates_new_version(review_db) -> None:
    agent_type = "review-agent-e"
    await _seed_proposal(agent_type)
    edits_payload = {
        "agent_type_id": agent_type,
        "version": 99,
        "topology": "pipeline",
        "agents": [
            {
                "agent_name": "edited-agent",
                "input_schema": {},
                "output_schema": {},
                "prohibited_fields": [],
            }
        ],
        "contracts": [],
        "rationale_per_agent": {"edited-agent": "expert renamed this agent"},
        "rationale_per_contract": {},
    }

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={
                "action": "edit",
                "expert_id": "expert-jane",
                "edits": edits_payload,
            },
        )

    assert resp.status_code == 200

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM team_compositions
            WHERE agent_type = $1
            ORDER BY version
            """,
            agent_type,
        )

    assert len(rows) == 2
    assert rows[0]["status"] == "archived"
    assert rows[0]["version"] == 1
    assert rows[1]["status"] == "approved"
    assert rows[1]["version"] == 2
    assert rows[1]["expert_signature"] == "expert-jane"
    assert json.loads(rows[1]["agent_list"])[0]["agent_name"] == "edited-agent"


@pytest.mark.asyncio
async def test_edit_approved_returns_409_without_mutating(review_db) -> None:
    agent_type = "review-agent-h"
    await _seed_proposal(agent_type, status="approved", expert_signature="expert-jane")
    edits_payload = {
        "agent_type_id": agent_type,
        "topology": "pipeline",
        "agents": [
            {
                "agent_name": "edited-agent",
                "input_schema": {},
                "output_schema": {},
                "prohibited_fields": [],
            }
        ],
        "contracts": [],
        "rationale_per_agent": {"edited-agent": "r"},
        "rationale_per_contract": {},
    }

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={
                "action": "edit",
                "expert_id": "expert-jane",
                "edits": edits_payload,
            },
        )

    assert resp.status_code == 409
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT version, status FROM team_compositions WHERE agent_type = $1",
            agent_type,
        )
    assert [(row["version"], row["status"]) for row in rows] == [(1, "approved")]


@pytest.mark.asyncio
async def test_reject_archives_with_reason_and_reproposes(
    review_db,
    monkeypatch,
) -> None:
    agent_type = "review-agent-f"
    await _seed_proposal(agent_type)
    mock_new_proposal = ProposalArtifact(
        id="00000000-0000-0000-0000-0000000000f2",
        agent_type_id=agent_type,
        version=2,
        topology=TopologyType.PIPELINE,
        agents=[
            {
                "agent_name": "v2-agent",
                "input_schema": {},
                "output_schema": {},
                "prohibited_fields": [],
            }
        ],
        contracts=[],
        rationale_per_agent={"v2-agent": "incorporates feedback"},
        rationale_per_contract={},
    )
    repropose = AsyncMock(return_value=mock_new_proposal)
    monkeypatch.setattr(
        "src.apprentice.proposal_review_service.generate_proposal",
        repropose,
    )

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={
                "action": "reject",
                "rejection_reason": "Too many agents for this domain size",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "re_proposed"
    assert resp.json()["new_proposal"]["version"] == 2
    repropose.assert_awaited_once()

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM team_compositions
            WHERE agent_type = $1 AND version = 1
            """,
            agent_type,
        )

    assert row["status"] == "archived"
    rationale = json.loads(row["rationale"])
    assert rationale["rejection_reason"] == "Too many agents for this domain size"


@pytest.mark.asyncio
async def test_invalid_action_returns_400(review_db) -> None:
    agent_type = "review-agent-g"
    await _seed_proposal(agent_type)

    async with _client() as client:
        resp = await client.put(
            f"/api/v1/agent-types/{agent_type}/proposal",
            json={"action": "bogus"},
        )

    assert resp.status_code == 400
