# Agent Worx

Agent Worx is an agent-lifecycle framework for building domain-specialized agents through
staged learning and certification.

The system starts with a domain seed, learns from expert Q&A in apprentice mode, proposes
a team structure when the knowledge graph is mature enough, validates coordination through
simulation, and then promotes the agent type to the next phase only through explicit expert
approval.

## Goal

The project is organized around three lifecycle phases:

- `apprentice`: learn the domain from an expert and build task/coordination knowledge
- `journeyman`: execute with guarded learning and human review
- `work`: operate under stricter safety constraints and quarantine new observations

At the moment, the implemented system covers the foundations and the full apprentice loop.

## What Exists Today

Completed so far:

- Phase 0 foundations
  - Temporal scaffolding
  - Redis, Postgres, Qdrant, and Kuzu clients
  - Postgres and Kuzu schema setup
  - Redis key conventions and state helpers
- Phase 1 apprentice
  - agent type registry and graph initialization
  - gap detection and question generation
  - answer processing, graph writing, and readiness scoring
  - team proposal generation and proposal review
  - simulation sessions and contract validation
  - Cert 1 advisory status and approval/rejection gate

Current test status:

- `tests/phase_0/`
- `tests/phase_1/`

The Phase 1 suite is green through `T1.11`.

## Architecture

Code layout:

- [`src/api`](/home/amir/workspace/agent-worx/src/api): FastAPI entrypoint and HTTP routes
- [`src/apprentice`](/home/amir/workspace/agent-worx/src/apprentice): apprentice-phase domain logic
- [`src/apprentice/simulation`](/home/amir/workspace/agent-worx/src/apprentice/simulation): simulation session manager and contract validation
- [`src/core`](/home/amir/workspace/agent-worx/src/core): shared models, enums, exceptions, and agent services
- [`src/infra`](/home/amir/workspace/agent-worx/src/infra): Postgres, Redis, Kuzu, and Qdrant integrations
- [`src/temporal`](/home/amir/workspace/agent-worx/src/temporal): worker/config/workflow scaffolding
- [`speckit`](/home/amir/workspace/agent-worx/speckit): implementation spec and invariants

Data stores:

- Postgres: durable metadata, proposals, cert events, simulation summaries
- Redis: fast operational state such as phase, readiness, and proposal flags
- Kuzu: per-agent-type task and coordination graphs
- Qdrant: reserved for later certified KB retrieval flows
- Temporal: orchestration foundation for later phases

API surface implemented now:

- `POST /api/v1/agent-types`
- `GET /api/v1/agent-types/{agent_type_id}`
- `POST /api/v1/agent-types/{agent_type_id}/qa/question`
- `POST /api/v1/agent-types/{agent_type_id}/qa/answer`
- `GET /api/v1/agent-types/{agent_type_id}/readiness`
- `GET /api/v1/agent-types/{agent_type_id}/proposal`
- `PUT /api/v1/agent-types/{agent_type_id}/proposal`
- `POST /api/v1/simulations`
- `GET /api/v1/simulations/{session_id}`
- `POST /api/v1/simulations/{session_id}/turn`
- `POST /api/v1/simulations/{session_id}/violations/{violation_index}/resolve`
- `POST /api/v1/simulations/{session_id}/close`
- `GET /api/v1/agent-types/{agent_type_id}/cert1-status`
- `POST /api/v1/agent-types/{agent_type_id}/cert1/approve`
- `POST /api/v1/agent-types/{agent_type_id}/cert1/reject`

## Running It

### 1. Start infrastructure

The repo includes a `docker-compose.yml` for the backing services.

```bash
docker compose up -d postgres redis qdrant temporal-postgres temporal temporal-ui
```

This starts:

- Postgres on `localhost:5432`
- Redis on `localhost:6379`
- Qdrant on `localhost:6333`
- Temporal on `localhost:7233`
- Temporal UI on `localhost:8080` and `localhost:8088`

### 2. Install Python dependencies

This is now a `uv` project.

```bash
uv sync --dev
```

The project currently supports Python `>=3.12,<3.14` and advertises `3.13` via
[.python-version](/home/amir/workspace/agent-worx/.python-version).

### 3. Run the API

```bash
uv run uvicorn src.api.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

### 4. Run tests

Full apprentice and foundations coverage:

```bash
uv run pytest tests/phase_0/ tests/phase_1/ -v
```

Phase 1 only:

```bash
uv run pytest tests/phase_1/ -v
```

Lint:

```bash
uv run ruff check .
```

## Notes

- The repo enforces the invariant that `SqliteSaver` must never be used.
- Kuzu graphs are shared per agent type at `./graphs/{agent_type}/domain.kuzu`.
- Some older code paths still emit `datetime.utcnow()` deprecation warnings during tests.
  They are non-failing but should be cleaned up.
- The apprentice path is the implemented core. Journeyman and work phase specs exist in
  [`speckit`](/home/amir/workspace/agent-worx/speckit), but those phases are not yet implemented end to end.

## Specs

The implementation spec lives in:

- [`speckit/README.md`](/home/amir/workspace/agent-worx/speckit/README.md)
- [`speckit/shared/INVARIANTS.md`](/home/amir/workspace/agent-worx/speckit/shared/INVARIANTS.md)
- [`speckit/phase-1-apprentice/PHASE.md`](/home/amir/workspace/agent-worx/speckit/phase-1-apprentice/PHASE.md)
