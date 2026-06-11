# Phase 2 — Journeyman

## Goal
Certified agents execute real tasks under expert supervision.
The expert reviews outputs asynchronously in shadow mode.
Runtime learnings flow into the delta buffer (never directly to the certified KB).
The expert approves Cert 2 when satisfied with sustained production performance.

## Dependencies
Phase 1 checklist must be fully green.
At least one agent type must have passed Cert 1 gate.

## Exit Condition
All items in the checklist below are passing AND at least one agent type has been approved at Cert 2 gate.

## Tasks
| ID | Task | File |
|---|---|---|
| T2.1 | LangGraph StateGraph | T2.1-langgraph-state-graph.md |
| T2.2 | Temporal activity wrapper | T2.2-temporal-activity-wrapper.md |
| T2.3 | Certified KB retrieval | T2.3-certified-kb-retrieval.md |
| T2.4 | Domain graph traversal | T2.4-domain-graph-traversal.md |
| T2.5 | Shadow review queue | T2.5-shadow-review-queue.md |
| T2.6 | Delta observation capture | T2.6-delta-observation-capture.md |
| T2.7 | Delta promotion pipeline | T2.7-delta-promotion-pipeline.md |
| T2.8 | Cert 2 gate | T2.8-cert2-gate.md |

## Data Flow
```
Task arrives via Temporal
  → Circuit breaker check (Phase 3 component, but check state from Redis)
  → LangGraph graph invoke (T2.1)
      → Retrieve from certified KB (T2.3) + domain graph (T2.4)
      → Execute task
      → Validate output
      → Route: complete | escalate | handoff | continue
  → Task result written to shadow_reviews table (T2.5)
  → Delta observations written to delta_entries table (T2.6)
  [background] Delta promotion pipeline (T2.7) reviews quarantine entries
  [human] Expert reviews shadow queue, flags issues
  [human] Expert approves Cert 2 when satisfied (T2.8)
```

## Checklist
```
[ ] T2.1  — LangGraph graph compiles; AsyncPostgresSaver confirmed; max_iterations guard in all loops
[ ] T2.2  — Temporal activity wraps LangGraph; retry policy set; crash recovery tested
[ ] T2.3  — Qdrant retrieval p95 < 100ms; Redis cache layer active; metadata filters working
[ ] T2.4  — Kuzu handoff traversal returns correct agents; Redis cache invalidated on graph write
[ ] T2.5  — Every completed task appears in shadow_reviews; all 3 expert actions (approve/flag/escalate) tested
[ ] T2.6  — Delta observations written to Postgres only; confirmed NOT in Kuzu or Qdrant
[ ] T2.7  — Auto-promote path (confidence ≥ 0.85) and human-review path both tested end-to-end
[ ] T2.8  — cert_ready_signal is advisory; expert can approve regardless; phase + learning_rate updated
```

## Test Command
```bash
pytest tests/phase_2/ -v
```

## Critical Reminders for This Phase
- `AsyncPostgresSaver` only — never `SqliteSaver` (Invariant I4)
- Every supervisor loop needs `max_iterations` guard (Invariant I5)
- Delta observations go to Postgres `delta_entries` table only (Invariant I1 applies here too)
- Cert 2 is human-only approval — no automation may trigger it (Invariant I2)
