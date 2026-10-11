import time
import os
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from common.answer_cache import PostgresAnswerCache
from common.database import create_database_pool
from rag.pipeline import RAGPipeline


logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    refresh: bool = False


class SourceResponse(BaseModel):
    source_id: str
    article: str = ""
    paragraph: str = ""
    item: str = ""
    subitem: str = ""
    title: str = ""
    content: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    method: str
    retrieved_articles: list[str]
    elapsed_ms: float
    cache_hit: bool = False
    processing_ms: float = 0.0


class HealthResponse(BaseModel):
    status: str
    collection: str
    searchable_chunks: int
    total_chunks: int


def get_pipeline(request: Request) -> RAGPipeline:
    return request.app.state.pipeline


def create_app(
    pipeline_factory: Callable[[], RAGPipeline] = RAGPipeline.create_default,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipeline = pipeline_factory()
        preload_reranker = os.getenv(
            "RAG_RERANK_PRELOAD", "true"
        ).lower() in {"1", "true", "yes", "on"}
        if preload_reranker:
            preload = getattr(pipeline, "preload_reranker", None)
            if callable(preload):
                preload()
        answer_cache = None
        cache_enabled = os.getenv(
            "RAG_ANSWER_CACHE_ENABLED", "true"
        ).lower() in {"1", "true", "yes", "on"}
        if cache_enabled:
            answer_cache = PostgresAnswerCache(
                create_database_pool(),
                collection_name=pipeline.retriever.collection_name,
                pipeline_version=os.getenv(
                    "RAG_CACHE_VERSION",
                    "conditional-rerank-v4",
                ),
                ttl_days=int(os.getenv("RAG_CACHE_TTL_DAYS", "30")),
            )
            try:
                await answer_cache.open()
            except Exception as error:
                logger.warning(
                    "PostgreSQL 답변 캐시를 사용할 수 없어 캐시 없이 시작합니다: %s",
                    error,
                )
                await answer_cache.close()
                answer_cache = None
            else:
                pipeline.answer_cache = answer_cache
        app.state.pipeline = pipeline
        try:
            yield
        finally:
            pipeline.close()
            if answer_cache is not None:
                await answer_cache.close()

    application = FastAPI(
        title="AI 기본법 근거 기반 QA API",
        version="0.2.0",
        description=(
            "AI 기본법을 Hybrid Search로 검색하고 법률 원문에 근거한 "
            "답변과 출처를 반환합니다."
        ),
        lifespan=lifespan,
    )
    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8443,http://127.0.0.1:8443",
        ).split(",")
        if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.get("/")
    async def root():
        return {
            "message": "AI 기본법 근거 기반 QA API",
            "docs": "/docs",
            "endpoint": "POST /ask",
        }

    @application.get("/health", response_model=HealthResponse)
    async def health(
        pipeline: RAGPipeline = Depends(get_pipeline),
    ) -> HealthResponse:
        return HealthResponse(
            status="ok",
            collection=pipeline.retriever.collection_name,
            searchable_chunks=len(pipeline.retriever.chunks),
            total_chunks=len(pipeline.retriever.chunks_by_key),
        )

    @application.post("/ask", response_model=AskResponse)
    async def ask(
        payload: AskRequest,
        pipeline: RAGPipeline = Depends(get_pipeline),
    ) -> AskResponse:
        started = time.perf_counter()
        try:
            result = await pipeline.answer(
                payload.question,
                bypass_cache=payload.refresh,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail=f"RAG 처리 중 오류가 발생했습니다: {error}",
            ) from error

        return AskResponse(
            **result.as_dict(),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    return application


app = create_app()
