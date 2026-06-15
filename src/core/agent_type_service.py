from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from src.core.enums import Phase, TopologyType
from src.core.exceptions import AgentTypeAlreadyExists, AgentTypeNotFound
from src.core.models import AgentTypeCreate, AgentTypeResponse
from src.core.redis_keys import (
    agent_learning_rate_key,
    agent_phase_key,
    agent_readiness_score_key,
)
from src.infra.kuzu_client import execute as kuzu_execute
from src.infra.kuzu_client import initialize_schema
from src.infra.postgres_client import get_pool
from src.infra.redis_client import redis_delete, redis_get, redis_set


async def create_agent_type(payload: AgentTypeCreate) -> AgentTypeResponse:
    pool = get_pool()
    agent_type_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM agent_types WHERE name = $1",
            payload.name,
        )
        if existing:
            raise AgentTypeAlreadyExists(payload.name)

        await conn.execute(
            """
            INSERT INTO agent_types (
                id,
                name,
                goal,
                task_boundary,
                topic_list,
                topology_type,
                workflow_participants,
                created_at
            )
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8)
            """,
            agent_type_id,
            payload.name,
            payload.goal,
            payload.task_boundary,
            json.dumps(payload.topic_list),
            payload.topology_type.value,
            json.dumps(payload.workflow_participants),
            datetime.utcnow(),
        )

    created_concept_ids: list[str] = []
    redis_keys = [
        agent_phase_key(payload.name),
        agent_learning_rate_key(payload.name),
        agent_readiness_score_key(payload.name),
    ]

    try:
        initialize_schema(payload.name)
        now_str = datetime.utcnow().isoformat()
        for index, topic in enumerate(payload.topic_list):
            concept_id = f"root-{index}-{uuid.uuid4().hex[:8]}"
            kuzu_execute(
                payload.name,
                """
                CREATE (:Concept {
                    id: $id,
                    label: $label,
                    namespace: 'task',
                    confidence: 0.0,
                    created_at: $created_at
                })
                """,
                {"id": concept_id, "label": topic, "created_at": now_str},
            )
            created_concept_ids.append(concept_id)

        redis_set(agent_phase_key(payload.name), Phase.APPRENTICE.value)
        redis_set(agent_learning_rate_key(payload.name), "1.0")
        redis_set(agent_readiness_score_key(payload.name), "0.0")
    except Exception:
        for key in redis_keys:
            redis_delete(key)
        for concept_id in created_concept_ids:
            kuzu_execute(
                payload.name,
                "MATCH (c:Concept {id: $id}) DELETE c",
                {"id": concept_id},
            )
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_types WHERE id = $1::uuid", agent_type_id)
        raise

    return AgentTypeResponse(
        agent_type_id=agent_type_id,
        name=payload.name,
        goal=payload.goal,
        task_boundary=payload.task_boundary,
        topic_list=payload.topic_list,
        topology_type=payload.topology_type,
        workflow_participants=payload.workflow_participants,
        phase=Phase.APPRENTICE,
        learning_rate=1.0,
        readiness_score=0.0,
        graph_initialized=True,
        created_at=datetime.utcnow(),
    )


async def get_agent_type(agent_type_id: str) -> AgentTypeResponse:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_types WHERE id = $1::uuid",
            agent_type_id,
        )
    if row is None:
        raise AgentTypeNotFound(agent_type_id)
    return _row_to_response(dict(row))


async def get_agent_type_by_name(name: str) -> AgentTypeResponse:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_types WHERE name = $1", name)
    if row is None:
        raise AgentTypeNotFound(name)
    return _row_to_response(dict(row))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _row_to_response(row: dict[str, Any]) -> AgentTypeResponse:
    name = row["name"]
    phase = redis_get(agent_phase_key(name)) or Phase.APPRENTICE.value
    learning_rate = float(redis_get(agent_learning_rate_key(name)) or "1.0")
    readiness = float(redis_get(agent_readiness_score_key(name)) or "0.0")

    return AgentTypeResponse(
        agent_type_id=str(row["id"]),
        name=name,
        goal=row["goal"],
        task_boundary=row["task_boundary"],
        topic_list=_json_value(row["topic_list"]),
        topology_type=TopologyType(row["topology_type"]),
        workflow_participants=_json_value(row["workflow_participants"]),
        phase=Phase(phase),
        learning_rate=learning_rate,
        readiness_score=readiness,
        graph_initialized=True,
        created_at=row["created_at"],
    )
