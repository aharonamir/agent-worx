from __future__ import annotations

"""Centralized Redis key construction for all framework key patterns."""


def agent_phase_key(agent_type: str) -> str:
    return f"agent:{agent_type}:phase"


def agent_learning_rate_key(agent_type: str) -> str:
    return f"agent:{agent_type}:learning_rate"


def agent_readiness_score_key(agent_type: str) -> str:
    return f"agent:{agent_type}:readiness_score"


def agent_proposal_ready_key(agent_type: str) -> str:
    return f"agent:{agent_type}:proposal_ready"


def agent_cert_ready_key(agent_type: str) -> str:
    return f"agent:{agent_type}:cert_ready"


def circuit_state_key(agent_type: str) -> str:
    return f"circuit:{agent_type}:state"


def circuit_stats_key(agent_type: str) -> str:
    return f"circuit:{agent_type}:stats"


def workflow_context_stream_key(workflow_id: str) -> str:
    return f"stream:workflow:{workflow_id}:context"


def graph_cache_key(agent_type: str, role: str) -> str:
    return f"graph:{agent_type}:{role}"


def certified_kb_cache_key(agent_type: str, query_hash: str) -> str:
    return f"certified_kb:{agent_type}:{query_hash}"
