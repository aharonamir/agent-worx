from __future__ import annotations

from alembic import op


revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_types (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name VARCHAR(100) NOT NULL UNIQUE,
            goal TEXT NOT NULL,
            task_boundary TEXT NOT NULL,
            topic_list JSONB NOT NULL,
            topology_type VARCHAR(20) NOT NULL,
            workflow_participants JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_types_name ON agent_types(name)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_types")
