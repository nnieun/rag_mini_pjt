import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue
from rank_bm25 import BM25Okapi

from common.ai_model import get_embedding_model, get_llm_model
from common.qdrant import get_qdrant_client


COLLECTION_NAME = os.getenv(
    "QDRANT_COLLECTION_NAME",
    "ai_basic_law_adaptive_anchor_v1",
)
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
CANDIDATE_K = int(os.getenv("RAG_CANDIDATE_K", "20"))
RRF_K = int(os.getenv("RAG_RRF_K", "60"))
RETRY_WAIT_SECONDS = int(os.getenv("RAG_RETRY_WAIT_SECONDS", "65"))
MAX_RETRIES = int(os.getenv("RAG_MAX_RETRIES", "3"))


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class Source(BaseModel):
    source_id: str
    article: str = ""
    paragraph: str = ""
    item: str = ""
    subitem: str = ""
    title: str = ""
    content: str


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    method: str = "Hybrid(Dense+BM25+RRF)"
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str
    collection: str
    searchable_chunks: int
    total_chunks: int


@dataclass
class RagResources:
    embedding_client: Any
    llm: Any
    qdrant_client: Any
    chunks: list[dict]
    chunks_by_key: dict[str, dict]
    bm25: BM25Okapi
    query_embedding_cache: dict[str, list[float]]
    cache_lock: asyncio.Lock


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


def load_chunks(qdrant_client: Any) -> tuple[list[dict], dict[str, dict]]:
    all_chunks: list[dict] = []
    offset = None

    while True:
        records, offset = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
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
            f"Qdrant 컬렉션에 청크가 없습니다: {COLLECTION_NAME}"
        )

    searchable_chunks = [
        chunk
        for chunk in all_chunks
        if chunk.get("search_enabled") is True
    ]
    if not searchable_chunks:
        raise RuntimeError(
            "search_enabled=True인 검색 청크가 없습니다. "
            "최종 청킹 Notebook을 먼저 실행하세요."
        )

    chunks_by_key = {
        str(chunk["chunk_key"]): chunk
        for chunk in all_chunks
        if chunk.get("chunk_key")
    }
    return searchable_chunks, chunks_by_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    qdrant_client = get_qdrant_client()
    available = {
        collection.name
        for collection in qdrant_client.get_collections().collections
    }
    if COLLECTION_NAME not in available:
        raise RuntimeError(
            f"Qdrant 컬렉션이 없습니다: {COLLECTION_NAME}. "
            "qdrant_test_adaptive_hierarchy_anchor.ipynb를 먼저 실행하세요."
        )

    chunks, chunks_by_key = load_chunks(qdrant_client)
    bm25 = BM25Okapi(
        [tokenize(searchable_text(chunk)) for chunk in chunks]
    )
    app.state.rag = RagResources(
        embedding_client=get_embedding_model(),
        llm=get_llm_model(max_tokens=1200),
        qdrant_client=qdrant_client,
        chunks=chunks,
        chunks_by_key=chunks_by_key,
        bm25=bm25,
        query_embedding_cache={},
        cache_lock=asyncio.Lock(),
    )

    yield

    app.state.rag.query_embedding_cache.clear()
    qdrant_client.close()


app = FastAPI(
    title="AI 기본법 근거 기반 QA API",
    version="0.1.0",
    description=(
        "AI 기본법을 Hybrid Search로 검색하고 법률 원문에 근거한 "
        "답변과 출처를 반환합니다."
    ),
    lifespan=lifespan,
)


def is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "429" in message
        or "rate limit" in message
        or "rate_limit" in message
    )


async def retry_api_call(operation, label: str):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await operation()
        except Exception as error:
            if not is_rate_limit_error(error) or attempt == MAX_RETRIES:
                raise
            print(
                f"{label} Rate Limit: {RETRY_WAIT_SECONDS}초 후 재시도 "
                f"({attempt}/{MAX_RETRIES - 1})"
            )
            await asyncio.sleep(RETRY_WAIT_SECONDS)
    raise RuntimeError(f"{label} 호출에 실패했습니다.")


async def embed_query(resources: RagResources, question: str) -> list[float]:
    cached = resources.query_embedding_cache.get(question)
    if cached is not None:
        return cached

    async with resources.cache_lock:
        cached = resources.query_embedding_cache.get(question)
        if cached is not None:
            return cached

        vector = await retry_api_call(
            lambda: resources.embedding_client.aembed_query(question),
            "Embedding",
        )
        resources.query_embedding_cache[question] = vector
        return vector


async def dense_search(
    resources: RagResources,
    question: str,
    k: int = CANDIDATE_K,
) -> list[dict]:
    query_vector = await embed_query(resources, question)
    response = await asyncio.to_thread(
        resources.qdrant_client.query_points,
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="search_enabled",
                    match=MatchValue(value=True),
                )
            ]
        ),
        limit=k,
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


