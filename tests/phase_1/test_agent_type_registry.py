from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from src.api.main import app
from src.core.redis_keys import (
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
from src.infra.kuzu_client import close_connections
from src.infra.redis_client import close_client, redis_delete, redis_get


@pytest_asyncio.fixture
async def app_ready() -> AsyncIterator[None]:
    pool = await init_pool()
    await initialize_knowledge_schema(pool)
    yield
    close_connections()
    await close_pool()
    close_client()


@pytest.fixture
def valid_payload() -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "name": f"burger-order-{suffix}",
        "goal": "Take and process burger orders end-to-end",
        "task_boundary": (
            "Burger ordering only. No payment processing, kitchen ops, or delivery."
        ),
        "topic_list": [
            "menu items",
            "order flow",
            "allergens",
            "modifiers",
            "upselling rules",
        ],
        "topology_type": "orchestrated",
        "workflow_participants": ["kitchen-agent", "payment-agent"],
    }


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _result_rows(result) -> list[list]:
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


async def _delete_agent_type(name: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM agent_types WHERE name = $1", name)
    redis_delete(agent_phase_key(name))
    redis_delete(agent_learning_rate_key(name))
    redis_delete(agent_readiness_score_key(name))


@pytest.mark.asyncio
async def test_create_agent_type_returns_201(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    try:
        assert resp.status_code == 201
        data = resp.json()
        assert data["graph_initialized"] is True
        assert data["phase"] == "apprentice"
        assert data["learning_rate"] == 1.0
        assert data["readiness_score"] == 0.0
    finally:
        await _delete_agent_type(valid_payload["name"])


@pytest.mark.asyncio
async def test_kuzu_graph_has_root_nodes(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    from src.infra.kuzu_client import execute

    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    try:
        assert resp.status_code == 201
        rows = _result_rows(
            execute(
                valid_payload["name"],
                """
                MATCH (c:Concept)
                WHERE c.namespace = 'task'
                RETURN c.label AS label, c.confidence AS conf
                """,
            )
        )

        labels = {row[0] for row in rows}
        confidences = [row[1] for row in rows]

        assert len(rows) == len(valid_payload["topic_list"])
        assert labels == set(valid_payload["topic_list"])
        assert all(confidence == 0.0 for confidence in confidences)
    finally:
        await _delete_agent_type(valid_payload["name"])


@pytest.mark.asyncio
async def test_redis_state_initialized(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    name = valid_payload["name"]

    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    try:
        assert resp.status_code == 201
        assert redis_get(agent_phase_key(name)) == "apprentice"
        assert redis_get(agent_learning_rate_key(name)) == "1.0"
        assert redis_get(agent_readiness_score_key(name)) == "0.0"
    finally:
        await _delete_agent_type(name)


@pytest.mark.asyncio
async def test_duplicate_name_returns_409(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    async with _client() as client:
        first = await client.post("/api/v1/agent-types", json=valid_payload)
        second = await client.post("/api/v1/agent-types", json=valid_payload)

    try:
        assert first.status_code == 201
        assert second.status_code == 409
    finally:
        await _delete_agent_type(valid_payload["name"])


@pytest.mark.asyncio
async def test_empty_topic_list_returns_400(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    valid_payload["topic_list"] = []

    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404(app_ready) -> None:
    async with _client() as client:
        resp = await client.get(
            "/api/v1/agent-types/00000000-0000-0000-0000-000000000000"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_agent_type_returns_created_agent(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))
    async with _client() as client:
        created = await client.post("/api/v1/agent-types", json=valid_payload)
        agent_id = created.json()["agent_type_id"]
        fetched = await client.get(f"/api/v1/agent-types/{agent_id}")

    try:
        assert fetched.status_code == 200
        data = fetched.json()
        assert data["name"] == valid_payload["name"]
        assert data["topic_list"] == valid_payload["topic_list"]
        assert data["workflow_participants"] == valid_payload["workflow_participants"]
        assert data["phase"] == "apprentice"
    finally:
        await _delete_agent_type(valid_payload["name"])


@pytest.mark.asyncio
async def test_kuzu_failure_rolls_back_postgres_row(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))

    def boom(agent_type: str) -> None:
        raise RuntimeError("simulated Kuzu failure")

    monkeypatch.setattr("src.core.agent_type_service.initialize_schema", boom)

    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    assert resp.status_code == 500
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_types WHERE name = $1",
            valid_payload["name"],
        )
    assert row is None


@pytest.mark.asyncio
async def test_redis_failure_rolls_back_postgres_and_kuzu(
    valid_payload: dict,
    app_ready,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))

    def fail_on_readiness(key: str, value: str, ttl_seconds: int | None = None) -> None:
        if key.endswith(":readiness_score"):
            raise RuntimeError("simulated Redis failure")

    monkeypatch.setattr("src.core.agent_type_service.redis_set", fail_on_readiness)

    async with _client() as client:
        resp = await client.post("/api/v1/agent-types", json=valid_payload)

    assert resp.status_code == 500
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_types WHERE name = $1",
            valid_payload["name"],
        )
    assert row is None

    from src.infra.kuzu_client import execute

    rows = _result_rows(
        execute(
            valid_payload["name"],
            "MATCH (c:Concept) RETURN c.id AS id",
        )
    )
    assert len(rows) == 0
