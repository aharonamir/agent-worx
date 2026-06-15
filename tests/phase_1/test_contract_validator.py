from __future__ import annotations

import pytest

from src.apprentice.simulation.contract_validator import (
    apply_resolution,
    validate_message,
)
from src.core.models import AgentContract, ContractViolation


@pytest.fixture
def agents() -> list[AgentContract]:
    return [
        AgentContract(
            agent_name="order-agent",
            input_schema={"items": "list[str]"},
            output_schema={"order_id": "str", "items": "list[str]"},
            prohibited_fields=[],
        ),
        AgentContract(
            agent_name="kitchen-agent",
            input_schema={"order_id": "str", "items": "list[str]"},
            output_schema={"est_minutes": "int"},
            prohibited_fields=["card_token", "customer_address"],
        ),
    ]


def test_compliant_message_no_violations(agents: list[AgentContract]) -> None:
    violations = validate_message(
        message_fields={"order_id": "ord-1", "items": ["burger"]},
        from_agent="order-agent",
        to_agent="kitchen-agent",
        agents=agents,
    )

    assert violations == []


def test_prohibited_field_detected(agents: list[AgentContract]) -> None:
    violations = validate_message(
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "card_token": "tok_abc",
        },
        from_agent="order-agent",
        to_agent="kitchen-agent",
        agents=agents,
    )

    assert len(violations) == 1
    assert violations[0].field == "card_token"
    assert "prohibited" in violations[0].reason


def test_undeclared_field_detected(agents: list[AgentContract]) -> None:
    violations = validate_message(
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "table_number": 7,
        },
        from_agent="order-agent",
        to_agent="kitchen-agent",
        agents=agents,
    )

    assert len(violations) == 1
    assert violations[0].field == "table_number"
    assert "not declared" in violations[0].reason


def test_prohibited_takes_precedence_even_if_also_in_schema(
    agents: list[AgentContract],
) -> None:
    agents[1].input_schema["card_token"] = "str"

    violations = validate_message(
        message_fields={
            "order_id": "ord-1",
            "items": ["burger"],
            "card_token": "tok_abc",
        },
        from_agent="order-agent",
        to_agent="kitchen-agent",
        agents=agents,
    )

    assert len(violations) == 1
    assert violations[0].field == "card_token"
    assert "prohibited" in violations[0].reason


def test_missing_contract_returns_violation_per_field(
    agents: list[AgentContract],
) -> None:
    violations = validate_message(
        message_fields={"a": 1, "b": 2},
        from_agent="order-agent",
        to_agent="nonexistent-agent",
        agents=agents,
    )

    assert len(violations) == 2
    assert all("no contract" in violation.reason for violation in violations)


def test_clarify_contract_adds_field_to_schema(
    agents: list[AgentContract],
) -> None:
    violation = ContractViolation(
        field="table_number",
        reason="not declared",
        from_agent="order-agent",
        to_agent="kitchen-agent",
    )

    updated_agents, coord_written = apply_resolution(
        violation,
        resolution="clarify_contract",
        clarification="int",
        agents=agents,
    )

    kitchen = next(agent for agent in updated_agents if agent.agent_name == "kitchen-agent")
    assert kitchen.input_schema["table_number"] == "int"
    assert coord_written is True

    original_kitchen = next(agent for agent in agents if agent.agent_name == "kitchen-agent")
    assert "table_number" not in original_kitchen.input_schema


def test_mark_edge_case_no_schema_change(agents: list[AgentContract]) -> None:
    violation = ContractViolation(
        field="table_number",
        reason="not declared",
        from_agent="order-agent",
        to_agent="kitchen-agent",
    )

    updated_agents, coord_written = apply_resolution(
        violation,
        resolution="mark_edge_case",
        clarification=None,
        agents=agents,
    )

    assert updated_agents == agents
    assert coord_written is False


def test_clarify_contract_without_clarification_raises(
    agents: list[AgentContract],
) -> None:
    violation = ContractViolation(
        field="table_number",
        reason="not declared",
        from_agent="order-agent",
        to_agent="kitchen-agent",
    )

    with pytest.raises(ValueError):
        apply_resolution(
            violation,
            resolution="clarify_contract",
            clarification=None,
            agents=agents,
        )
