from __future__ import annotations

import pathlib
import re

import pytest

from src.core.enums import Phase
from src.core.redis_keys import (
    agent_cert_ready_key,
    agent_learning_rate_key,
    agent_phase_key,
    agent_proposal_ready_key,
    agent_readiness_score_key,
    certified_kb_cache_key,
    circuit_state_key,
    circuit_stats_key,
    graph_cache_key,
    workflow_context_stream_key,
)


def test_agent_key_patterns() -> None:
    assert agent_phase_key("burger-order") == "agent:burger-order:phase"
    assert agent_learning_rate_key("burger-order") == "agent:burger-order:learning_rate"
    assert (
        agent_readiness_score_key("burger-order")
        == "agent:burger-order:readiness_score"
    )
    assert agent_proposal_ready_key("burger-order") == "agent:burger-order:proposal_ready"
    assert agent_cert_ready_key("burger-order") == "agent:burger-order:cert_ready"


def test_circuit_key_patterns() -> None:
    assert circuit_state_key("burger-order") == "circuit:burger-order:state"
    assert circuit_stats_key("burger-order") == "circuit:burger-order:stats"


def test_workflow_stream_key() -> None:
    assert workflow_context_stream_key("wf-abc123") == (
        "stream:workflow:wf-abc123:context"
    )


def test_cache_key_patterns() -> None:
    assert graph_cache_key("burger-order", "order-agent") == (
        "graph:burger-order:order-agent"
    )
    assert certified_kb_cache_key("burger-order", "a1b2c3") == (
        "certified_kb:burger-order:a1b2c3"
    )


@pytest.fixture
def redis_client(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from src.infra.redis_client import close_client, get_client

    close_client()
    client = get_client()
    yield client
    client.flushdb()
    close_client()


def test_get_agent_state_defaults(redis_client) -> None:
    from src.infra.redis_client import get_agent_state

    state = get_agent_state("nonexistent-agent")
    assert state == {
        "phase": "apprentice",
        "learning_rate": 1.0,
        "readiness_score": 0.0,
        "proposal_ready": False,
        "cert_ready": False,
    }


def test_get_agent_state_after_init(redis_client) -> None:
    from src.infra.redis_client import get_agent_state, redis_set

    redis_set(agent_phase_key("burger-order"), "apprentice")
    redis_set(agent_learning_rate_key("burger-order"), "1.0")
    redis_set(agent_readiness_score_key("burger-order"), "0.0")

    state = get_agent_state("burger-order")
    assert state["phase"] == "apprentice"
    assert state["learning_rate"] == 1.0
    assert state["readiness_score"] == 0.0


def test_set_agent_phase_atomic(redis_client) -> None:
    from src.infra.redis_client import get_agent_state, set_agent_phase

    set_agent_phase("burger-order", Phase.JOURNEYMAN, 0.5)
    state = get_agent_state("burger-order")
    assert state["phase"] == "journeyman"
    assert state["learning_rate"] == 0.5


def test_workflow_stream_hset_hget_xadd_xread(redis_client) -> None:
    from src.core.redis_keys import circuit_stats_key
    from src.infra.redis_client import (
        redis_hget,
        redis_hgetall,
        redis_hset,
        stream_add,
        stream_read,
    )

    stats_key = circuit_stats_key("burger-order")
    stream_key = workflow_context_stream_key("wf-abc123")

    redis_hset(stats_key, {"error_rate": "0.1", "consecutive_failures": "2"})
    assert redis_hgetall(stats_key)["error_rate"] == "0.1"
    assert redis_hget(stats_key, "consecutive_failures") == "2"

    message_id = stream_add(stream_key, {"event": "task_started", "task_id": "t1"})
    messages = stream_read(stream_key, last_id="0", count=1)

    assert len(messages) == 1
    returned_stream, returned_messages = messages[0]
    assert returned_stream == stream_key
    assert returned_messages == [
        (message_id, {"event": "task_started", "task_id": "t1"})
    ]


def test_no_raw_fstring_redis_keys_outside_allowed_files() -> None:
    pattern = re.compile(r'f["\'](agent|circuit|stream|graph|certified_kb):')
    allowed_files = {"redis_keys.py", "redis_client.py"}

    violations = []
    for path in pathlib.Path("src").rglob("*.py"):
        if path.name in allowed_files:
            continue
        if pattern.search(path.read_text()):
            violations.append(str(path))

    assert violations == []
