from __future__ import annotations

from src.core.models import AgentContract, ContractViolation


def validate_message(
    message_fields: dict,
    from_agent: str,
    to_agent: str,
    agents: list[AgentContract],
) -> list[ContractViolation]:
    receiving_agent = _find_agent(to_agent, agents)
    if receiving_agent is None:
        return [
            ContractViolation(
                field=field,
                reason=f"'{to_agent}' has no contract in the approved composition",
                from_agent=from_agent,
                to_agent=to_agent,
            )
            for field in message_fields
        ]

    violations: list[ContractViolation] = []

    for field in message_fields:
        if field in receiving_agent.prohibited_fields:
            violations.append(
                ContractViolation(
                    field=field,
                    reason=f"'{to_agent}' is prohibited from receiving '{field}'",
                    from_agent=from_agent,
                    to_agent=to_agent,
                )
            )
        elif field not in receiving_agent.input_schema:
            violations.append(
                ContractViolation(
                    field=field,
                    reason=f"'{field}' is not declared in '{to_agent}'s input_schema",
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

    updated_agents: list[AgentContract] = []
    for agent in agents:
        if agent.agent_name == violation.to_agent:
            input_schema = dict(agent.input_schema)
            input_schema[violation.field] = clarification
            updated_agents.append(agent.model_copy(update={"input_schema": input_schema}))
        else:
            updated_agents.append(agent)
    return updated_agents, True


def _find_agent(agent_name: str, agents: list[AgentContract]) -> AgentContract | None:
    for agent in agents:
        if agent.agent_name == agent_name:
            return agent
    return None
