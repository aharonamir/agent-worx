from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

import redis.asyncio as redis


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_MAX_CONNECTIONS = 20


class RedisHash(StrEnum):
    AGENT_STATE = "agent:{agent_type}:state"
    READINESS = "agent:{agent_type}:readiness"


class RedisStream(StrEnum):
    CONTEXT_EVENTS = "agent:{agent_type}:context"


def agent_state_key(agent_type: str) -> str:
    return RedisHash.AGENT_STATE.format(agent_type=agent_type)


def readiness_key(agent_type: str) -> str:
    return RedisHash.READINESS.format(agent_type=agent_type)


def context_stream_key(agent_type: str) -> str:
    return RedisStream.CONTEXT_EVENTS.format(agent_type=agent_type)


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
