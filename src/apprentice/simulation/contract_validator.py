from __future__ import annotations

from src.core.models import AgentContract, ContractViolation


def validate_message(
    message_fields: dict,
    from_agent: str,
    to_agent: str,
    agents: list[AgentContract],
) -> list[ContractViolation]:
    receiving_agent = _find_agent(to_agent, agents)
    violations: list[ContractViolation] = []

    for field in receiving_agent.prohibited_fields:
        if field in message_fields:
            violations.append(
                ContractViolation(
                    field=field,
                    reason=f"Field '{field}' is prohibited for {to_agent}",
                    from_agent=from_agent,
                    to_agent=to_agent,
                )
            )

    for field in receiving_agent.input_schema:
        if field not in message_fields:
            violations.append(
                ContractViolation(
                    field=field,
                    reason=f"Required field '{field}' is missing for {to_agent}",
                    from_agent=from_agent,
                    to_agent=to_agent,
                )
            )

    return violations


def apply_resolution(
    violation: ContractViolation,
    resolution: str,
    clarification: str | None,
    agents: list[AgentContract],
) -> tuple[list[AgentContract], bool]:
    if resolution == "mark_edge_case":
        return agents, False
    if resolution != "clarify_contract":
        raise ValueError("resolution must be clarify_contract or mark_edge_case")
    if not clarification:
        raise ValueError("clarification is required for clarify_contract")

    updated_agents = [agent.model_copy(deep=True) for agent in agents]
    receiving_agent = _find_agent(violation.to_agent, updated_agents)
    receiving_agent.input_schema[violation.field] = clarification
    if violation.field in receiving_agent.prohibited_fields:
        receiving_agent.prohibited_fields.remove(violation.field)
    return updated_agents, True


def _find_agent(agent_name: str, agents: list[AgentContract]) -> AgentContract:
    for agent in agents:
        if agent.agent_name == agent_name:
            return agent
    raise ValueError(f"Agent '{agent_name}' is not part of this composition")
