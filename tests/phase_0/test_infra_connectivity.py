from __future__ import annotations

import ast
from pathlib import Path

from src.temporal.config import get_temporal_config


ROOT = Path(__file__).resolve().parents[2]


def _compose_text() -> str:
    return (ROOT / "docker-compose.yml").read_text()


def test_temporal_compose_uses_pinned_images_and_namespace() -> None:
    compose = _compose_text()

    assert "temporalio/auto-setup:1.25.2" in compose
    assert "temporalio/ui:2.31.2" in compose
    assert "DEFAULT_NAMESPACE: agent-platform" in compose
    assert 'SKIP_DEFAULT_NAMESPACE_CREATION: "false"' in compose
    assert '"7233:7233"' in compose
    assert '"8080:8080"' in compose


def test_temporal_config_defaults_to_agent_platform(monkeypatch) -> None:
    monkeypatch.delenv("TEMPORAL_HOST", raising=False)
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)

    config = get_temporal_config()

    assert config.host == "localhost:7233"
    assert config.namespace == "agent-platform"


def test_sqlite_saver_is_not_imported() -> None:
    src_root = ROOT / "src"
    forbidden = {"SqliteSaver", "langgraph.checkpoint.sqlite"}

    for path in src_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden
        text = path.read_text()
        assert "SqliteSaver" not in text
