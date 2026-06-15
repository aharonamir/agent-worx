from __future__ import annotations


class AgentTypeAlreadyExists(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Agent type '{name}' already exists")


class AgentTypeNotFound(Exception):
    def __init__(self, agent_type_id: str):
        self.agent_type_id = agent_type_id
        super().__init__(f"Agent type '{agent_type_id}' not found")
