# Invariants

> These are hard safety rules. Load this file and keep it in context for the entire session.
> A violation of any invariant is a critical bug regardless of whether tests pass.

---

## I1 — No direct write to certified KB from work-phase agents

**Rule:** An agent in `Phase.WORK` must never call `qdrant_client.upsert()` or write any edge to Kuzu directly.
All observations from work-phase agents must be written to `delta_entries` (Postgres) with `status=quarantine`.

**Where to enforce:** `src/work/manifest_enforcer.py` — check phase before any knowledge write.
**Test:** `tests/phase_3/test_manifest_enforcer.py::test_work_phase_cannot_write_to_certified_kb`

---

## I2 — No automation at Cert gates

**Rule:** Phase transitions (`apprentice → journeyman`, `journeyman → work`) must only happen via an explicit
`POST /cert1/approve` or `POST /cert2/approve` API call with a valid `expert_id`.
No background job, scheduler, or score threshold may trigger a phase transition.

**Where to enforce:** `src/api/routes/cert.py` — the only place `phase` is updated in Redis.
**Test:** `tests/phase_1/test_cert1_gate.py::test_phase_not_updated_without_expert_approval`

---

## I3 — Action manifest is enforced before every action

**Rule:** In `Phase.WORK`, before executing any action, the agent must check its `action_manifest`.
If the action is not in `allowed_actions` or the data contains a `prohibited_field`, the action must be
refused and an `EscalationEvent` written. The action must NOT execute.

**Where to enforce:** `src/work/manifest_enforcer.py::enforce(action, payload) -> bool`
**Test:** `tests/phase_3/test_manifest_enforcer.py::test_prohibited_action_refused_and_escalated`

---

## I4 — Never use SqliteSaver

**Rule:** `SqliteSaver` must never be imported or used anywhere in the codebase.
The only permitted LangGraph checkpointer is `AsyncPostgresSaver`.

**Where to enforce:** Linting rule. Add to `pyproject.toml`:
```toml
[tool.ruff.lint]
banned-imports = ["langgraph.checkpoint.sqlite"]
```
**Test:** `grep -r "SqliteSaver" src/` must return empty.

---

## I5 — Every supervisor loop has a max_iterations guard

**Rule:** Every LangGraph node that can loop must check `state.iterations >= state.max_iterations`.
If the guard triggers, set `state.routing_decision = "escalate"` and `state.escalation_reason = "max_iterations"`.
Never let a loop run without a ceiling.

**Where to enforce:** `src/journeyman/graph_definition.py` and `src/work/graph_definition.py`
**Test:** `tests/phase_2/test_langgraph_state.py::test_max_iterations_triggers_escalation`

---

## I6 — Team composition is immutable after expert signature

**Rule:** A `team_compositions` row with `status=approved` and a non-null `expert_signature` must never be
mutated. Changes must create a new row with `version = old_version + 1` and archive the old row
(`status=archived`). The old row is never deleted.

**Where to enforce:** `src/api/routes/proposals.py` — reject any PUT that modifies an approved composition in place.
**Test:** `tests/phase_1/test_proposal_engine.py::test_approved_composition_is_immutable`

---

## I7 — Workers escalate to orchestrator only

**Rule:** In an orchestrated workflow, a worker agent must never create an `EscalationEvent` with
`routed_to="human_queue"` directly. Workers must set `state.escalation_required=True` and return to
the orchestrator node. Only the orchestrator may route to `human_queue`.

**Where to enforce:** `src/journeyman/graph_definition.py` — worker nodes have no access to the escalation router.
**Test:** `tests/phase_2/test_langgraph_state.py::test_worker_escalation_routes_to_orchestrator_not_human`

---

## I8 — Delta entry confidence threshold is higher in work phase

**Rule:** In `Phase.WORK`, the auto-promotion threshold for delta entries is `0.95` (not `0.85`).
Any delta entry from a work-phase agent with `confidence < 0.95` must be set to `status=flagged`
and routed to human review. The `0.95` value comes from `WORK_PHASE_DELTA_AUTO_APPROVE_THRESHOLD` env var.

**Where to enforce:** `src/delta/promotion_pipeline.py::get_auto_approve_threshold(phase) -> float`
**Test:** `tests/phase_3/test_manifest_enforcer.py::test_work_phase_delta_threshold_is_higher`

---

## I9 — Circuit breaker blocks task execution when OPEN

**Rule:** When a circuit breaker is in `CircuitState.OPEN`, any new task for that agent type must be
immediately routed to `human_queue` without invoking LangGraph or any LLM call.
**Where to enforce:** `src/temporal/workflows.py` — check circuit state before invoking LangGraph activity.
**Test:** `tests/phase_3/test_circuit_breaker.py::test_open_circuit_routes_to_human_queue`

---

## I10 — Kuzu: one DB instance per agent TYPE, not per instance

**Rule:** The path `./graphs/{agent_type}/domain.kuzu` must be the single shared graph for all instances
of that agent type. Never create a graph at `./graphs/{agent_type}/{instance_id}/`.
The `KUZU_GRAPHS_DIR` env var controls the base path.

**Where to enforce:** `src/infra/kuzu_client.py::get_connection(agent_type: str) -> kuzu.Connection`
**Test:** `tests/phase_0/test_infra_connectivity.py::test_kuzu_shared_per_type_not_per_instance`
