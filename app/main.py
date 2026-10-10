import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from rag.pipeline import RAGPipeline


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


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
        app.state.pipeline = pipeline
        yield
        pipeline.close()

    application = FastAPI(
        title="AI 기본법 근거 기반 QA API",
        version="0.2.0",
        description=(
            "AI 기본법을 Hybrid Search로 검색하고 법률 원문에 근거한 "
            "답변과 출처를 반환합니다."
        ),
        lifespan=lifespan,
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
            result = await pipeline.answer(payload.question)
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
