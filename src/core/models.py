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
    Phase,
    TopologyType,
)


class AgentTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: str = Field(..., min_length=10, max_length=500)
    task_boundary: str = Field(..., min_length=10, max_length=1000)
    topic_list: list[str] = Field(..., min_length=1, max_length=50)
    topology_type: TopologyType
    workflow_participants: list[str] = Field(default_factory=list)


class AgentTypeResponse(BaseModel):
    agent_type_id: str
    name: str
    goal: str
    task_boundary: str
    topic_list: list[str]
    topology_type: TopologyType
    workflow_participants: list[str]
    phase: Phase
    learning_rate: float
    readiness_score: float
    graph_initialized: bool
    created_at: datetime


class KnowledgeGap(BaseModel):
    concept_id: str
    concept_label: str
    gap_type: Literal["orphan", "low_confidence", "unexplored"]
    severity: float = Field(..., ge=0.0, le=1.0)
    breadth: int = Field(..., ge=0)
    priority_score: float = Field(..., ge=0.0)
    namespace: Literal["task", "coordination"]


class GapDetectorResult(BaseModel):
    agent_type_id: str
    gaps: list[KnowledgeGap]
    total_nodes: int
    orphan_count: int
    low_confidence_count: int
    unexplored_count: int


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
