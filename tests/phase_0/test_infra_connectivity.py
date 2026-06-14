from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.infra.postgres_client import PostgresDatabase, create_pool, get_pool_config
from src.infra.redis_client import create_redis_client, get_redis_config
from src.temporal.config import get_temporal_config


ROOT = Path(__file__).resolve().parents[2]


def _compose_text() -> str:
    return (ROOT / "docker-compose.yml").read_text()


def test_temporal_compose_uses_pinned_images_and_namespace() -> None:
    compose = _compose_text()

    assert "temporalio/auto-setup:1.25.2" in compose
    assert "temporalio/ui:2.31.2" in compose
    assert "DEFAULT_NAMESPACE: agent-platform" in compose
    assert 'SKIP_DEFAULT_NAMESPACE_CREATION: "false"' in compose
    assert '"7233:7233"' in compose
    assert '"8080:8080"' in compose


def test_temporal_config_defaults_to_agent_platform(monkeypatch) -> None:
    monkeypatch.delenv("TEMPORAL_HOST", raising=False)
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)

    config = get_temporal_config()

    assert config.host == "localhost:7233"
    assert config.namespace == "agent-platform"


def test_sqlite_saver_is_not_imported() -> None:
    src_root = ROOT / "src"
    forbidden = {"SqliteSaver", "langgraph.checkpoint.sqlite"}

    for path in src_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden
        text = path.read_text()
        assert "SqliteSaver" not in text


def test_postgres_compose_creates_three_databases_with_pgvector() -> None:
    compose = _compose_text()

    assert "FROM postgres:16.4" in compose
    assert "postgresql-16-pgvector=0.8.2-1.pgdg12+1" in compose
    assert "dpkg -i --force-breaks" in compose
    assert "CREATE DATABASE agent_knowledge;" in compose
    assert "CREATE DATABASE agent_ops;" in compose
    assert "POSTGRES_DB: agent_checkpoints" in compose
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in compose
    assert '"5432:5432"' in compose
    assert '"max_connections=200"' in compose


def test_postgres_pool_config_defaults_to_three_databases(monkeypatch) -> None:
    for env_name in ("DATABASE_URL", "KNOWLEDGE_DB_URL", "OPS_DB_URL"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.delenv("POSTGRES_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("POSTGRES_POOL_MAX_SIZE", raising=False)

    configs = {
        database: get_pool_config(database)
        for database in (
            PostgresDatabase.CHECKPOINTS,
            PostgresDatabase.KNOWLEDGE,
            PostgresDatabase.OPS,
        )
    }

    assert configs[PostgresDatabase.CHECKPOINTS].dsn.endswith("/agent_checkpoints")
    assert configs[PostgresDatabase.KNOWLEDGE].dsn.endswith("/agent_knowledge")
    assert configs[PostgresDatabase.OPS].dsn.endswith("/agent_ops")
    assert all(config.min_size == 1 for config in configs.values())
    assert all(config.max_size == 10 for config in configs.values())


@pytest.mark.asyncio
async def test_postgres_databases_pgvector_and_pool_round_trip() -> None:
    expected_database_names = {
        PostgresDatabase.CHECKPOINTS: "agent_checkpoints",
        PostgresDatabase.KNOWLEDGE: "agent_knowledge",
        PostgresDatabase.OPS: "agent_ops",
    }

    for database, expected_name in expected_database_names.items():
        pool = await create_pool(database)
        try:
            async with pool.acquire() as conn:
                current_database = await conn.fetchval("SELECT current_database()")
                vector_extension_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
                )
                server_version = await conn.fetchval("SHOW server_version")
                pooled_connection_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND usename = current_user
                    """
                )
        finally:
            await pool.close()

        assert current_database == expected_name
        assert server_version.startswith("16.4")
        assert vector_extension_count == 1
        assert pooled_connection_count >= 1


def test_redis_compose_uses_pinned_base_with_redisearch() -> None:
    compose = _compose_text()

    assert "FROM redis:7.2.6" in compose
    assert "redis-redisearch=1:1.2.2-4" in compose
    assert "dpkg -i --force-depends" in compose
    assert "redis-server" in compose
    assert "--loadmodule" in compose
    assert "/usr/lib/redis/modules/redisearch.so" in compose
    assert '"6379:6379"' in compose


def test_redis_config_defaults_to_localhost(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_MAX_CONNECTIONS", raising=False)

    config = get_redis_config()

    assert config.url == "redis://localhost:6379/0"
    assert config.max_connections == 20


@pytest.mark.asyncio
async def test_redis_ping_redisearch_and_stream_round_trip() -> None:
    client = create_redis_client()
    stream_name = "test:phase0:stream"
    group_start = "0-0"
    try:
        assert await client.ping() is True

        info = await client.info("server")
        assert info["redis_version"].startswith("7.2.6")

        modules = await client.module_list()
        module_names = {
            module.get("name", "").lower()
            for module in modules
            if isinstance(module, dict)
        }
        assert "ft" in module_names

        await client.delete(stream_name)
        message_id = await client.xadd(stream_name, {"event": "round-trip"})
        messages = await client.xread({stream_name: group_start}, count=1, block=1000)

        assert message_id
        assert len(messages) == 1
        returned_stream_name, returned_messages = messages[0]
        assert returned_stream_name == stream_name
        assert returned_messages == [(message_id, {"event": "round-trip"})]
    finally:
        await client.delete(stream_name)
        await client.aclose()
