# Agent Worx — Spec-Kit

## Purpose

This repository is the implementation specification for the Agent Worx.
It is structured for consumption by AI coding agents (Claude, Codex, etc.) and human engineers equally.

**Read this file first. Then read the phase file. Then read individual task cards in order.**

---

## What You Are Building

A production-grade multi-agent platform where AI agents move through three lifecycle phases:

```
Apprentice  ──[Cert 1: human gate]──►  Journeyman  ──[Cert 2: human gate]──►  Work
(learning)                              (supervised)                           (production)
```

Each phase has decreasing learning plasticity. Agents become less malleable as they advance.
Human expert approval is required at every phase transition. Automation supports but never replaces this.

---

## Repo Structure

```
speckit/
├── README.md                          ← YOU ARE HERE — read first
├── shared/
│   ├── DEPENDENCIES.md                ← All pinned versions
│   ├── PROJECT_STRUCTURE.md           ← Full file/folder layout to generate
│   ├── DATA_SCHEMAS.md                ← All Pydantic models and DB schemas
│   ├── API_CONTRACTS.md               ← All endpoint definitions with types
│   └── INVARIANTS.md                  ← Safety rules that must never be violated
├── phase-0-foundations/
│   ├── PHASE.md                       ← Phase goal, exit condition, checklist
│   ├── T0.1-temporal.md
│   ├── T0.2-postgres.md
│   ├── T0.3-redis.md
│   ├── T0.4-qdrant.md
│   ├── T0.5-kuzu.md
│   ├── T0.6-schema-kuzu.md
│   ├── T0.7-schema-postgres.md
│   └── T0.8-schema-redis.md
├── phase-1-apprentice/
│   ├── PHASE.md
│   ├── T1.1-agent-type-registry.md
│   ├── T1.2-gap-detector.md
│   ├── T1.3-question-generator.md
│   ├── T1.4-answer-processor.md
│   ├── T1.5-graph-writer.md
│   ├── T1.6-readiness-scorer.md
│   ├── T1.7-llm-team-proposal.md
│   ├── T1.8-proposal-review-api.md
│   ├── T1.9-simulation-session.md
│   ├── T1.10-contract-validator.md
│   └── T1.11-cert1-gate.md
├── phase-2-journeyman/
│   ├── PHASE.md
│   ├── T2.1-langgraph-state-graph.md
│   ├── T2.2-temporal-activity-wrapper.md
│   ├── T2.3-certified-kb-retrieval.md
│   ├── T2.4-domain-graph-traversal.md
│   ├── T2.5-shadow-review-queue.md
│   ├── T2.6-delta-observation-capture.md
│   ├── T2.7-delta-promotion-pipeline.md
│   └── T2.8-cert2-gate.md
└── phase-3-work/
    ├── PHASE.md
    ├── T3.1-action-manifest-enforcement.md
    ├── T3.2-out-of-scope-escalation.md
    ├── T3.3-temporal-work-config.md
    ├── T3.4-behavioral-baseline.md
    ├── T3.5-drift-detection.md
    ├── T3.6-circuit-breaker.md
    ├── T3.7-low-plasticity-delta.md
    └── T3.8-recert-triggers.md
```

---

## Agent Instructions

If you are an AI coding agent reading this:

1. **Load `shared/DEPENDENCIES.md` before writing any code.** All versions are pinned. Do not install latest.
2. **Load `shared/PROJECT_STRUCTURE.md` before creating any file.** Every file has a designated path. Do not invent paths.
3. **Load `shared/DATA_SCHEMAS.md` before implementing any function that reads or writes data.** All models are defined there.
4. **Load `shared/API_CONTRACTS.md` before implementing any endpoint.** All request/response types are defined there.
5. **Load `shared/INVARIANTS.md` and keep it in context for the entire session.** These are hard safety rules. Never violate them.
6. **Work one task card at a time.** Complete the task, run its test, confirm the acceptance criterion passes, then move on.
7. **Do not proceed past a phase CHECKLIST item that is failing.** Each item maps to a safety invariant or a dependency for the next phase.
8. **Never write directly to the Qdrant certified KB or Kuzu graph from a work-phase agent.** All writes from work-phase agents go to the delta quarantine store (Postgres `delta_entries` table) only.

---

## Build Order

```
Phase 0 (all tasks) → validate phase checklist → Phase 1 (all tasks) → validate → Phase 2 → validate → Phase 3
```

Do not start Phase 1 until Phase 0 checklist is fully green.
Do not start Phase 2 until Phase 1 checklist is fully green.
Do not start Phase 3 until Phase 2 checklist is fully green.

---

## Key Contacts / Decisions Already Made

| Decision | Choice | Rationale |
|---|---|---|
| Workflow runtime | LangGraph 1.0 + Temporal | LangGraph for agent logic; Temporal for durability |
| Graph DB | Kuzu (Vela fork) | 374× faster than Neo4j on path queries; zero infra |
| Vector DB | Qdrant | Rust-based; filtered HNSW preserves recall under metadata filters |
| KV + messaging | Redis 7.2+ | Sub-ms reads; Redis Streams for context bus |
| Checkpointer | AsyncPostgresSaver | SQLite has a write-lock ceiling of ~100 concurrent agents |
| Cert gates | Human-only approval | No automation can trigger phase graduation |
