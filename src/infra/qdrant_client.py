from __future__ import annotations

import os
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.models import FieldCondition, Filter, MatchValue, MinShould, Range


DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "certified_kb"
DEFAULT_EMBEDDING_DIM = 1536

PAYLOAD_INDEXES = {
    "agent_type": models.PayloadSchemaType.KEYWORD,
    "phase": models.PayloadSchemaType.KEYWORD,
    "confidence": models.PayloadSchemaType.FLOAT,
    "version": models.PayloadSchemaType.INTEGER,
}

_client: QdrantClient | None = None


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


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = create_qdrant_client()
    return _client


def ensure_certified_kb_collection(client: QdrantClient | None = None) -> None:
    config = get_qdrant_config()
    qdrant = client or get_client()

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


def setup_collection() -> None:
    ensure_certified_kb_collection()


def upsert_knowledge(point_id: str, vector: list[float], payload: dict) -> None:
    config = get_qdrant_config()
    get_client().upsert(
        collection_name=config.collection,
        points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def search_knowledge(
    query_vector: list[float],
    agent_type: str,
    min_confidence: float = 0.7,
    phases: list[str] | None = None,
    top_k: int = 5,
) -> list[dict]:
    config = get_qdrant_config()
    must_conditions = [
        FieldCondition(key="agent_type", match=MatchValue(value=agent_type)),
        FieldCondition(key="confidence", range=Range(gte=min_confidence)),
    ]
    if phases:
        query_filter = Filter(
            must=must_conditions,
            min_should=MinShould(
                conditions=[
                    FieldCondition(key="phase", match=MatchValue(value=phase))
                    for phase in phases
                ],
                min_count=1,
            ),
        )
    else:
        query_filter = Filter(must=must_conditions)

    results = get_client().search(
        collection_name=config.collection,
        query_vector=query_vector,
        query_filter=query_filter,
        limit=top_k,
    )
    return [{"id": result.id, "score": result.score, "payload": result.payload} for result in results]


if __name__ == "__main__":
    setup_collection()
    print(f"Collection '{get_qdrant_config().collection}' ready with payload indexes.")
