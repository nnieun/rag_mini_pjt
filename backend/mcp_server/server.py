"""MCP server for the AI Basic Act RAG tools.

The server is a thin adapter: every tool goes through `rag.tools.execute_tool`, so
argument validation, the allowlist in config/tools.json and tool-call tracing are
the same as in the HTTP API. The RAG pipeline (Qdrant + BM25 index) is loaded on
the first tool call, so MCP clients can list tools without waiting for it.
"""

import asyncio
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from common.telemetry import RequestTrace, tool_call_scope, trace_scope
from rag.tools import allowed_tools, exact_article_results, execute_tool

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


COMPLIANCE_PROMPT = """다음 AI 서비스가 AI 기본법상 어떤 의무를 지는지 점검해줘.

서비스 설명:
{service_description}

진행 순서:
1. search_law로 고영향 인공지능, 생성형 인공지능, 투명성 확보, 안전성 확보, 사업자 책무 관련 조문을 찾는다.
2. 해당할 수 있는 조문은 get_article로 원문을 확인한다.
3. 아래 형식으로 정리한다. 원문에서 확인한 조문만 인용하고, 근거가 없으면 "법령에서 확인되지 않음"이라고 쓴다.

| 의무 | 해당 여부 | 근거 조문 | 해야 할 일 |
|---|---|---|---|

마지막에 이 점검은 법률 자문이 아니라는 문장을 덧붙인다."""


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _article_number(article: str) -> int | None:
    match = re.fullmatch(r"제(\d+)조(?:의\d+)?", re.sub(r"\s+", "", article))
    return int(match.group(1)) if match else None


def table_of_contents(retriever: Any) -> str:
    """조문 번호와 제목 목록. 같은 조의 항·호 청크는 한 줄로 합친다."""
    titles: dict[str, str] = {}
    for chunk in retriever.chunks_by_key.values():
        article = re.sub(r"\s+", "", str(chunk.get("article") or ""))
        if article and article not in titles:
            titles[article] = str(chunk.get("title") or "")

    def order(article: str) -> tuple[int, str]:
        number = _article_number(article)
        return (number if number is not None else 10**6, article)

    lines = [f"{article} {titles[article]}".rstrip() for article in sorted(titles, key=order)]
    return "\n".join(lines)


def article_text(documents: list[dict]) -> str:
    parts = []
    for document in documents:
        label = " ".join(
            str(document.get(key) or "") for key in ("article", "paragraph", "item")
        ).strip()
        parts.append(f"[{label}] {document.get('content') or ''}".strip())
    return "\n".join(parts)


def format_answer(result: Any) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "sources": [
            {
                "source_id": source.source_id,
                "article": source.article,
                "paragraph": source.paragraph,
                "item": source.item,
                "title": source.title,
            }
            for source in result.sources
        ],
        "method": result.method,
        "cache_hit": result.cache_hit,
    }


def format_article(document: dict) -> dict[str, str]:
    content = str(document.get("content") or "")
    return {
        "article": str(document.get("article") or ""),
        "paragraph": str(document.get("paragraph") or ""),
        "item": str(document.get("item") or ""),
        "title": str(document.get("title") or ""),
        "content": content[:CONTENT_LIMIT],
    }


TraceSink = Callable[[RequestTrace], Awaitable[None] | None]


@asynccontextmanager
async def mcp_trace(name: str, sink: TraceSink | None) -> AsyncIterator[RequestTrace]:
    """One RequestTrace per MCP tool call, handed to `sink` when the call ends."""
    trace = RequestTrace(endpoint=f"mcp:{name}")
    with trace_scope(trace):
        try:
            yield trace
        except Exception as error:
            trace.status = "error"
            trace.errors.append(type(error).__name__)
            raise
        else:
            trace.status = "ok"
        finally:
            trace.finish()
            if sink is not None:
                pending = sink(trace)
                if pending is not None:
                    await pending


