import asyncio
import re
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue
from rank_bm25 import BM25Okapi

from rag.retry import retry_rate_limit
from rag.vectorstore import QdrantLawStore


def tokenize(text: str) -> list[str]:
    raw_tokens = re.findall(r"[가-힣]+|[a-z]+|\d+", text.lower())
    suffixes = (
        "인가요",
        "이란",
        "이랑",
        "에서",
        "으로",
        "에게",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
    )
    normalized = []
    for token in raw_tokens:
        for suffix in suffixes:
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        if token:
            normalized.append(token)
    return normalized


def searchable_text(chunk: dict) -> str:
    fields = (
        "law_name",
        "chapter",
        "section",
        "article",
        "paragraph",
        "item",
        "subitem",
        "title",
        "content",
    )
    return " ".join(str(chunk.get(field) or "") for field in fields)


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    rrf_k: int = 60,
) -> list[dict]:
    scores: dict[str, float] = {}
    documents: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, document in enumerate(ranked, start=1):
            chunk_id = str(document["chunk_id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (
                rrf_k + rank
            )
            documents[chunk_id] = document
    ranked_ids = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [
        {**documents[chunk_id], "rrf_score": scores[chunk_id]}
        for chunk_id in ranked_ids
    ]


class HybridRetriever:
    method = "Hybrid(Dense+BM25+RRF)"

    def __init__(
        self,
        *,
        qdrant_client: Any,
        embedding_client: Any,
        collection_name: str,
        top_k: int = 5,
        candidate_k: int = 20,
        rrf_k: int = 60,
        max_retries: int = 3,
        retry_wait_seconds: int = 65,
    ):
        self.client = qdrant_client
        self.embedding_client = embedding_client
        self.collection_name = collection_name
        self.top_k = top_k
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds
        self.query_embedding_cache: dict[str, list[float]] = {}
        self.cache_lock = asyncio.Lock()

        store = QdrantLawStore(self.client, self.collection_name)
        self.chunks, self.chunks_by_key = store.load()
        self.bm25 = BM25Okapi(
            [tokenize(searchable_text(chunk)) for chunk in self.chunks]
        )

    async def embed_query(self, question: str) -> list[float]:
        cached = self.query_embedding_cache.get(question)
        if cached is not None:
            return cached
        async with self.cache_lock:
            cached = self.query_embedding_cache.get(question)
            if cached is not None:
                return cached
            vector = await retry_rate_limit(
                lambda: self.embedding_client.aembed_query(question),
                label="Embedding",
                max_retries=self.max_retries,
                wait_seconds=self.retry_wait_seconds,
            )
            self.query_embedding_cache[question] = vector
            return vector

    async def dense_search(self, question: str, k: int | None = None) -> list[dict]:
        query_vector = await self.embed_query(question)
        response = await asyncio.to_thread(
            self.client.query_points,
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="search_enabled",
                        match=MatchValue(value=True),
                    )
                ]
            ),
            limit=k or self.candidate_k,
        )
        return [
            {
                **dict(point.payload or {}),
                "chunk_id": str(point.id),
                "dense_score": float(point.score),
            }
            for point in response.points
            if point.payload and point.payload.get("content")
        ]

    def bm25_search(self, question: str, k: int | None = None) -> list[dict]:
        scores = self.bm25.get_scores(tokenize(question))
        ranked_indices = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )
        return [
            {**self.chunks[index], "bm25_score": float(scores[index])}
            for index in ranked_indices
            if scores[index] > 0
        ][: k or self.candidate_k]

    async def search(self, question: str, k: int | None = None) -> list[dict]:
        limit = k or self.top_k
        dense = await self.dense_search(question, self.candidate_k)
        keyword = self.bm25_search(question, self.candidate_k)
        return reciprocal_rank_fusion(
            [dense, keyword], self.rrf_k
        )[:limit]

    @staticmethod
    def unique_articles(results: list[dict]) -> list[str]:
        return list(
            dict.fromkeys(
                str(document.get("article"))
                for document in results
                if document.get("article")
            )
        )
