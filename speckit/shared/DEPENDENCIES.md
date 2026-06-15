# Dependencies — Pinned Versions

> All versions are pinned. Do not install `latest`. Do not upgrade without updating this file.

---

## Python

```txt
# pyproject.toml
python>=3.12,<3.14

# Core framework
langgraph==1.0.0
langchain-core==0.3.*
langsmith==0.3.*

# Temporal
temporalio==1.7.*

# Graph DB
kuzu==0.7.*               # use Vela Engineering fork for multi-writer: pip install git+https://github.com/Vela-Engineering/kuzu

# Vector DB
qdrant-client==1.12.*

# Relational / KV
asyncpg==0.30.*
psycopg==3.2.*
redis==5.2.*

# API
fastapi==0.115.*
uvicorn[standard]==0.32.*
pydantic==2.10.*

# LLM
anthropic==0.40.*         # primary LLM client
openai==1.57.*            # fallback / embedding

# NLP (answer processor entity extraction)
spacy==3.8.*
# python -m spacy download en_core_web_trf

# Observability
opentelemetry-sdk==1.29.*
opentelemetry-exporter-prometheus==0.50b0
prometheus-client==0.21.*

# Testing
pytest==8.3.*
pytest-asyncio==0.24.*
httpx==0.28.*             # async test client for FastAPI
```

---

## Infrastructure Images

```yaml
# docker-compose versions
temporal/auto-setup: "1.25.2"
temporalio/ui: "2.31.2"
postgres: "16.4"
redis: "7.2.6"
qdrant/qdrant: "v1.12.1"
```

---

## Node / Frontend (simulation console)

```json
{
  "react": "18.3.1",
  "typescript": "5.7.2",
  "vite": "6.0.3",
  "@tanstack/react-query": "5.62.2",
  "zustand": "5.0.2"
}
```

---

## Notes

- Kuzu Vela fork adds concurrent multi-writer support required for multi-agent workloads. Standard `pip install kuzu` is single-writer only — DO NOT use standard package in production.
- LangGraph `AsyncPostgresSaver` requires `asyncpg`. Do not use `SqliteSaver` anywhere — it has a database-level write lock that is a hard ceiling at ~100 concurrent agents.
- Use `pydantic==2.*` throughout. LangGraph 1.0 requires Pydantic v2. Do not mix v1 and v2 models.
