from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.enums import (
    CertDecision,
    CertGate,
    CircuitState,
    CompositionStatus,
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


class QuestionGeneratorResult(BaseModel):
    agent_type_id: str
    question: str
    targeting_gap: KnowledgeGap
    is_followup: bool = False
    parent_question_id: str | None = None


class AnswerProcessorInput(BaseModel):
    agent_type_id: str
    question: str
    answer: str
    gap_context: KnowledgeGap


class ExtractedEntity(BaseModel):
    label: str
    entity_type: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractedRelation(BaseModel):
    source: str
    target: str
    relation_type: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ConflictDetail(BaseModel):
    existing_source: str
    existing_target: str
    existing_relation: str
    existing_confidence: float = Field(..., ge=0.0, le=1.0)
    conflict_description: str


class AnswerProcessorResult(BaseModel):
    status: Literal["write", "conflict", "follow_up"]
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    conflict: ConflictDetail | None = None
    follow_up_question: str | None = None


class ReadinessScore(BaseModel):
    agent_type_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    node_coverage: float = Field(..., ge=0.0, le=1.0)
    edge_density: float = Field(..., ge=0.0, le=1.0)
    confidence_mean: float = Field(..., ge=0.0, le=1.0)
    proposal_ready: bool
    cert_ready: bool
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentContract(BaseModel):
    agent_name: str
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    prohibited_fields: list[str] = Field(default_factory=list)


class HandoffContract(BaseModel):
    from_agent: str
    to_agent: str
    condition: str
    validates: list[str]
    rationale: str


class ProposalArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type_id: str
    version: int = 1
    topology: TopologyType
    agents: list[AgentContract]
    contracts: list[HandoffContract]
    rationale_per_agent: dict[str, str]
    rationale_per_contract: dict[str, str]
    status: CompositionStatus = CompositionStatus.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expert_signature: str | None = None
    signed_at: datetime | None = None


class SimulationTurnInput(BaseModel):
    role: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=4000)


class SimulationObservation(BaseModel):
    type: ObservationType
    description: str
    turn_index: int
    roles_involved: list[str]
    coord_edge_written: bool = False


class ContractViolation(BaseModel):
    field: str
    reason: str
    from_agent: str
    to_agent: str
    resolution: Literal["pending", "clarify_contract", "mark_edge_case"] = "pending"


class SimulationTurnResult(BaseModel):
    turn_index: int
    role: str
    message: str
    violations: list[ContractViolation]
    observations: list[SimulationObservation]
    paused_for_violation: bool


class SimulationSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type_id: str
    composition_version: int
    current_role: str | None = None
    turn_history: list[SimulationTurnResult] = Field(default_factory=list)
    observations: list[SimulationObservation] = Field(default_factory=list)
    coord_namespace_writes: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["active", "closed"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None


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
