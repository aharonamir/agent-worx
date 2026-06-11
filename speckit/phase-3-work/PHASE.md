# Phase 3 — Work

## Goal
Work-phase agents run at full production scale with low learning rate (0.1).
Out-of-scope tasks are refused and escalated — never attempted.
The drift monitor watches for behavioral divergence from the certified baseline.
The circuit breaker isolates failing agent types before failures cascade.

## Dependencies
Phase 2 checklist must be fully green.
At least one agent type must have passed Cert 2 gate.

## Exit Condition
All items in the checklist below are passing.
At least one agent type running successfully in work phase for 48+ hours without circuit breaker firing.

## Tasks
| ID | Task | File |
|---|---|---|
| T3.1 | Action manifest enforcement | T3.1-action-manifest-enforcement.md |
| T3.2 | Out-of-scope escalation | T3.2-out-of-scope-escalation.md |
| T3.3 | Temporal work-phase config | T3.3-temporal-work-config.md |
| T3.4 | Behavioral baseline recorder | T3.4-behavioral-baseline.md |
| T3.5 | Drift detection job | T3.5-drift-detection.md |
| T3.6 | Circuit breaker | T3.6-circuit-breaker.md |
| T3.7 | Low-plasticity delta capture | T3.7-low-plasticity-delta.md |
| T3.8 | Re-certification triggers | T3.8-recert-triggers.md |

## Data Flow
```
Task arrives via Temporal
  → Circuit breaker check → if OPEN: route to human_queue immediately, no LLM call
  → Scope detector (T3.2): similarity < 0.5 → refuse + escalate
  → Action manifest check (T3.1): prohibited action → refuse + escalate
  → LangGraph graph invoke (same graph as Phase 2, work-phase config)
  → Task result written (shadow queue disabled in work phase)
  → Low-plasticity delta observations captured (T3.7) → Postgres delta_entries only
  [background hourly] Drift detection job (T3.5) diffs against baseline
  [background] Delta promotion pipeline (same as T2.7, higher threshold: 0.95)
  [event-driven] Re-cert triggers (T3.8) on team composition changes
```

## Checklist
```
[ ] T3.1  — Prohibited action refused + escalated; action NOT executed; manifest immutable post-Cert 2
[ ] T3.2  — Similarity score < 0.5 triggers refusal + escalation; score logged
[ ] T3.3  — Heartbeat timeout set; workflow execution timeout set; concurrency limits configured
[ ] T3.4  — Behavioral baseline snapshot created at Cert 2 approval; graph hash stored
[ ] T3.5  — Drift WARN fires at 0.15; CRIT fires at 0.30; Prometheus metrics published
[ ] T3.6  — CLOSED→OPEN after 5 consecutive failures; OPEN routes to human_queue; HALF_OPEN probe tested
[ ] T3.7  — Work-phase delta auto-approve threshold is 0.95 (not 0.85); < 0.95 flagged for human review
[ ] T3.8  — Structural change triggers full re-cert; contract change triggers bilateral re-cert only
```

## Test Command
```bash
pytest tests/phase_3/ -v
```

## Critical Reminders for This Phase
- Work-phase agents NEVER write to Kuzu or Qdrant directly (Invariant I1)
- Action manifest is enforced before EVERY action (Invariant I3)
- Circuit breaker must block task execution — no LLM call when OPEN (Invariant I9)
- Delta auto-approve threshold is HIGHER in work phase: 0.95 (Invariant I8)