def build_server(
    pipeline_factory: Callable[[], Any] | None = None,
    answerer_factory: Callable[[Any], Any] | None = None,
    *,
    trace_sink: TraceSink | None = None,
    **settings: Any,
) -> FastMCP:
    """Build the MCP server.

    `answerer_factory(pipeline)` must return an object with
    `async answer(question) -> AnswerResult`; by default it is `LangGraphRAG`.
    `trace_sink(trace)` receives every finished tool-call trace (for example to save it
    in PostgreSQL); it may be sync or async and must not raise.
    Extra keyword arguments go to `FastMCP` (for example the HTTP transport settings).
    """
    if pipeline_factory is None:
        from rag.pipeline import RAGPipeline

        pipeline_factory = RAGPipeline.create_default
    if answerer_factory is None:

        def answerer_factory(loaded: Any) -> Any:
            from rag.graph import LangGraphRAG

            return LangGraphRAG(loaded)

    pipeline = LazyPipeline(pipeline_factory)
    answerer_lock = asyncio.Lock()
    answerer_box: dict[str, Any] = {}

    async def get_answerer() -> Any:
        if "value" not in answerer_box:
            async with answerer_lock:
                if "value" not in answerer_box:
                    answerer_box["value"] = answerer_factory(await pipeline.get())
        return answerer_box["value"]

    async def run_traced(name: str, arguments: dict) -> Any:
        async with mcp_trace(name, trace_sink):
            return await execute_tool(await pipeline.get(), name, arguments, channel="mcp")

    allowed = allowed_tools()
    server = FastMCP("ai-basic-act", instructions=SERVER_INSTRUCTIONS, **settings)

    if "SearchLaw" in allowed:

        @server.tool()
        async def search_law(
            query: Annotated[str, Field(min_length=2, max_length=1000, description="검색할 질문 또는 키워드")],
            top_k: Annotated[int, Field(ge=1, le=20, description="돌려받을 조문 수")] = 5,
        ) -> list[dict[str, str]]:
            """AI 기본법에서 질문과 관련된 조문을 Hybrid 검색(Dense+BM25+RRF)으로 찾는다."""
            results = await run_traced("SearchLaw", {"query": query, "top_k": top_k})
            return [format_article(document) for document in results]

    if "GetArticle" in allowed:

        @server.tool()
        async def get_article(
            article_number: Annotated[int, Field(ge=1, description="조문 번호. 제33조라면 33")],
        ) -> list[dict[str, str]]:
            """AI 기본법의 특정 조문 원문을 조·항·호 단위로 그대로 가져온다."""
            results = await run_traced("GetArticle", {"article_number": article_number})
            if not results:
                raise ValueError(f"제{article_number}조는 AI 기본법에 없습니다.")
            return [format_article(document) for document in results]

    if "GetRelatedArticles" in allowed:

        @server.tool()
        async def get_related_articles(
            article_number: Annotated[int, Field(ge=1, description="기준 조문 번호")],
            direction: Annotated[
                Literal["both", "out", "in"],
                Field(description="out: 이 조문이 인용하는 조문, in: 이 조문을 인용하는 조문"),
            ] = "both",
        ) -> list[dict[str, str]]:
            """AI 기본법에서 특정 조문과 인용 관계로 이어진 조문(1단계)을 가져온다. 의무 조문의 과태료·위임 조문을 찾을 때 쓴다."""
            results = await run_traced(
                "GetRelatedArticles", {"article_number": article_number, "direction": direction}
            )
            return [
                {**format_article(document), "relation": str(document.get("relation") or "")}
                for document in results
            ]

    if _env_flag("RAG_MCP_ASK_ENABLED", True):

        @server.tool()
        async def ask_law(
            question: Annotated[str, Field(min_length=2, max_length=1000, description="AI 기본법에 대한 질문")],
        ) -> dict[str, Any]:
            """AI 기본법 RAG 에이전트에게 질문하고, 근거 조문이 붙은 답변을 받는다."""
            async with mcp_trace("AskLaw", trace_sink):
                async with tool_call_scope("AskLaw", channel="mcp", arguments={"question": question}):
                    result = await (await get_answerer()).answer(question)
            return format_answer(result)

    @server.resource(
        "law://ai-basic-act/toc",
        name="toc",
        description="AI 기본법 조문 목차 (조 번호와 제목)",
        mime_type="text/plain",
    )
    async def toc() -> str:
        return table_of_contents((await pipeline.get()).retriever)

    @server.resource(
        "law://ai-basic-act/articles/{article_number}",
        name="article",
        description="AI 기본법 특정 조문 원문",
        mime_type="text/plain",
    )
    async def article(article_number: str) -> str:
        if not article_number.isdigit():
            raise ValueError("조문 번호는 숫자여야 합니다.")
        documents = exact_article_results((await pipeline.get()).retriever, int(article_number))
        if not documents:
            raise ValueError(f"제{article_number}조는 AI 기본법에 없습니다.")
        return article_text(documents)

    @server.prompt(
        name="compliance_check",
        description="AI 서비스 설명을 받아 AI 기본법상 의무를 점검하는 프롬프트",
    )
    def compliance_check(service_description: str) -> str:
        return COMPLIANCE_PROMPT.format(service_description=service_description)

    server.pipeline = pipeline  # type: ignore[attr-defined]
    return server
