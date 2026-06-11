# Data Schemas

> These are the canonical type definitions. Every function that reads or writes data must use these models.
> All models use Pydantic v2. File location: `src/core/models.py`

---

## Enums

```python
# src/core/enums.py

from enum import Enum

class Phase(str, Enum):
    APPRENTICE = "apprentice"
    JOURNEYMAN = "journeyman"
    WORK = "work"

class TopologyType(str, Enum):
    PIPELINE = "pipeline"
    ORCHESTRATED = "orchestrated"
    PEER = "peer"

class ObservationType(str, Enum):
    VIOLATION = "violation"
    LEARNED = "learned"
    AMBIGUOUS = "ambiguous"

class DeltaStatus(str, Enum):
    QUARANTINE = "quarantine"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"

class CompositionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ARCHIVED = "archived"

class CertGate(str, Enum):
    CERT1 = "cert1"
    CERT2 = "cert2"

class CertDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class FlagCategory(str, Enum):
    WRONG_OUTPUT = "wrong_output"
    WRONG_HANDOFF = "wrong_handoff"
    MISSED_CONSTRAINT = "missed_constraint"
```

---

## Core Domain Models

```python
# src/core/models.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator
from .enums import *


# ── Agent Type ──────────────────────────────────────────────

class AgentTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: str = Field(..., min_length=10, max_length=500)
    task_boundary: str = Field(..., min_length=10, max_length=1000,
        description="Hard boundary of what this agent is allowed to know and do")
    topic_list: list[str] = Field(..., min_length=1, max_length=50,
        description="Seed topics that become root nodes in the domain graph")
    topology_type: TopologyType
    workflow_participants: list[str] = Field(default_factory=list,
        description="Names of other agent types in the workflow (empty for single-agent)")

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


# ── Knowledge Gap ────────────────────────────────────────────

class KnowledgeGap(BaseModel):
    concept_id: str
    concept_label: str
    gap_type: Literal["orphan", "low_confidence", "unexplored"]
    severity: float = Field(..., ge=0.0, le=1.0)
    breadth: int = Field(..., ge=0,
        description="Count of dependent concepts blocked by this gap")
    priority_score: float = Field(..., ge=0.0,
        description="severity × breadth — higher is more urgent")
    namespace: Literal["task", "coordination"]

class GapDetectorResult(BaseModel):
    agent_type_id: str
    gaps: list[KnowledgeGap]
    total_nodes: int
    orphan_count: int
    low_confidence_count: int
    unexplored_count: int


# ── Q&A Session ──────────────────────────────────────────────

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
    existing_confidence: float
    conflict_description: str

class AnswerProcessorResult(BaseModel):
    status: Literal["write", "conflict", "follow_up"]
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    conflict: ConflictDetail | None = None
    follow_up_question: str | None = None


# ── Readiness Score ──────────────────────────────────────────

class ReadinessScore(BaseModel):
    agent_type_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    node_coverage: float = Field(..., ge=0.0, le=1.0)
    edge_density: float = Field(..., ge=0.0, le=1.0)
    confidence_mean: float = Field(..., ge=0.0, le=1.0)
    proposal_ready: bool
    cert_ready: bool
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# ── Team Proposal ────────────────────────────────────────────

class AgentContract(BaseModel):
    agent_name: str
    input_schema: dict[str, str] = Field(...,
        description="Field name → type string, e.g. {'order_items': 'list[str]'}")
    output_schema: dict[str, str]
    prohibited_fields: list[str] = Field(default_factory=list)

class HandoffContract(BaseModel):
    from_agent: str
    to_agent: str
    condition: str = Field(..., description="Human-readable condition for this handoff")
    validates: list[str] = Field(...,
        description="Fields that must be asserted before handing off")
    rationale: str

class ProposalArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type_id: str
    version: int = 1
    topology: TopologyType
    agents: list[AgentContract]
    contracts: list[HandoffContract]
    rationale_per_agent: dict[str, str] = Field(...,
        description="agent_name → rationale for why this agent exists")
    rationale_per_contract: dict[str, str] = Field(...,
        description="'from_agent→to_agent' → rationale")
    status: CompositionStatus = CompositionStatus.PROPOSED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expert_signature: str | None = None
    signed_at: datetime | None = None


# ── Simulation ───────────────────────────────────────────────

class SimulationTurnInput(BaseModel):
    role: str = Field(..., description="Agent name the expert is playing")
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None


# ── LangGraph State ──────────────────────────────────────────

class AgentState(BaseModel):
    """LangGraph state schema. All fields required for routing must use Literal types."""
    agent_type: str
    instance_id: str
    phase: Phase
    task_id: str
    task_input: dict[str, Any]
    task_output: dict[str, Any] = Field(default_factory=dict)
    escalation_required: bool = False
    escalation_reason: str | None = None
    action_log: list[dict[str, Any]] = Field(default_factory=list)
    delta_observations: list[dict[str, Any]] = Field(default_factory=list)
    iterations: int = 0
    max_iterations: int = 10
    routing_decision: Literal["continue", "escalate", "complete", "handoff"] = "continue"


# ── Delta Quarantine ─────────────────────────────────────────

class DeltaEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    agent_instance_id: str
    status: DeltaStatus = DeltaStatus.QUARANTINE
    observation_type: ObservationType
    edge_data: dict[str, Any] = Field(...,
        description="Structured knowledge to potentially promote")
    triggered_by_task_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None


# ── Cert Events ──────────────────────────────────────────────

class CertApproveRequest(BaseModel):
    expert_id: str = Field(..., min_length=1)
    notes: str = Field(default="", max_length=2000)

class CertRejectRequest(BaseModel):
    expert_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=10, max_length=2000)

class CertEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    gate: CertGate
    decision: CertDecision
    expert_id: str
    readiness_score: float
    notes: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Shadow Review ─────────────────────────────────────────────

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


# ── Escalation ───────────────────────────────────────────────

class EscalationEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    agent_type: str
    instance_id: str
    reason: Literal["out_of_scope", "action_prohibited", "max_iterations", "worker_failure"]
    task_summary: str
    scope_similarity_score: float | None = None
    routed_to: Literal["orchestrator", "human_queue"]
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Circuit Breaker ───────────────────────────────────────────

class CircuitBreakerStatus(BaseModel):
    agent_type: str
    state: CircuitState
    error_rate: float = Field(..., ge=0.0, le=1.0)
    consecutive_failures: int
    last_state_change: datetime
    next_probe_at: datetime | None = None
```

