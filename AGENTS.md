# AGENTS.md

## Purpose

This repository implements **Agent Worx**, an agent-lifecycle system that trains a domain-specific
agent type through staged phases:

- `apprentice`: expert-guided learning and simulation
- `journeyman`: guarded execution with review
- `work`: stricter runtime safety and quarantined learning

The source of truth is the spec in [`speckit/`](./speckit).

## Read This First For Spec Work

Before implementing any spec task, load these files in order:

1. [`speckit/README.md`](./speckit/README.md)
2. [`speckit/shared/DEPENDENCIES.md`](./speckit/shared/DEPENDENCIES.md)
3. [`speckit/shared/PROJECT_STRUCTURE.md`](./speckit/shared/PROJECT_STRUCTURE.md)
4. [`speckit/shared/DATA_SCHEMAS.md`](./speckit/shared/DATA_SCHEMAS.md)
5. [`speckit/shared/API_CONTRACTS.md`](./speckit/shared/API_CONTRACTS.md)
6. [`speckit/shared/INVARIANTS.md`](./speckit/shared/INVARIANTS.md)

Then read the relevant phase file and the specific task card.

## Hard Invariants

These are critical and must stay active for the whole session:

- `I1`: work-phase agents must not write directly to Qdrant or Kuzu
- `I2`: phase transitions happen only through explicit cert approval APIs
- `I3`: work-phase action manifest must be enforced before action execution
- `I4`: never use `SqliteSaver`; only `AsyncPostgresSaver` is allowed
- `I5`: every supervisor/workflow loop needs a `max_iterations` guard
- `I6`: approved team compositions are immutable; version instead of mutate
- `I7`: worker agents escalate only to the orchestrator, never directly to human queue
- `I8`: work-phase delta auto-approve threshold is `0.95`
- `I9`: open circuit breaker blocks task execution before LangGraph/LLM invocation
- `I10`: one shared Kuzu DB per `agent_type`, not per instance

Read the full definitions in [`speckit/shared/INVARIANTS.md`](./speckit/shared/INVARIANTS.md).

## Current State

Completed:

- Phase 0 foundations
- Phase 1 apprentice through `T1.11`

Implemented system today:

- FastAPI API under [`src/api`](./src/api)
- apprentice services under [`src/apprentice`](./src/apprentice)
- shared core/domain logic under [`src/core`](./src/core)
- infrastructure clients under [`src/infra`](./src/infra)
- Temporal scaffolding under [`src/temporal`](./src/temporal)

Not implemented end to end yet:

- Phase 2 journeyman
- Phase 3 work

## Working Rules For Task Execution

When following the spec:

1. Work through task cards in order, one task at a time.
2. Do not move past a failing checklist item.
3. Complete the task, run its tests, and confirm acceptance criteria before proceeding.
4. After a passing task, commit with:

```bash
git add -A
git commit -m "feat: complete [TASK_ID]"
```

If the user asks for a review, prioritize bugs, regressions, risks, and missing tests first.

## Runtime And Tooling

This is a `uv` project.

- Python: `>=3.12,<3.14`
- Advertised local version: [`.python-version`](./.python-version) currently pins `3.13`
- Dependency manifest: [`pyproject.toml`](./pyproject.toml)
- Lockfile: [`uv.lock`](./uv.lock)

Main services in [`docker-compose.yml`](./docker-compose.yml):

- Postgres
- Redis
- Qdrant
- Temporal
- Temporal UI

## Commands

Install and sync:

```bash
uv sync --dev
```

Run API:

```bash
uv run uvicorn src.api.main:app --reload
```

Run full implemented test coverage:

```bash
uv run pytest tests/phase_0/ tests/phase_1/ -v
```

Run apprentice tests only:

```bash
uv run pytest tests/phase_1/ -v
```

Lint:

```bash
uv run ruff check .
```

## Known Notes

- Some older paths still emit `datetime.utcnow()` deprecation warnings in tests.
- Kuzu graph path is shared per agent type at `./graphs/{agent_type}/domain.kuzu`.
- Qdrant is present in infrastructure, but direct certified-KB writes are tightly constrained by invariants.
- The repo already includes a Ruff ban for `langgraph.checkpoint.sqlite`.

## Useful Entry Points

- Spec overview: [`README.md`](./README.md)
- Phase 1 spec: [`speckit/phase-1-apprentice/PHASE.md`](./speckit/phase-1-apprentice/PHASE.md)
- Future phases:
  - [`speckit/phase-2-journeyman/PHASE.md`](./speckit/phase-2-journeyman/PHASE.md)
  - [`speckit/phase-3-work/PHASE.md`](./speckit/phase-3-work/PHASE.md)
