"""MCP server for the AI Basic Act RAG tools.

The server is a thin adapter: every tool goes through `rag.tools.execute_tool`, so
argument validation, the allowlist in config/tools.json and tool-call tracing are
the same as in the HTTP API. The RAG pipeline (Qdrant + BM25 index) is loaded on
the first tool call, so MCP clients can list tools without waiting for it.
"""

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from common.telemetry import RequestTrace, trace_scope
from rag.tools import allowed_tools, execute_tool

SERVER_INSTRUCTIONS = (
    "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법(AI 기본법) 원문을 검색하는 도구다. "
    "답변에는 반드시 도구가 돌려준 조문만 인용하고, 조문에서 확인할 수 없는 내용은 추측하지 않는다."
)

CONTENT_LIMIT = 4000


class LazyPipeline:
    """Create the pipeline once, on first use, even under concurrent calls."""

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._pipeline: Any | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Any:
        if self._pipeline is None:
            async with self._lock:
                if self._pipeline is None:
                    self._pipeline = await asyncio.to_thread(self._factory)
        return self._pipeline


def format_article(document: dict) -> dict[str, str]:
    content = str(document.get("content") or "")
    return {
        "article": str(document.get("article") or ""),
        "paragraph": str(document.get("paragraph") or ""),
        "item": str(document.get("item") or ""),
        "title": str(document.get("title") or ""),
        "content": content[:CONTENT_LIMIT],
    }


async def run_traced(name: str, arguments: dict, pipeline: Any, **kwargs: Any) -> Any:
    with trace_scope(RequestTrace(endpoint=f"mcp:{name}")):
        return await execute_tool(pipeline, name, arguments, channel="mcp", **kwargs)


def build_server(pipeline_factory: Callable[[], Any] | None = None) -> FastMCP:
    if pipeline_factory is None:
        from rag.pipeline import RAGPipeline

        pipeline_factory = RAGPipeline.create_default
    pipeline = LazyPipeline(pipeline_factory)
    allowed = allowed_tools()
    server = FastMCP("ai-basic-act", instructions=SERVER_INSTRUCTIONS)

    if "SearchLaw" in allowed:

        @server.tool()
        async def search_law(
            query: Annotated[str, Field(min_length=2, max_length=1000, description="검색할 질문 또는 키워드")],
            top_k: Annotated[int, Field(ge=1, le=20, description="돌려받을 조문 수")] = 5,
        ) -> list[dict[str, str]]:
            """AI 기본법에서 질문과 관련된 조문을 Hybrid 검색(Dense+BM25+RRF)으로 찾는다."""
            results = await run_traced(
                "SearchLaw", {"query": query, "top_k": top_k}, await pipeline.get()
            )
            return [format_article(document) for document in results]

    if "GetArticle" in allowed:

        @server.tool()
        async def get_article(
            article_number: Annotated[int, Field(ge=1, description="조문 번호. 제33조라면 33")],
        ) -> list[dict[str, str]]:
            """AI 기본법의 특정 조문 원문을 조·항·호 단위로 그대로 가져온다."""
            results = await run_traced(
                "GetArticle", {"article_number": article_number}, await pipeline.get()
            )
            if not results:
                raise ValueError(f"제{article_number}조는 AI 기본법에 없습니다.")
            return [format_article(document) for document in results]

    server.pipeline = pipeline  # type: ignore[attr-defined]  # ask_law 등 다음 단계에서 재사용
    return server
