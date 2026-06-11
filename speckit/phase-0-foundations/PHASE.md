# Phase 0 — Foundations

## Goal
Get all five infrastructure services running, validated, and connected.
No agent logic in this phase — only the platform substrate.
Phases 1–3 will fail without this being production-stable.

## Dependencies
None. This phase has no prerequisites.

## Exit Condition
All items in the checklist below are passing.

## Tasks
| ID | Task | File |
|---|---|---|
| T0.1 | Temporal cluster | T0.1-temporal.md |
| T0.2 | Postgres instance | T0.2-postgres.md |
| T0.3 | Redis instance | T0.3-redis.md |
| T0.4 | Qdrant instance | T0.4-qdrant.md |
| T0.5 | Kuzu graph DB setup | T0.5-kuzu.md |
| T0.6 | Kuzu domain graph schema | T0.6-schema-kuzu.md |
| T0.7 | Postgres delta quarantine schema | T0.7-schema-postgres.md |
| T0.8 | Redis key schema | T0.8-schema-redis.md |

## Checklist
Run before proceeding to Phase 1.

```
[ ] T0.1 — Temporal UI accessible at localhost:8080, namespace agent-platform registered
[ ] T0.2 — All three Postgres DBs created, pgvector extension confirmed, connection pooling active
[ ] T0.3 — Redis PING returns PONG, RediSearch module active, Streams round-trip passes
[ ] T0.4 — Qdrant /healthz returns ok, certified_kb collection created, payload indexes active
[ ] T0.5 — Kuzu imports without error, multi-hop query on 100K node graph completes < 50ms
[ ] T0.6 — Kuzu schema (all 4 node tables, all 3 rel tables) created for a test agent type
[ ] T0.7 — All 4 Postgres tables created, INSERT+SELECT round-trip passes on each
[ ] T0.8 — All Redis key patterns tested with HSET/HGET/XADD/XREAD
[ ] ALL  — Single connectivity test script touches all 5 services and returns green
```

## Test Command
```bash
pytest tests/phase_0/ -v
```
