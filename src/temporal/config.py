from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_TEMPORAL_HOST = "localhost:7233"
DEFAULT_TEMPORAL_NAMESPACE = "agent-platform"


@dataclass(frozen=True)
class TemporalConfig:
    host: str = DEFAULT_TEMPORAL_HOST
    namespace: str = DEFAULT_TEMPORAL_NAMESPACE


def get_temporal_config() -> TemporalConfig:
    return TemporalConfig(
        host=os.getenv("TEMPORAL_HOST", DEFAULT_TEMPORAL_HOST),
        namespace=os.getenv("TEMPORAL_NAMESPACE", DEFAULT_TEMPORAL_NAMESPACE),
    )
