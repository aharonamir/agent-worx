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
