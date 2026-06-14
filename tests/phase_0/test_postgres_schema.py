from __future__ import annotations

import uuid

import pytest

from src.infra.postgres_client import PostgresDatabase, create_pool, initialize_ops_schema


POSTGRES_SCHEMA_TABLES = {
    "delta_entries",
    "team_compositions",
    "cert_events",
    "shadow_reviews",
    "escalation_events",
}

POSTGRES_SCHEMA_INDEXES = {
    "idx_delta_agent_type",
    "idx_delta_status",
    "idx_cert_agent_type",
    "idx_shadow_agent_type_status",
}


@pytest.mark.asyncio
async def test_postgres_ops_schema_tables_insert_select_round_trip() -> None:
    pool = await create_pool(PostgresDatabase.OPS)
    marker = f"phase0-{uuid.uuid4()}"
    try:
        await initialize_ops_schema(pool)

        async with pool.acquire() as conn:
            table_names = set(
                await conn.fetchval(
                    """
                    SELECT array_agg(table_name)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY($1::text[])
                    """,
                    list(POSTGRES_SCHEMA_TABLES),
                )
            )
            assert POSTGRES_SCHEMA_TABLES <= table_names

            uuid_extension_count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = 'uuid-ossp'"
            )
            assert uuid_extension_count == 1

            index_names = set(
                await conn.fetchval(
                    """
                    SELECT array_agg(indexname)
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = ANY($1::text[])
                    """,
                    list(POSTGRES_SCHEMA_INDEXES),
                )
            )
            assert POSTGRES_SCHEMA_INDEXES <= index_names

            delta_id = await conn.fetchval(
                """
                INSERT INTO delta_entries (
                    agent_type,
                    agent_instance_id,
                    observation_type,
                    edge_data,
                    triggered_by_task_id,
                    confidence
                )
                VALUES ($1, 'instance-1', 'learned', $2::jsonb, 'task-1', 0.7)
                RETURNING id
                """,
                marker,
                '{"source":"expert"}',
            )
            delta_status = await conn.fetchval(
                "SELECT status FROM delta_entries WHERE id = $1",
                delta_id,
            )
            assert delta_status == "quarantine"

            composition_id = await conn.fetchval(
                """
                INSERT INTO team_compositions (
                    agent_type,
                    version,
                    topology,
                    agent_list,
                    contracts,
                    rationale
                )
                VALUES ($1, 1, 'pipeline', $2::jsonb, $3::jsonb, $4::jsonb)
                RETURNING id
                """,
                marker,
                '[{"agent_name":"order-agent"}]',
                "[]",
                '{"order-agent":"single responsibility"}',
            )
            topology = await conn.fetchval(
                "SELECT topology FROM team_compositions WHERE id = $1",
                composition_id,
            )
            assert topology == "pipeline"

            cert_event_id = await conn.fetchval(
                """
                INSERT INTO cert_events (
                    agent_type,
                    gate,
                    decision,
                    expert_id,
                    readiness_score,
                    notes
                )
                VALUES ($1, 'cert1', 'approved', 'expert-1', 0.82, 'ready')
                RETURNING id
                """,
                marker,
            )
            cert_gate = await conn.fetchval(
                "SELECT gate FROM cert_events WHERE id = $1",
                cert_event_id,
            )
            assert cert_gate == "cert1"

            shadow_review_id = await conn.fetchval(
                """
                INSERT INTO shadow_reviews (
                    task_id,
                    agent_type,
                    instance_id,
                    task_input,
                    task_output,
                    action_log,
                    confidence_score
                )
                VALUES (
                    'task-1',
                    $1,
                    'instance-1',
                    $2::jsonb,
                    $3::jsonb,
                    $4::jsonb,
                    0.76
                )
                RETURNING id
                """,
                marker,
                '{"input":"value"}',
                '{"output":"value"}',
                '[{"action":"respond"}]',
            )
            shadow_status = await conn.fetchval(
                "SELECT status FROM shadow_reviews WHERE id = $1",
                shadow_review_id,
            )
            assert shadow_status == "pending"

            escalation_event_id = await conn.fetchval(
                """
                INSERT INTO escalation_events (
                    task_id,
                    agent_type,
                    instance_id,
                    reason,
                    task_summary,
                    scope_similarity_score,
                    routed_to
                )
                VALUES (
                    'task-2',
                    $1,
                    'instance-1',
                    'out_of_scope',
                    'needs human',
                    0.12,
                    'human_queue'
                )
                RETURNING id
                """,
                marker,
            )
            routed_to = await conn.fetchval(
                "SELECT routed_to FROM escalation_events WHERE id = $1",
                escalation_event_id,
            )
            assert routed_to == "human_queue"
    finally:
        async with pool.acquire() as conn:
            for table_name in POSTGRES_SCHEMA_TABLES:
                await conn.execute(
                    f"DELETE FROM {table_name} WHERE agent_type = $1",
                    marker,
                )
        await pool.close()


@pytest.mark.asyncio
async def test_postgres_ops_schema_idempotent() -> None:
    pool = await create_pool(PostgresDatabase.OPS)
    try:
        await initialize_ops_schema(pool)
        await initialize_ops_schema(pool)
    finally:
        await pool.close()
