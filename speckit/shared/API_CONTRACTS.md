# API Contracts

> All endpoints use FastAPI. Request and response types reference models in `DATA_SCHEMAS.md`.
> Base URL: `http://localhost:8000/api/v1`

---

## Agent Types

### POST /agent-types
Create a new agent type and initialize its domain graph.

```python
# Request:  AgentTypeCreate
# Response: AgentTypeResponse (201 Created)
# Errors:
#   400 — topic_list is empty
#   409 — agent type with this name already exists

POST /api/v1/agent-types
Content-Type: application/json

{
  "name": "burger-order",
  "goal": "Take and process burger orders end-to-end",
  "task_boundary": "Burger ordering only. Does not handle payment processing, kitchen operations, or delivery.",
  "topic_list": ["menu items", "order flow", "allergens", "modifiers", "upselling rules"],
  "topology_type": "orchestrated",
  "workflow_participants": ["kitchen-agent", "payment-agent"]
}
```

### GET /agent-types/{agent_type_id}
```python
# Response: AgentTypeResponse
# Errors: 404
```

### GET /agent-types/{agent_type_id}/readiness
```python
# Response: ReadinessScore
# Errors: 404
```

---

## Q&A Session (Apprentice)

### POST /agent-types/{agent_type_id}/qa/question
Get the next question the agent wants to ask the expert.

```python
# Request:  (no body)
# Response: QuestionGeneratorResult
# Errors:
#   404 — agent type not found
#   409 — agent not in apprentice phase

POST /api/v1/agent-types/{agent_type_id}/qa/question
```

### POST /agent-types/{agent_type_id}/qa/answer
Submit the expert's answer to the last question.

```python
# Request:
{
  "question": "string — the question being answered",
  "answer": "string — expert's natural language answer",
  "gap_context": KnowledgeGap  # returned with the question
}

# Response:
{
  "status": "write" | "conflict" | "follow_up",
  "processor_result": AnswerProcessorResult,
  "readiness_score": ReadinessScore  # updated score after write (if status=write)
}

# Errors:
#   400 — answer is empty
#   404 — agent type not found
#   409 — agent not in apprentice phase
```

---

## Team Proposals

### GET /agent-types/{agent_type_id}/proposal
```python
# Response: ProposalArtifact | null
# Returns null if readiness score has not crossed proposal threshold yet
```

### PUT /agent-types/{agent_type_id}/proposal
```python
# Request:
{
  "action": "approve" | "edit" | "reject",
  "edits": ProposalArtifact | null,   # required if action=edit
  "rejection_reason": "string | null"  # required if action=reject
}

# Response:
{
  "composition_id": "uuid",
  "status": "approved" | "re_proposed",
  "new_proposal": ProposalArtifact | null  # present if action=reject (re-proposed)
}
```

---

## Simulation Sessions

### POST /simulations
```python
# Request:
{
  "agent_type_id": "string",
  "composition_version": 1
}

# Response: SimulationSession (201 Created)
```

### GET /simulations/{session_id}
```python
# Response: SimulationSession
```

### POST /simulations/{session_id}/turn
```python
# Request: SimulationTurnInput
{
  "role": "kitchen-agent",
  "message": "Received order. Prep ticket created. Est. 12 min."
}

# Response: SimulationTurnResult
# Note: if paused_for_violation=true, client must POST to
#       /simulations/{session_id}/violations/{index}/resolve before next turn
```

### POST /simulations/{session_id}/violations/{violation_index}/resolve
```python
# Request:
{
  "resolution": "clarify_contract" | "mark_edge_case",
  "clarification": "string | null"  # required if resolution=clarify_contract
}

# Response: { "resolved": true, "coord_edge_written": bool }
```

### POST /simulations/{session_id}/close
```python
# Request: (no body)
# Response:
{
  "session_id": "string",
  "coord_edges_written": int,
  "observations_captured": int,
  "violations_total": int,
  "violations_unresolved": int
}
```

---

## Certification Gates

### GET /agent-types/{agent_type_id}/cert1-status
```python
# Response:
{
  "readiness_score": float,
  "simulation_runs_completed": int,
  "violations_unresolved": int,
  "cert_ready": bool  # advisory signal only — expert must still approve manually
}
```

### POST /agent-types/{agent_type_id}/cert1/approve
```python
# Request: CertApproveRequest
# Response:
{
  "cert_event_id": "uuid",
  "previous_phase": "apprentice",
  "new_phase": "journeyman",
  "new_learning_rate": 0.5
}
# Errors:
#   400 — cert_ready is false (include current readiness_score in error body)
#   409 — agent not in apprentice phase
```

### POST /agent-types/{agent_type_id}/cert1/reject
```python
# Request: CertRejectRequest
# Response: { "cert_event_id": "uuid", "phase": "apprentice" }
```

### GET /agent-types/{agent_type_id}/cert2-status
```python
# Response:
{
  "tasks_completed": int,
  "tasks_flagged": int,
  "flag_rate": float,
  "avg_confidence": float,
  "shadow_reviews_pending": int,
  "cert_ready_signal": bool  # advisory only — human must approve manually regardless
}
```

### POST /agent-types/{agent_type_id}/cert2/approve
```python
# Request: CertApproveRequest
# Response:
{
  "cert_event_id": "uuid",
  "previous_phase": "journeyman",
  "new_phase": "work",
  "new_learning_rate": 0.1
}
# Note: cert2 approve succeeds REGARDLESS of cert_ready_signal value.
#       It is the expert's decision, not a system gate.
# Errors:
#   409 — agent not in journeyman phase
```

---

## Shadow Reviews

### GET /shadow-reviews
```python
# Query params: agent_type (required), status (optional, default=pending)
# Response: list[ShadowReview]
```

### PUT /shadow-reviews/{review_id}
```python
# Request:
{
  "action": "approve" | "flag" | "escalate",
  "expert_id": "string",
  "flag_category": FlagCategory | null,   # required if action=flag
  "flag_description": "string | null"     # required if action=flag
}
# Response: ShadowReview (updated)
```

---

## Circuit Breaker

### GET /agent-types/{agent_type_id}/circuit-breaker
```python
# Response: CircuitBreakerStatus
```

---

## Health

### GET /health
```python
# Response: { "status": "ok" }  (200) or { "status": "degraded", "checks": {...} } (503)
```

### GET /ready
```python
# Response: { "ready": true } (200) or { "ready": false, "reason": "..." } (503)
# Checks: Postgres reachable, Redis reachable, Qdrant reachable, Temporal reachable
```
