from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

import asyncpg


class PostgresDatabase(StrEnum):
    CHECKPOINTS = "checkpoints"
    KNOWLEDGE = "knowledge"
    OPS = "ops"


DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10

DEFAULT_DATABASE_URLS = {
    PostgresDatabase.CHECKPOINTS: "postgresql://agent:agent@localhost:5432/agent_checkpoints",
    PostgresDatabase.KNOWLEDGE: "postgresql://agent:agent@localhost:5432/agent_knowledge",
    PostgresDatabase.OPS: "postgresql://agent:agent@localhost:5432/agent_ops",
}

DATABASE_URL_ENV = {
    PostgresDatabase.CHECKPOINTS: "DATABASE_URL",
    PostgresDatabase.KNOWLEDGE: "KNOWLEDGE_DB_URL",
    PostgresDatabase.OPS: "OPS_DB_URL",
}

OPS_SCHEMA_DDL = [
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    """
    CREATE TABLE IF NOT EXISTS delta_entries (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_type VARCHAR(100) NOT NULL,
        agent_instance_id VARCHAR(100) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'quarantine',
        observation_type VARCHAR(20) NOT NULL,
        edge_data JSONB NOT NULL,
        triggered_by_task_id VARCHAR(100) NOT NULL,
        confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        reviewed_at TIMESTAMP,
        reviewed_by VARCHAR(100),
        rejection_reason TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_delta_agent_type ON delta_entries(agent_type)",
    "CREATE INDEX IF NOT EXISTS idx_delta_status ON delta_entries(status)",
    """
    CREATE TABLE IF NOT EXISTS team_compositions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_type VARCHAR(100) NOT NULL,
        version INT NOT NULL,
        topology VARCHAR(20) NOT NULL,
        agent_list JSONB NOT NULL,
        contracts JSONB NOT NULL,
        rationale JSONB,
        expert_signature VARCHAR(200),
        signed_at TIMESTAMP,
        status VARCHAR(20) NOT NULL DEFAULT 'proposed',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(agent_type, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cert_events (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_type VARCHAR(100) NOT NULL,
        gate VARCHAR(10) NOT NULL,
        decision VARCHAR(10) NOT NULL,
        expert_id VARCHAR(100) NOT NULL,
        readiness_score FLOAT NOT NULL,
        notes TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cert_agent_type ON cert_events(agent_type)",
    """
    CREATE TABLE IF NOT EXISTS shadow_reviews (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        task_id VARCHAR(100) NOT NULL,
        agent_type VARCHAR(100) NOT NULL,
        instance_id VARCHAR(100) NOT NULL,
        task_input JSONB NOT NULL,
        task_output JSONB NOT NULL,
        action_log JSONB NOT NULL,
        confidence_score FLOAT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        flag_category VARCHAR(30),
        flag_description TEXT,
        reviewed_by VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        reviewed_at TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_shadow_agent_type_status
    ON shadow_reviews(agent_type, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS escalation_events (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        task_id VARCHAR(100) NOT NULL,
        agent_type VARCHAR(100) NOT NULL,
        instance_id VARCHAR(100) NOT NULL,
        reason VARCHAR(30) NOT NULL,
        task_summary TEXT NOT NULL,
        scope_similarity_score FLOAT,
        routed_to VARCHAR(20) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
]


@dataclass(frozen=True)
class PostgresPoolConfig:
    database: PostgresDatabase
    dsn: str
    min_size: int = DEFAULT_POOL_MIN_SIZE
    max_size: int = DEFAULT_POOL_MAX_SIZE


def _normalize_asyncpg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def get_pool_config(database: PostgresDatabase) -> PostgresPoolConfig:
    env_name = DATABASE_URL_ENV[database]
    dsn = os.getenv(env_name, DEFAULT_DATABASE_URLS[database])
    min_size = int(os.getenv("POSTGRES_POOL_MIN_SIZE", str(DEFAULT_POOL_MIN_SIZE)))
    max_size = int(os.getenv("POSTGRES_POOL_MAX_SIZE", str(DEFAULT_POOL_MAX_SIZE)))
    return PostgresPoolConfig(
        database=database,
        dsn=_normalize_asyncpg_dsn(dsn),
        min_size=min_size,
        max_size=max_size,
    )


async def create_pool(database: PostgresDatabase) -> asyncpg.Pool:
    config = get_pool_config(database)
    return await asyncpg.create_pool(
        dsn=config.dsn,
        min_size=config.min_size,
        max_size=config.max_size,
    )


async def initialize_ops_schema(pool: asyncpg.Pool | None = None) -> None:
    owned_pool = pool is None
    active_pool = pool or await create_pool(PostgresDatabase.OPS)
    try:
        async with active_pool.acquire() as conn:
            for ddl in OPS_SCHEMA_DDL:
                await conn.execute(ddl)
    finally:
        if owned_pool:
            await active_pool.close()
