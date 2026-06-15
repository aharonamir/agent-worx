from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.apprentice.proposal_engine import generate_proposal
from src.core.enums import CompositionStatus, TopologyType
from src.core.exceptions import NoProposalFound, ProposalAlreadyApproved
from src.core.models import AgentContract, HandoffContract, ProposalArtifact
from src.infra.postgres_client import get_pool


async def get_latest_proposal(agent_type: str) -> ProposalArtifact | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM team_compositions
            WHERE agent_type = $1
            ORDER BY version DESC
            LIMIT 1
            """,
            agent_type,
        )

    if row is None:
        return None
    return _row_to_artifact(row)


async def approve_proposal(agent_type: str, expert_id: str) -> ProposalArtifact:
    latest = await _require_mutable_latest(agent_type)
    signed_at = datetime.now(UTC)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE team_compositions
            SET status = $1,
                expert_signature = $2,
                signed_at = $3
            WHERE agent_type = $4 AND version = $5
            """,
            CompositionStatus.APPROVED.value,
            expert_id,
            signed_at.replace(tzinfo=None),
            agent_type,
            latest.version,
        )

    latest.status = CompositionStatus.APPROVED
    latest.expert_signature = expert_id
    latest.signed_at = signed_at
    return latest


async def edit_proposal(
    agent_type: str,
    expert_id: str,
    edits: ProposalArtifact,
) -> ProposalArtifact:
    latest = await _require_mutable_latest(agent_type)
    new_version = latest.version + 1
    signed_at = datetime.now(UTC)
    created_at = datetime.now(UTC)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE team_compositions
                SET status = $1
                WHERE agent_type = $2 AND version = $3
                """,
                CompositionStatus.ARCHIVED.value,
                agent_type,
                latest.version,
            )
            await conn.execute(
                """
                INSERT INTO team_compositions (
                    id,
                    agent_type,
                    version,
                    topology,
                    agent_list,
                    contracts,
                    rationale,
                    status,
                    expert_signature,
                    signed_at,
                    created_at
                )
                VALUES (
                    $1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb,
                    $8, $9, $10, $11
                )
                """,
                uuid.UUID(edits.id),
                agent_type,
                new_version,
                edits.topology.value,
                json.dumps([agent.model_dump() for agent in edits.agents]),
                json.dumps([contract.model_dump() for contract in edits.contracts]),
                json.dumps(
                    {
                        "rationale_per_agent": edits.rationale_per_agent,
                        "rationale_per_contract": edits.rationale_per_contract,
                    }
                ),
                CompositionStatus.APPROVED.value,
                expert_id,
                signed_at.replace(tzinfo=None),
                created_at.replace(tzinfo=None),
            )

    edits.agent_type_id = agent_type
    edits.version = new_version
    edits.status = CompositionStatus.APPROVED
    edits.expert_signature = expert_id
    edits.signed_at = signed_at
    edits.created_at = created_at
    return edits


async def reject_proposal(
    agent_type: str,
    rejection_reason: str,
    agent_goal: str,
    task_boundary: str,
    declared_topology: TopologyType,
    workflow_participants: list[str],
) -> ProposalArtifact:
    latest = await _require_mutable_latest(agent_type)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE team_compositions
            SET status = $1,
                rationale = jsonb_set(
                    COALESCE(rationale, '{}'::jsonb),
                    '{rejection_reason}',
                    to_jsonb($2::text)
                )
            WHERE agent_type = $3 AND version = $4
            """,
            CompositionStatus.ARCHIVED.value,
            rejection_reason,
            agent_type,
            latest.version,
        )

    return await generate_proposal(
        agent_type,
        agent_goal,
        task_boundary,
        declared_topology,
        workflow_participants,
        rejection_context=rejection_reason,
    )


async def _require_mutable_latest(agent_type: str) -> ProposalArtifact:
    latest = await get_latest_proposal(agent_type)
    if latest is None:
        raise NoProposalFound(agent_type)
    if (
        latest.status == CompositionStatus.APPROVED
        or latest.expert_signature is not None
    ):
        raise ProposalAlreadyApproved(agent_type, latest.version)
    return latest


def _row_to_artifact(row: Any) -> ProposalArtifact:
    rationale = _json_value(row["rationale"]) if row["rationale"] else {}
    signed_at = _as_aware_utc(row["signed_at"]) if row["signed_at"] else None
    return ProposalArtifact(
        id=str(row["id"]),
        agent_type_id=row["agent_type"],
        version=row["version"],
        topology=TopologyType(row["topology"]),
        agents=[
            AgentContract.model_validate(agent)
            for agent in _json_value(row["agent_list"])
        ],
        contracts=[
            HandoffContract.model_validate(contract)
            for contract in _json_value(row["contracts"])
        ],
        rationale_per_agent=rationale.get("rationale_per_agent", {}),
        rationale_per_contract=rationale.get("rationale_per_contract", {}),
        status=CompositionStatus(row["status"]),
        created_at=_as_aware_utc(row["created_at"]),
        expert_signature=row["expert_signature"],
        signed_at=signed_at,
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
