from __future__ import annotations

import os
import json
from dataclasses import dataclass
from enum import StrEnum

import asyncpg

from src.core.enums import DeltaStatus
from src.core.models import CertEvent, DeltaEntry, EscalationEvent


class PostgresDatabase(StrEnum):
    CHECKPOINTS = "checkpoints"
    KNOWLEDGE = "knowledge"
    OPS = "ops"


DEFAULT_POOL_MIN_SIZE = 2
DEFAULT_POOL_MAX_SIZE = 20

DEFAULT_DATABASE_URLS = {
    PostgresDatabase.CHECKPOINTS: "postgresql://alf:alfpass@localhost:5432/agent_checkpoints",
    PostgresDatabase.KNOWLEDGE: "postgresql://alf:alfpass@localhost:5432/agent_knowledge",
    PostgresDatabase.OPS: "postgresql://alf:alfpass@localhost:5432/agent_ops",
}

DATABASE_URL_ENV = {
    PostgresDatabase.CHECKPOINTS: "DATABASE_URL",
    PostgresDatabase.KNOWLEDGE: "KNOWLEDGE_DB_URL",
    PostgresDatabase.OPS: "OPS_DB_URL",
}

_pool: asyncpg.Pool | None = None


KNOWLEDGE_SCHEMA_DDL = [
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS agent_types (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name VARCHAR(100) NOT NULL UNIQUE,
        goal TEXT NOT NULL,
        task_boundary TEXT NOT NULL,
        topic_list JSONB NOT NULL,
        topology_type VARCHAR(20) NOT NULL,
        workflow_participants JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_types_name ON agent_types(name)",
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
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_delta_status'
        ) THEN
            ALTER TABLE delta_entries
            ADD CONSTRAINT chk_delta_status
            CHECK (status IN ('quarantine', 'approved', 'rejected', 'flagged'));
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_delta_observation_type'
        ) THEN
            ALTER TABLE delta_entries
            ADD CONSTRAINT chk_delta_observation_type
            CHECK (observation_type IN ('violation', 'learned', 'ambiguous'));
        END IF;
    END $$;
    """,
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
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_composition_status'
        ) THEN
            ALTER TABLE team_compositions
            ADD CONSTRAINT chk_composition_status
            CHECK (status IN ('proposed', 'approved', 'archived'));
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_composition_agent_type ON team_compositions(agent_type)",
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
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_cert_gate'
        ) THEN
            ALTER TABLE cert_events
            ADD CONSTRAINT chk_cert_gate CHECK (gate IN ('cert1', 'cert2'));
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_cert_decision'
        ) THEN
            ALTER TABLE cert_events
            ADD CONSTRAINT chk_cert_decision
            CHECK (decision IN ('approved', 'rejected'));
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_cert_agent_type ON cert_events(agent_type)",
    """
    CREATE TABLE IF NOT EXISTS simulation_session_summaries (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_type VARCHAR(100) NOT NULL,
        session_id VARCHAR(100) NOT NULL,
        composition_version INT NOT NULL,
        coord_edges_written INT NOT NULL,
        observations_captured INT NOT NULL,
        violations_total INT NOT NULL,
        violations_unresolved INT NOT NULL,
        closed_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sim_summary_agent_type
    ON simulation_session_summaries(agent_type)
    """,
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
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_shadow_status'
        ) THEN
            ALTER TABLE shadow_reviews
            ADD CONSTRAINT chk_shadow_status
            CHECK (status IN ('pending', 'approved', 'flagged', 'escalated'));
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_shadow_flag_category'
        ) THEN
            ALTER TABLE shadow_reviews
            ADD CONSTRAINT chk_shadow_flag_category
            CHECK (
                flag_category IS NULL
                OR flag_category IN (
                    'wrong_output',
                    'wrong_handoff',
                    'missed_constraint'
                )
            );
        END IF;
    END $$;
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
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_escalation_reason'
        ) THEN
            ALTER TABLE escalation_events
            ADD CONSTRAINT chk_escalation_reason
            CHECK (
                reason IN (
                    'out_of_scope',
                    'action_prohibited',
                    'max_iterations',
                    'worker_failure'
                )
            );
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'chk_escalation_routed_to'
        ) THEN
            ALTER TABLE escalation_events
            ADD CONSTRAINT chk_escalation_routed_to
            CHECK (routed_to IN ('orchestrator', 'human_queue'));
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_escalation_agent_type ON escalation_events(agent_type)",
]

OPS_SCHEMA_DDL = KNOWLEDGE_SCHEMA_DDL


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


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_pool(PostgresDatabase.KNOWLEDGE)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized; call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def initialize_knowledge_schema(pool: asyncpg.Pool | None = None) -> None:
    owned_pool = pool is None
    active_pool = pool or await create_pool(PostgresDatabase.KNOWLEDGE)
    try:
        async with active_pool.acquire() as conn:
            for ddl in KNOWLEDGE_SCHEMA_DDL:
                await conn.execute(ddl)
    finally:
        if owned_pool:
            await active_pool.close()


async def initialize_ops_schema(pool: asyncpg.Pool | None = None) -> None:
    await initialize_knowledge_schema(pool)


async def insert_delta_entry(entry: DeltaEntry) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO delta_entries (
                id,
                agent_type,
                agent_instance_id,
                status,
                observation_type,
                edge_data,
                triggered_by_task_id,
                confidence,
                created_at
            )
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            entry.id,
            entry.agent_type,
            entry.agent_instance_id,
            entry.status.value,
            entry.observation_type.value,
            json.dumps(entry.edge_data),
            entry.triggered_by_task_id,
            entry.confidence,
            entry.created_at,
        )


async def get_quarantine_entries(agent_type: str) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM delta_entries
            WHERE agent_type = $1
              AND status = $2
            ORDER BY created_at ASC
            """,
            agent_type,
            DeltaStatus.QUARANTINE.value,
        )
    return [dict(row) for row in rows]


async def insert_cert_event(event: CertEvent) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cert_events (
                id,
                agent_type,
                gate,
                decision,
                expert_id,
                readiness_score,
                notes,
                created_at
            )
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
            """,
            event.id,
            event.agent_type,
            event.gate.value,
            event.decision.value,
            event.expert_id,
            event.readiness_score,
            event.notes,
            event.created_at.replace(tzinfo=None),
        )


async def insert_simulation_session_summary(summary: dict) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO simulation_session_summaries (
                agent_type,
                session_id,
                composition_version,
                coord_edges_written,
                observations_captured,
                violations_total,
                violations_unresolved,
                closed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            summary["agent_type"],
            summary["session_id"],
            summary["composition_version"],
            summary["coord_edges_written"],
            summary["observations_captured"],
            summary["violations_total"],
            summary["violations_unresolved"],
            summary["closed_at"],
        )


async def insert_escalation_event(event: EscalationEvent) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO escalation_events (
                id,
                task_id,
                agent_type,
                instance_id,
                reason,
                task_summary,
                scope_similarity_score,
                routed_to,
                created_at
            )
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event.id,
            event.task_id,
            event.agent_type,
            event.instance_id,
            event.reason,
            event.task_summary,
            event.scope_similarity_score,
            event.routed_to,
            event.created_at,
        )