---

## Postgres Table DDL

```sql
-- Run via Alembic migration 001_initial_schema.py

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE delta_entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type      VARCHAR(100) NOT NULL,
    agent_instance_id VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'quarantine',
    observation_type VARCHAR(20) NOT NULL,
    edge_data       JSONB NOT NULL,
    triggered_by_task_id VARCHAR(100) NOT NULL,
    confidence      FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMP,
    reviewed_by     VARCHAR(100),
    rejection_reason TEXT
);

CREATE INDEX idx_delta_agent_type ON delta_entries(agent_type);
CREATE INDEX idx_delta_status ON delta_entries(status);

CREATE TABLE team_compositions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type      VARCHAR(100) NOT NULL,
    version         INT NOT NULL,
    topology        VARCHAR(20) NOT NULL,
    agent_list      JSONB NOT NULL,
    contracts       JSONB NOT NULL,
    rationale       JSONB,
    expert_signature VARCHAR(200),
    signed_at       TIMESTAMP,
    status          VARCHAR(20) NOT NULL DEFAULT 'proposed',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(agent_type, version)
);

CREATE TABLE cert_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type      VARCHAR(100) NOT NULL,
    gate            VARCHAR(10) NOT NULL,
    decision        VARCHAR(10) NOT NULL,
    expert_id       VARCHAR(100) NOT NULL,
    readiness_score FLOAT NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cert_agent_type ON cert_events(agent_type);

CREATE TABLE shadow_reviews (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         VARCHAR(100) NOT NULL,
    agent_type      VARCHAR(100) NOT NULL,
    instance_id     VARCHAR(100) NOT NULL,
    task_input      JSONB NOT NULL,
    task_output     JSONB NOT NULL,
    action_log      JSONB NOT NULL,
    confidence_score FLOAT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    flag_category   VARCHAR(30),
    flag_description TEXT,
    reviewed_by     VARCHAR(100),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMP
);

CREATE INDEX idx_shadow_agent_type_status ON shadow_reviews(agent_type, status);

CREATE TABLE escalation_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         VARCHAR(100) NOT NULL,
    agent_type      VARCHAR(100) NOT NULL,
    instance_id     VARCHAR(100) NOT NULL,
    reason          VARCHAR(30) NOT NULL,
    task_summary    TEXT NOT NULL,
    scope_similarity_score FLOAT,
    routed_to       VARCHAR(20) NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```
