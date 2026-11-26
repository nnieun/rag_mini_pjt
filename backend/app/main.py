import asyncio
import time
import os
import logging
from pathlib import Path
from uuid import UUID
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from common.answer_cache import PostgresAnswerCache
from common.database import create_checkpoint_pool, create_database_pool
from common.telemetry import RequestTrace, get_current_trace, trace_scope
from common.trace_store import PostgresTraceStore, save_trace_safely
from documents.processor import extract_document
from mcp_server.http import build_http_server, mcp_route
from rag.graph import LangGraphRAG, checkpoint_serde
from rag.mcp_client import load_external_tools
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


TRACED_PATHS = {"/ask", "/documents/extract", "/documents/summarize"}


def _env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


def _schedule_trace_write(app: FastAPI, trace: RequestTrace) -> None:
    """응답을 늦추지 않도록 추적 저장은 백그라운드 작업으로 돌린다."""
    store = getattr(app.state, "trace_store", None)
    if store is None:
        return
    task = asyncio.create_task(save_trace_safely(store, trace))
    pending = app.state.pending_trace_writes
    pending.add(task)
    task.add_done_callback(pending.discard)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


async def open_checkpointer():
    """thread_id별 대화 상태를 PostgreSQL에 저장하는 체크포인터를 연다.

    DB를 쓸 수 없으면 (None, None)을 돌려주고, 이때 후속 질문은 요청의 history로만 처리한다.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pool = create_checkpoint_pool()
    try:
        await pool.open(wait=True, timeout=5.0)
        checkpointer = AsyncPostgresSaver(pool, serde=checkpoint_serde())
        await checkpointer.setup()
    except Exception as error:
        logger.warning(
            "LangGraph 체크포인터를 사용할 수 없어 history 기반 대화만 지원합니다: %s",
            error,
        )
        await pool.close()
        return None, None
    return pool, checkpointer


def get_pipeline(request: Request) -> RAGPipeline:
    return request.app.state.pipeline


def create_app(
    pipeline_factory: Callable[[], RAGPipeline] = RAGPipeline.create_default,
) -> FastAPI:
    mcp_server = None

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
        checkpoint_pool = None
        checkpointer = None
        if _env_flag("RAG_CHECKPOINT_ENABLED", True):
            checkpoint_pool, checkpointer = await open_checkpointer()
        trace_store = None
        if _env_flag("RAG_TRACE_STORE_ENABLED", True):
            trace_store = PostgresTraceStore(
                create_database_pool(),
                pipeline_version=os.getenv("RAG_CACHE_VERSION", "conditional-rerank-v10"),
            )
            try:
                await trace_store.open()
            except Exception as error:
                logger.warning(
                    "PostgreSQL 요청 추적 저장소를 사용할 수 없어 기록 없이 시작합니다: %s",
                    error,
                )
                await trace_store.close()
                trace_store = None
        app.state.pipeline = pipeline
        external_tools = []
        if _env_flag("RAG_MCP_CLIENT_ENABLED", True):
            try:
                external_tools = await load_external_tools()
            except Exception as error:  # 설정 파일 오류 등
                logger.warning("외부 MCP 서버 설정을 읽지 못해 외부 도구 없이 시작합니다: %s", error)
        app.state.rag_graph = LangGraphRAG(
            pipeline, checkpointer=checkpointer, external_tools=external_tools
        )
        app.state.trace_store = trace_store
        app.state.pending_trace_writes = set()
        try:
            async with AsyncExitStack() as stack:
                if mcp_server is not None:
                    await stack.enter_async_context(mcp_server.session_manager.run())
                yield
        finally:
            pending = app.state.pending_trace_writes
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            pipeline.close()
            if answer_cache is not None:
                await answer_cache.close()
            if trace_store is not None:
                await trace_store.close()
            if checkpoint_pool is not None:
                await checkpoint_pool.close()

    application = FastAPI(
        title="AI 기본법 근거 기반 QA API",
        version="0.2.0",
        description=(
            "AI 기본법을 Hybrid Search로 검색하고 법률 원문에 근거한 "
            "답변과 출처를 반환합니다."
        ),
        lifespan=lifespan,
    )
    if _env_flag("RAG_MCP_HTTP_ENABLED", True):
        mcp_server = build_http_server(
            application.state,
            trace_sink=lambda trace: _schedule_trace_write(application, trace),
        )
        application.router.routes.append(mcp_route(mcp_server))
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
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_trace_middleware(request: Request, call_next):
        """요청마다 RequestTrace를 열어 LLM·도구 호출을 모은다."""
        incoming = request.headers.get("x-request-id", "")
        trace = RequestTrace(endpoint=request.url.path)
        if _is_uuid(incoming):
            trace.request_id = incoming
        with trace_scope(trace):
            request.state.trace = trace
            try:
                response = await call_next(request)
            except Exception as error:
                trace.status = "error"
                trace.errors.append(type(error).__name__)
                raise
            else:
                if trace.status == "running":
                    trace.status = (
                        "ok" if response.status_code < 400 else f"http_{response.status_code}"
                    )
                response.headers["X-Request-ID"] = trace.request_id
                return response
            finally:
                trace.finish()
                if request.url.path in TRACED_PATHS:
                    _schedule_trace_write(request.app, trace)

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
        trace = get_current_trace() or RequestTrace(endpoint="/ask")
        try:
            result = await request.app.state.rag_graph.answer(
                payload.question,
                bypass_cache=payload.refresh,
                history=[item.model_dump() for item in payload.history],
                thread_id=payload.thread_id,
            )
        except ValueError as error:
            trace.status = "invalid_request"
            trace.errors.append(type(error).__name__)
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            trace.status = "error"
            trace.errors.append(type(error).__name__)
            raise HTTPException(
                status_code=502,
                detail=f"RAG 처리 중 오류가 발생했습니다: {error}",
            ) from error

        status = "insufficient_evidence" if not result.sources else "answered"
        trace.status = status
        trace.cache_hit = result.cache_hit
        return AskResponse(
            **result.as_dict(),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            status=status,
            request_id=trace.request_id,
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
