from __future__ import annotations


class AgentTypeAlreadyExists(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Agent type '{name}' already exists")


class AgentTypeNotFound(Exception):
    def __init__(self, agent_type_id: str):
        self.agent_type_id = agent_type_id
        super().__init__(f"Agent type '{agent_type_id}' not found")


class NoProposalFound(Exception):
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        super().__init__(f"No proposal found for agent type '{agent_type}'")


class ProposalAlreadyApproved(Exception):
    def __init__(self, agent_type: str, version: int):
        self.agent_type = agent_type
        self.version = version
        super().__init__(
            f"Proposal version {version} for '{agent_type}' is already approved "
            "and immutable"
        )