def bm25_search(
    resources: RagResources,
    question: str,
    k: int = CANDIDATE_K,
) -> list[dict]:
    scores = resources.bm25.get_scores(tokenize(question))
    ranked_indices = sorted(
        range(len(scores)),
        key=lambda index: scores[index],
        reverse=True,
    )
    return [
        {
            **resources.chunks[index],
            "bm25_score": float(scores[index]),
        }
        for index in ranked_indices
        if scores[index] > 0
    ][:k]


def rrf(ranked_lists: list[list[dict]], rrf_k: int = RRF_K) -> list[dict]:
    scores: dict[str, float] = {}
    documents: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, document in enumerate(ranked, start=1):
            chunk_id = str(document["chunk_id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (
                rrf_k + rank
            )
            documents[chunk_id] = document

    return [
        {
            **documents[chunk_id],
            "rrf_score": scores[chunk_id],
        }
        for chunk_id in sorted(scores, key=scores.get, reverse=True)
    ]


async def hybrid_search(
    resources: RagResources,
    question: str,
    k: int = TOP_K,
) -> list[dict]:
    dense_results = await dense_search(resources, question, CANDIDATE_K)
    keyword_results = bm25_search(resources, question, CANDIDATE_K)
    return rrf([dense_results, keyword_results])[:k]


def build_context(
    resources: RagResources,
    results: list[dict],
) -> tuple[str, list[Source]]:
    selected: list[dict] = []
    seen: set[str] = set()

    for result in results:
        parent_id = result.get("parent_id")
        document = resources.chunks_by_key.get(str(parent_id), result)
        key = str(document.get("chunk_id") or document.get("chunk_key"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(document)

    context_parts: list[str] = []
    sources: list[Source] = []
    for index, document in enumerate(selected, start=1):
        source_id = f"S{index}"
        content = str(document["content"])
        location = " ".join(
            str(document.get(field) or "")
            for field in (
                "article",
                "paragraph",
                "item",
                "subitem",
                "title",
            )
        ).strip()
        context_parts.append(f"[{source_id}] {location}\n{content}")
        sources.append(
            Source(
                source_id=source_id,
                article=str(document.get("article") or ""),
                paragraph=str(document.get("paragraph") or ""),
                item=str(document.get("item") or ""),
                subitem=str(document.get("subitem") or ""),
                title=str(document.get("title") or ""),
                content=content,
            )
        )

    return "\n\n".join(context_parts), sources


async def generate_answer(
    resources: RagResources,
    question: str,
    results: list[dict],
) -> tuple[str, list[Source]]:
    context, sources = build_context(resources, results)
    messages = [
        (
            "system",
            "당신은 AI 기본법 안내자입니다. 제공된 법령 근거만 사용해 "
            "한국어로 답하세요. 각 핵심 주장 뒤에 [S1] 형식으로 출처를 "
            "표시하세요. 질문에 답할 근거가 없거나 법률에 구체적인 내용이 "
            "없으면 '제공된 AI 기본법 근거에서는 확인할 수 없습니다'라고 "
            "명시하고 추측하지 마세요.",
        ),
        (
            "human",
            f"질문: {question}\n\n법령 근거:\n{context}",
        ),
    ]
    response = await retry_api_call(
        lambda: resources.llm.ainvoke(messages),
        "LLM",
    )
    answer = response.content
    if not isinstance(answer, str):
        answer = str(answer)
    return answer, sources


@app.get("/")
async def root():
    return {
        "message": "AI 기본법 근거 기반 QA API",
        "docs": "/docs",
        "endpoint": "POST /ask",
    }


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    resources: RagResources = request.app.state.rag
    return HealthResponse(
        status="ok",
        collection=COLLECTION_NAME,
        searchable_chunks=len(resources.chunks),
        total_chunks=len(resources.chunks_by_key),
    )


@app.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request) -> AskResponse:
    question = payload.question.strip()
    if len(question) < 2:
        raise HTTPException(status_code=422, detail="질문을 입력하세요.")

    resources: RagResources = request.app.state.rag
    started = time.perf_counter()
    try:
        results = await hybrid_search(resources, question, TOP_K)
        if not results:
            raise HTTPException(
                status_code=404,
                detail="관련 법률 근거를 찾지 못했습니다.",
            )
        answer, sources = await generate_answer(
            resources,
            question,
            results,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"RAG 처리 중 오류가 발생했습니다: {error}",
        ) from error

    elapsed_ms = (time.perf_counter() - started) * 1000
    return AskResponse(
        answer=answer,
        sources=sources,
        elapsed_ms=round(elapsed_ms, 2),
    )
