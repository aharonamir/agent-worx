from __future__ import annotations

import os
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models


DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "certified_kb"
DEFAULT_EMBEDDING_DIM = 1536

PAYLOAD_INDEXES = {
    "agent_type": models.PayloadSchemaType.KEYWORD,
    "namespace": models.PayloadSchemaType.KEYWORD,
    "source_id": models.PayloadSchemaType.KEYWORD,
}


@dataclass(frozen=True)
class QdrantConfig:
    url: str = DEFAULT_QDRANT_URL
    collection: str = DEFAULT_COLLECTION
    embedding_dim: int = DEFAULT_EMBEDDING_DIM


def get_qdrant_config() -> QdrantConfig:
    return QdrantConfig(
        url=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL),
        collection=os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", str(DEFAULT_EMBEDDING_DIM))),
    )


def create_qdrant_client() -> QdrantClient:
    config = get_qdrant_config()
    return QdrantClient(url=config.url)


def ensure_certified_kb_collection(client: QdrantClient | None = None) -> None:
    config = get_qdrant_config()
    qdrant = client or create_qdrant_client()

    if not qdrant.collection_exists(config.collection):
        qdrant.create_collection(
            collection_name=config.collection,
            vectors_config=models.VectorParams(
                size=config.embedding_dim,
                distance=models.Distance.COSINE,
            ),
        )

    for field_name, field_schema in PAYLOAD_INDEXES.items():
        collection = qdrant.get_collection(config.collection)
        if field_name in collection.payload_schema:
            continue
        qdrant.create_payload_index(
            collection_name=config.collection,
            field_name=field_name,
            field_schema=field_schema,
        )
