from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    APPRENTICE = "apprentice"
    JOURNEYMAN = "journeyman"
    WORK = "work"


class TopologyType(str, Enum):
    PIPELINE = "pipeline"
    ORCHESTRATED = "orchestrated"
    PEER = "peer"


class ObservationType(str, Enum):
    VIOLATION = "violation"
    LEARNED = "learned"
    AMBIGUOUS = "ambiguous"


class DeltaStatus(str, Enum):
    QUARANTINE = "quarantine"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class CompositionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ARCHIVED = "archived"


class CertGate(str, Enum):
    CERT1 = "cert1"
    CERT2 = "cert2"


class CertDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class FlagCategory(str, Enum):
    WRONG_OUTPUT = "wrong_output"
    WRONG_HANDOFF = "wrong_handoff"
    MISSED_CONSTRAINT = "missed_constraint"
