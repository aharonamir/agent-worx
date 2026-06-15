from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.enums import (
    CertDecision,
    CertGate,
    CircuitState,
    DeltaStatus,
    FlagCategory,
    ObservationType,
)


class DeltaEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    agent_instance_id: str
    status: DeltaStatus = DeltaStatus.QUARANTINE
    observation_type: ObservationType
    edge_data: dict[str, Any]
    triggered_by_task_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class CertEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    gate: CertGate
    decision: CertDecision
    expert_id: str
    readiness_score: float
    notes: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ShadowReview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    agent_type: str
    instance_id: str
    task_input: dict[str, Any]
    task_output: dict[str, Any]
    action_log: list[dict[str, Any]]
    confidence_score: float
    status: Literal["pending", "approved", "flagged", "escalated"] = "pending"
    flag_category: FlagCategory | None = None
    flag_description: str | None = None
    reviewed_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: datetime | None = None


class EscalationEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    agent_type: str
    instance_id: str
    reason: Literal[
        "out_of_scope",
        "action_prohibited",
        "max_iterations",
        "worker_failure",
    ]
    task_summary: str
    scope_similarity_score: float | None = None
    routed_to: Literal["orchestrator", "human_queue"]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CircuitBreakerStatus(BaseModel):
    agent_type: str
    state: CircuitState
    error_rate: float = Field(..., ge=0.0, le=1.0)
    consecutive_failures: int
    last_state_change: datetime
    next_probe_at: datetime | None = None
