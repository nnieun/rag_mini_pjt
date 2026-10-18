import time
import os
import logging
from pathlib import Path
from uuid import uuid4
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from common.answer_cache import PostgresAnswerCache
from common.database import create_database_pool
from documents.processor import extract_document
from rag.graph import LangGraphRAG
from rag.pipeline import RAGPipeline
from rag.retry import retry_rate_limit
from rag.schemas import ConversationHistoryItem


logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    refresh: bool = False
    thread_id: str | None = Field(default=None, max_length=100)
    history: list[ConversationHistoryItem] = Field(default_factory=list, max_length=10)


class SourceResponse(BaseModel):
    source_id: str
    article: str = ""
    paragraph: str = ""
    item: str = ""
    subitem: str = ""
    title: str = ""
    content: str
    highlight_text: str = ""


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    method: str
    retrieved_articles: list[str]
    elapsed_ms: float
    cache_hit: bool = False
    processing_ms: float = 0.0
    total_relevant: int = 0
    displayed_count: int = 0
    has_more: bool = False
    status: str = "answered"
    missing_fields: list[str] = Field(default_factory=list)
    request_id: str = ""
    model_usage: dict[str, int | None] = Field(default_factory=dict)
    resolved_question: str = ""


class DocumentResponse(BaseModel):
    filename: str
    media_type: str
    text: str
    pages: int
    extraction_method: str


class DocumentSummaryResponse(DocumentResponse):
    summary: str
    model_usage: dict[str, int | None] = Field(default_factory=dict)


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
                    "conditional-rerank-v10",
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
        app.state.rag_graph = LangGraphRAG(pipeline)
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
    report_dir = Path(__file__).resolve().parents[1] / "generated_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/reports", StaticFiles(directory=report_dir), name="reports")
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
        request: Request,
        pipeline: RAGPipeline = Depends(get_pipeline),
    ) -> AskResponse:
        started = time.perf_counter()
        try:
            result = await request.app.state.rag_graph.answer(
                payload.question,
                bypass_cache=payload.refresh,
                history=[item.model_dump() for item in payload.history],
                thread_id=payload.thread_id,
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
            status=("insufficient_evidence" if not result.sources else "answered"),
            request_id=str(uuid4()),
        )

    @application.post("/documents/extract", response_model=DocumentResponse)
    async def extract_uploaded_document(
        file: UploadFile = File(...),
    ) -> DocumentResponse:
        try:
            data = await file.read()
            extracted = extract_document(
                file.filename or "upload",
                file.content_type or "application/octet-stream",
                data,
                max_bytes=int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024))),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            await file.close()
        return DocumentResponse(**extracted.__dict__)

    @application.post("/documents/summarize", response_model=DocumentSummaryResponse)
    async def summarize_uploaded_document(
        file: UploadFile = File(...),
        pipeline: RAGPipeline = Depends(get_pipeline),
    ) -> DocumentSummaryResponse:
        try:
            extracted = extract_document(
                file.filename or "upload",
                file.content_type or "application/octet-stream",
                await file.read(),
                max_bytes=int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024))),
            )
            response = await retry_rate_limit(
                lambda: pipeline.llm.ainvoke(
                    [
                        (
                            "system",
                            "문서 원문만 사용해 핵심 내용, 적용 대상, 주요 의무, "
                            "조건·예외, 확인할 수 없는 정보를 한국어로 요약하세요. "
                            "원문에 없는 사실은 만들지 마세요.",
                        ),
                        ("human", extracted.text[:16000]),
                    ]
                ),
                label="Document summary",
                max_retries=pipeline.max_retries,
                wait_seconds=pipeline.retry_wait_seconds,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            await file.close()
        usage = getattr(response, "usage_metadata", None) or {}
        return DocumentSummaryResponse(
            **extracted.__dict__,
            summary=str(response.content),
            model_usage={
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )

    return application


app = create_app()
