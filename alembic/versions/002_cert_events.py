from __future__ import annotations

from alembic import op

from src.infra.postgres_client import KNOWLEDGE_SCHEMA_DDL


revision = "002_cert_events"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for ddl in KNOWLEDGE_SCHEMA_DDL:
        if "agent_types" not in ddl and "idx_agent_types_name" not in ddl:
            op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS escalation_events")
    op.execute("DROP TABLE IF EXISTS shadow_reviews")
    op.execute("DROP TABLE IF EXISTS cert_events")
    op.execute("DROP TABLE IF EXISTS team_compositions")
    op.execute("DROP TABLE IF EXISTS delta_entries")
