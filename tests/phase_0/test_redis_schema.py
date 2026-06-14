from __future__ import annotations

import uuid

import pytest

from src.infra.redis_client import (
    agent_state_key,
    context_stream_key,
    create_redis_client,
    readiness_key,
)


@pytest.mark.asyncio
async def test_redis_key_patterns_hset_hget_xadd_xread() -> None:
    client = create_redis_client()
    agent_type = f"phase0-{uuid.uuid4()}"
    state_key = agent_state_key(agent_type)
    score_key = readiness_key(agent_type)
    stream_key = context_stream_key(agent_type)

    assert state_key == f"agent:{agent_type}:state"
    assert score_key == f"agent:{agent_type}:readiness"
    assert stream_key == f"agent:{agent_type}:context"

    try:
        await client.hset(
            state_key,
            mapping={
                "phase": "apprentice",
                "learning_rate": "1.0",
                "graph_initialized": "false",
            },
        )
        state = await client.hgetall(state_key)
        assert state == {
            "phase": "apprentice",
            "learning_rate": "1.0",
            "graph_initialized": "false",
        }

        await client.hset(
            score_key,
            mapping={
                "score": "0.42",
                "proposal_ready": "false",
                "cert_ready": "false",
            },
        )
        assert await client.hget(score_key, "score") == "0.42"
        assert await client.hget(score_key, "proposal_ready") == "false"
        assert await client.hget(score_key, "cert_ready") == "false"

        message_id = await client.xadd(
            stream_key,
            {
                "event": "readiness_updated",
                "score": "0.42",
            },
        )
        messages = await client.xread({stream_key: "0-0"}, count=1, block=1000)

        assert len(messages) == 1
        returned_stream, returned_messages = messages[0]
        assert returned_stream == stream_key
        assert returned_messages == [
            (
                message_id,
                {
                    "event": "readiness_updated",
                    "score": "0.42",
                },
            )
        ]
    finally:
        await client.delete(state_key, score_key, stream_key)
        await client.aclose()
