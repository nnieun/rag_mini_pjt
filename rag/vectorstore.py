import asyncio
from typing import Any

from qdrant_client.models import Distance, PointStruct, VectorParams

from rag.retry import retry_rate_limit


class QdrantLawStore:
    def __init__(
        self,
        client: Any,
        collection_name: str,
        embedding_client: Any | None = None,
        batch_size: int = 20,
        max_retries: int = 3,
        retry_wait_seconds: int = 65,
    ):
        self.client = client
        self.collection_name = collection_name
        self.embedding_client = embedding_client
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds

    def collection_exists(self) -> bool:
        return self.client.collection_exists(self.collection_name)

    async def index(
        self,
        chunks: list[dict],
        *,
        recreate: bool = False,
    ) -> int:
        if self.embedding_client is None:
            raise ValueError("index에는 embedding_client가 필요합니다.")
        searchable = [
            chunk for chunk in chunks if chunk.get("search_enabled") is True
        ]
        if not searchable:
            raise ValueError("검색 가능한 청크가 없습니다.")

        vectors: list[list[float]] = []
        for start in range(0, len(searchable), self.batch_size):
            batch = searchable[start : start + self.batch_size]
            batch_vectors = await retry_rate_limit(
                lambda batch=batch: self.embedding_client.aembed_documents(
                    [chunk["search_text"] for chunk in batch]
                ),
                label="Embedding",
                max_retries=self.max_retries,
                wait_seconds=self.retry_wait_seconds,
            )
            vectors.extend(batch_vectors)

        vector_size = len(vectors[0])
        vector_by_id = {
            chunk["point_id"]: vector
            for chunk, vector in zip(searchable, vectors)
        }
        zero_vector = [0.0] * vector_size

        if self.collection_exists():
            if not recreate:
                raise ValueError(
                    f"컬렉션이 이미 존재합니다: {self.collection_name}. "
                    "recreate=True로 명시해야 재생성합니다."
                )
            await asyncio.to_thread(
                self.client.delete_collection,
                self.collection_name,
            )

        await asyncio.to_thread(
            self.client.create_collection,
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
        points = [
            PointStruct(
                id=chunk["point_id"],
                vector=vector_by_id.get(chunk["point_id"], zero_vector),
                payload={
                    key: value
                    for key, value in chunk.items()
                    if key != "search_text"
                },
            )
            for chunk in chunks
        ]
        await asyncio.to_thread(
            self.client.upsert,
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        return len(points)

    def load(self) -> tuple[list[dict], dict[str, dict]]:
        all_chunks: list[dict] = []
        offset = None
        while True:
            records, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in records:
                payload = dict(point.payload or {})
                content = payload.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue
                payload["chunk_id"] = str(point.id)
                all_chunks.append(payload)
            if offset is None:
                break

        if not all_chunks:
            raise RuntimeError(
                f"Qdrant 컬렉션에 청크가 없습니다: {self.collection_name}"
            )
        searchable = [
            chunk
            for chunk in all_chunks
            if chunk.get("search_enabled") is True
        ]
        if not searchable:
            raise RuntimeError("search_enabled=True인 청크가 없습니다.")
        by_key = {
            str(chunk["chunk_key"]): chunk
            for chunk in all_chunks
            if chunk.get("chunk_key")
        }
        return searchable, by_key
