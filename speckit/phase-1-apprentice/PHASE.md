# Phase 1 — Apprentice

## Goal
An agent type can be created from a domain seed, run Socratic Q&A sessions with a domain expert,
build its task and coordination knowledge graphs, simulate a workflow team, and reach the Cert 1 gate
where the expert approves graduation to Journeyman.

## Dependencies
Phase 0 checklist must be fully green.

## Exit Condition
All items in the checklist below are passing AND at least one agent type has been approved at Cert 1 gate.

## Tasks
| ID | Task | File |
|---|---|---|
| T1.1 | Agent type registry | T1.1-agent-type-registry.md |
| T1.2 | Knowledge gap detector | T1.2-gap-detector.md |
| T1.3 | Socratic question generator | T1.3-question-generator.md |
| T1.4 | Answer processor | T1.4-answer-processor.md |
| T1.5 | Graph writer | T1.5-graph-writer.md |
| T1.6 | Readiness scorer | T1.6-readiness-scorer.md |
| T1.7 | LLM team proposal | T1.7-llm-team-proposal.md |
| T1.8 | Proposal review API | T1.8-proposal-review-api.md |
| T1.9 | Simulation session + run recorder | T1.9-simulation-session.md |
| T1.10 | Contract validator | T1.10-contract-validator.md |
| T1.11 | Cert 1 gate | T1.11-cert1-gate.md |

## Data Flow
```
Domain seed (T1.1)
  → Gap detector (T1.2) — finds what's missing in the graph
  → Question generator (T1.3) — asks expert one focused question
  → Answer processor (T1.4) — parses + validates expert answer
  → Graph writer (T1.5) — writes to Kuzu
  → Readiness scorer (T1.6) — re-scores after each write
  [loop until proposal_ready=true]
  → LLM team proposal (T1.7) — clusters graph into candidate agents
  → Proposal review (T1.8) — expert approves/edits/rejects
  → Simulation sessions (T1.9) — expert role-plays other agents
      → Contract validator (T1.10) — catches violations mid-sim
  [loop until cert_ready=true]
  → Cert 1 gate (T1.11) — expert clicks approve → phase=journeyman
```

## Checklist
```
[ ] T1.1  — POST /agent-types creates agent, Kuzu graph initialized with seed topic nodes
[ ] T1.2  — Gap detector returns ranked gaps; orphans, low-confidence, and unexplored all detected
[ ] T1.3  — Question generator never repeats a covered concept; stays within task_boundary
[ ] T1.4  — Contradictory answer returns conflict status; ambiguous returns follow_up
[ ] T1.5  — Graph write confirms in Kuzu; readiness score updates in Redis after each write
[ ] T1.6  — Score formula correct; proposal_ready=true at 0.55; cert_ready=true at 0.80
[ ] T1.7  — Multi-cluster domain produces multi-agent proposal with contracts and rationale
[ ] T1.8  — All three paths (approve/edit/reject) tested; rejection triggers re-proposal
[ ] T1.9  — Turn round-trip < 2s; coord namespace edges appear in Kuzu after session close
[ ] T1.10 — Field-level violations detected; both resolution paths (clarify/edge-case) tested
[ ] T1.11 — Approve only succeeds when cert_ready=true; phase updated in Redis; cert event written
```

## Test Command
```bash
pytest tests/phase_1/ -v
```
