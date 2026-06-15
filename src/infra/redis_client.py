from __future__ import annotations

import os
from dataclasses import dataclass

import redis

from src.core.enums import Phase
from src.core.redis_keys import (
    agent_cert_ready_key,
    agent_learning_rate_key,
    agent_phase_key,
    agent_proposal_ready_key,
    agent_readiness_score_key,
    workflow_context_stream_key,
)


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_MAX_CONNECTIONS = 20

_client: redis.Redis | None = None


def agent_state_key(agent_type: str) -> str:
    return f"agent:{agent_type}:state"


def readiness_key(agent_type: str) -> str:
    return f"agent:{agent_type}:readiness"


def context_stream_key(agent_type: str) -> str:
    return f"agent:{agent_type}:context"


@dataclass(frozen=True)
class RedisConfig:
    url: str = DEFAULT_REDIS_URL
    max_connections: int = DEFAULT_MAX_CONNECTIONS


def get_redis_config() -> RedisConfig:
    return RedisConfig(
        url=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
        max_connections=int(
            os.getenv("REDIS_MAX_CONNECTIONS", str(DEFAULT_MAX_CONNECTIONS))
        ),
    )


def create_redis_client() -> redis.Redis:
    config = get_redis_config()
    return redis.from_url(
        config.url,
        decode_responses=True,
        max_connections=config.max_connections,
    )


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = create_redis_client()
    return _client


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def redis_get(key: str) -> str | None:
    return get_client().get(key)


def redis_set(key: str, value: str, ttl_seconds: int | None = None) -> None:
    if ttl_seconds is None:
        get_client().set(key, value)
    else:
        get_client().set(key, value, ex=ttl_seconds)


def redis_delete(key: str) -> None:
    get_client().delete(key)


def redis_hset(key: str, mapping: dict[str, str]) -> None:
    get_client().hset(key, mapping=mapping)


def redis_hgetall(key: str) -> dict[str, str]:
    return get_client().hgetall(key)


def redis_hget(key: str, field: str) -> str | None:
    return get_client().hget(key, field)


def stream_add(stream_key: str, fields: dict[str, str], maxlen: int = 1000) -> str:
    return get_client().xadd(stream_key, fields, maxlen=maxlen, approximate=True)


def stream_read(stream_key: str, last_id: str = "0", count: int = 10) -> list:
    return get_client().xread({stream_key: last_id}, count=count, block=100)


def stream_set_ttl(stream_key: str, ttl_seconds: int) -> None:
    get_client().expire(stream_key, ttl_seconds)


def verify_redisearch_module() -> bool:
    modules = get_client().module_list()
    module_names = {
        str(module.get("name", "")).lower()
        for module in modules
        if isinstance(module, dict)
    }
    return "ft" in module_names or "search" in module_names


def get_agent_state(agent_type: str) -> dict[str, str | float | bool]:
    client = get_client()
    pipe = client.pipeline()
    pipe.get(agent_phase_key(agent_type))
    pipe.get(agent_learning_rate_key(agent_type))
    pipe.get(agent_readiness_score_key(agent_type))
    pipe.get(agent_proposal_ready_key(agent_type))
    pipe.get(agent_cert_ready_key(agent_type))
    phase, lr, score, prop_ready, cert_ready = pipe.execute()

    return {
        "phase": phase or Phase.APPRENTICE.value,
        "learning_rate": float(lr) if lr else 1.0,
        "readiness_score": float(score) if score else 0.0,
        "proposal_ready": prop_ready == "true",
        "cert_ready": cert_ready == "true",
    }


def set_agent_phase(agent_type: str, phase: Phase, learning_rate: float) -> None:
    client = get_client()
    pipe = client.pipeline()
    pipe.set(agent_phase_key(agent_type), phase.value)
    pipe.set(agent_learning_rate_key(agent_type), str(learning_rate))
    pipe.execute()


def workflow_stream_key(workflow_id: str) -> str:
    return workflow_context_stream_key(workflow_id)
