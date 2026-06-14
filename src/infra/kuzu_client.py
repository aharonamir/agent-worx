from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import kuzu


DEFAULT_KUZU_GRAPHS_DIR = Path("./graphs")
AGENT_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")

_connections: dict[tuple[Path, str], kuzu.Connection] = {}


def _validate_agent_type(agent_type: str) -> None:
    if not AGENT_TYPE_PATTERN.fullmatch(agent_type):
        raise ValueError(
            "agent_type must be a single path segment using letters, numbers, "
            "underscores, or hyphens"
        )


def get_graphs_dir() -> Path:
    return Path(os.getenv("KUZU_GRAPHS_DIR", str(DEFAULT_KUZU_GRAPHS_DIR)))


def get_db_path(agent_type: str) -> Path:
    _validate_agent_type(agent_type)
    return get_graphs_dir() / agent_type / "domain.kuzu"


def get_db(agent_type: str) -> kuzu.Database:
    db_path = get_db_path(agent_type)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return kuzu.Database(str(db_path))


def get_connection(agent_type: str) -> kuzu.Connection:
    db_path = get_db_path(agent_type)
    key = (db_path.parent.parent.resolve(), agent_type)
    if key not in _connections:
        _connections[key] = kuzu.Connection(get_db(agent_type))
    return _connections[key]


def execute(agent_type: str, query: str, params: dict[str, Any] | None = None):
    conn = get_connection(agent_type)
    if params:
        return conn.execute(query, params)
    return conn.execute(query)
