# Project Structure

> Generate every file at the path listed here. Do not invent paths.

---

## Root Layout

```
agent-lifecycle-framework/
├── docker-compose.yml               # All infra services
├── .env.example                     # Environment variable template
├── requirements.txt                 # Python deps (from DEPENDENCIES.md)
├── pyproject.toml                   # Project metadata + tool config
│
├── alembic/                         # DB migrations
│   ├── env.py
│   └── versions/
│       ├── 001_initial_schema.py
│       └── 002_cert_events.py
│
├── src/
│   ├── __init__.py
│   │
│   ├── core/                        # Domain models and shared types
│   │   ├── __init__.py
│   │   ├── models.py                # All Pydantic models (see DATA_SCHEMAS.md)
│   │   ├── enums.py                 # Phase, TopologyType, ObservationType, etc.
│   │   └── exceptions.py            # Custom exception classes
│   │
│   ├── infra/                       # Infrastructure clients (thin wrappers)
│   │   ├── __init__.py
│   │   ├── kuzu_client.py           # Kuzu connection + query helpers
│   │   ├── qdrant_client.py         # Qdrant collection + upsert/search helpers
│   │   ├── redis_client.py          # Redis + Streams helpers
│   │   └── postgres_client.py       # asyncpg pool + query helpers
│   │
│   ├── apprentice/                  # Phase 1 — all apprentice kernel components
│   │   ├── __init__.py
│   │   ├── gap_detector.py          # T1.2
│   │   ├── question_generator.py    # T1.3
│   │   ├── answer_processor.py      # T1.4
│   │   ├── graph_writer.py          # T1.5
│   │   ├── readiness_scorer.py      # T1.6
│   │   ├── proposal_engine.py       # T1.7
│   │   └── simulation/
│   │       ├── __init__.py
│   │       ├── session_manager.py   # T1.9
│   │       └── contract_validator.py # T1.10
│   │
│   ├── journeyman/                  # Phase 2 — supervised execution
│   │   ├── __init__.py
│   │   ├── graph_definition.py      # T2.1 — LangGraph StateGraph
│   │   ├── retrieval.py             # T2.3 + T2.4 — KB + graph retrieval
│   │   ├── shadow_queue.py          # T2.5
│   │   └── delta_buffer.py          # T2.6
│   │
│   ├── work/                        # Phase 3 — production execution
│   │   ├── __init__.py
│   │   ├── manifest_enforcer.py     # T3.1
│   │   ├── scope_detector.py        # T3.2
│   │   ├── drift_monitor.py         # T3.5
│   │   └── circuit_breaker.py       # T3.6
│   │
│   ├── temporal/                    # Temporal workflow + activity definitions
│   │   ├── __init__.py
│   │   ├── workflows.py             # AgentTaskWorkflow, ApprenticeSessionWorkflow
│   │   ├── activities.py            # T2.2 — LangGraph wrapped as Temporal activities
│   │   └── worker.py                # Temporal worker entrypoint
│   │
│   ├── delta/                       # Delta quarantine + promotion pipeline
│   │   ├── __init__.py
│   │   └── promotion_pipeline.py    # T2.7
│   │
│   ├── api/                         # FastAPI application
│   │   ├── __init__.py
│   │   ├── main.py                  # App factory, middleware, startup
│   │   ├── dependencies.py          # Shared FastAPI dependencies (DB pools, etc.)
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── agent_types.py       # T1.1 — /agent-types endpoints
│   │       ├── apprentice.py        # Q&A session, readiness endpoints
│   │       ├── proposals.py         # T1.8 — proposal review endpoints
│   │       ├── simulations.py       # T1.9 — simulation session endpoints
│   │       ├── cert.py              # T1.11 + T2.8 — cert gate endpoints
│   │       ├── shadow.py            # T2.5 — shadow review endpoints
│   │       └── health.py            # /health, /ready
│   │
│   └── observability/
│       ├── __init__.py
│       ├── metrics.py               # Prometheus metric definitions
│       └── tracing.py               # LangSmith + OpenTelemetry setup
│
├── graphs/                          # Kuzu DB files (one per agent type, gitignored)
│   └── .gitkeep
│
├── tests/
│   ├── conftest.py                  # Shared fixtures (test DB, mock Redis, etc.)
│   ├── phase_0/
│   │   ├── test_infra_connectivity.py
│   │   └── test_schemas.py
│   ├── phase_1/
│   │   ├── test_gap_detector.py
│   │   ├── test_question_generator.py
│   │   ├── test_answer_processor.py
│   │   ├── test_graph_writer.py
│   │   ├── test_readiness_scorer.py
│   │   ├── test_proposal_engine.py
│   │   ├── test_simulation_session.py
│   │   ├── test_contract_validator.py
│   │   └── test_cert1_gate.py
│   ├── phase_2/
│   │   ├── test_langgraph_state.py
│   │   ├── test_retrieval.py
│   │   ├── test_shadow_queue.py
│   │   ├── test_delta_buffer.py
│   │   ├── test_delta_promotion.py
│   │   └── test_cert2_gate.py
│   └── phase_3/
│       ├── test_manifest_enforcer.py
│       ├── test_scope_detector.py
│       ├── test_drift_monitor.py
│       └── test_circuit_breaker.py
│
└── console/                         # React simulation console (Phase 1)
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── components/
        │   ├── RoleSelector.tsx
        │   ├── ConversationThread.tsx
        │   ├── RunRecorder.tsx
        │   └── ViolationBanner.tsx
        └── hooks/
            ├── useSimulationSession.ts
            └── useWebSocket.ts
```

---

## Environment Variables

```bash
# .env.example

# Postgres
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/agent_checkpoints
KNOWLEDGE_DB_URL=postgresql+asyncpg://user:pass@localhost:5432/agent_knowledge
OPS_DB_URL=postgresql+asyncpg://user:pass@localhost:5432/agent_ops

# Redis
REDIS_URL=redis://localhost:6379/0

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=certified_kb

# Kuzu
KUZU_GRAPHS_DIR=./graphs

# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=agent-platform

# LLM
ANTHROPIC_API_KEY=sk-ant-...
EMBEDDING_MODEL=text-embedding-3-small   # OpenAI embedding model
EMBEDDING_DIM=1536

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls-...
LANGCHAIN_PROJECT=agent-lifecycle-framework

# Thresholds (configurable)
READINESS_PROPOSAL_THRESHOLD=0.55
READINESS_CERT1_THRESHOLD=0.80
DRIFT_WARN_THRESHOLD=0.15
DRIFT_CRITICAL_THRESHOLD=0.30
CIRCUIT_BREAKER_ERROR_RATE_THRESHOLD=0.20
CIRCUIT_BREAKER_CONSECUTIVE_FAILURES=5
WORK_PHASE_DELTA_AUTO_APPROVE_THRESHOLD=0.95
```
