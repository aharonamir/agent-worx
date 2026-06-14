from __future__ import annotations


def _single_value(result):
    assert result.has_next()
    row = result.get_next()
    assert not result.has_next()
    return row[0]


def test_kuzu_schema_initializes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))

    from src.infra.kuzu_client import execute, initialize_schema

    initialize_schema("test-agent")

    execute(
        "test-agent",
        """
        CREATE (:Concept {
            id: 'c1',
            label: 'burger',
            namespace: 'task',
            confidence: 0.9,
            created_at: '2025-01-01'
        })
        """,
    )
    concept_label = _single_value(
        execute("test-agent", "MATCH (c:Concept {id: 'c1'}) RETURN c.label")
    )
    assert concept_label == "burger"

    execute(
        "test-agent",
        """
        CREATE (:Constraint {
            id: 'k1',
            description: 'must preserve allergies',
            severity: 'hard'
        })
        """,
    )
    constraint_description = _single_value(
        execute("test-agent", "MATCH (c:Constraint {id: 'k1'}) RETURN c.description")
    )
    assert constraint_description == "must preserve allergies"

    execute(
        "test-agent",
        """
        CREATE (:AgentRole {
            id: 'r1',
            name: 'order-agent',
            input_schema: '{"items":"list[str]"}',
            output_schema: '{"ticket":"str"}',
            prohibited_fields: '["payment_card"]'
        })
        """,
    )
    role_name = _single_value(
        execute("test-agent", "MATCH (r:AgentRole {id: 'r1'}) RETURN r.name")
    )
    assert role_name == "order-agent"

    execute(
        "test-agent",
        """
        CREATE (:Concept {
            id: 'c2',
            label: 'menu',
            namespace: 'task',
            confidence: 0.8,
            created_at: '2025-01-01'
        })
        """,
    )
    execute(
        "test-agent",
        """
        MATCH (a:Concept {id:'c1'}), (b:Concept {id:'c2'})
        CREATE (a)-[:RELATES_TO {relation:'has', confidence:0.85, version:1}]->(b)
        """,
    )
    relation = execute(
        "test-agent",
        """
        MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept)
        RETURN a.label, r.relation, b.label
        """,
    ).get_next()
    assert relation == ["burger", "has", "menu"]

    execute(
        "test-agent",
        """
        MATCH (c:Concept {id:'c1'}), (k:Constraint {id:'k1'})
        CREATE (c)-[:HAS_CONSTRAINT]->(k)
        """,
    )
    constrained = _single_value(
        execute(
            "test-agent",
            """
            MATCH (:Concept {id:'c1'})-[:HAS_CONSTRAINT]->(k:Constraint)
            RETURN k.id
            """,
        )
    )
    assert constrained == "k1"

    execute(
        "test-agent",
        """
        CREATE (:AgentRole {
            id: 'r2',
            name: 'kitchen-agent',
            input_schema: '{"ticket":"str"}',
            output_schema: '{"status":"str"}',
            prohibited_fields: '[]'
        })
        """,
    )
    execute(
        "test-agent",
        """
        MATCH (a:AgentRole {id:'r1'}), (b:AgentRole {id:'r2'})
        CREATE (a)-[:HANDS_OFF_TO {
            condition:'ticket ready',
            validates:'["ticket"]',
            confidence:0.9
        }]->(b)
        """,
    )
    handoff = execute(
        "test-agent",
        """
        MATCH (a:AgentRole)-[h:HANDS_OFF_TO]->(b:AgentRole)
        RETURN a.name, h.condition, b.name
        """,
    ).get_next()
    assert handoff == ["order-agent", "ticket ready", "kitchen-agent"]

    execute(
        "test-agent",
        """
        MATCH (c:Concept {id:'c1'}), (r:AgentRole {id:'r1'})
        CREATE (c)-[:HAS_ROLE]->(r)
        """,
    )
    role = _single_value(
        execute(
            "test-agent",
            """
            MATCH (:Concept {id:'c1'})-[:HAS_ROLE]->(r:AgentRole)
            RETURN r.name
            """,
        )
    )
    assert role == "order-agent"


def test_kuzu_schema_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KUZU_GRAPHS_DIR", str(tmp_path))

    from src.infra.kuzu_client import initialize_schema

    initialize_schema("idempotent-agent")
    initialize_schema("idempotent-agent")
