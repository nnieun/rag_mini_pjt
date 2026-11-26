"""Tool registry shared by the LangGraph agent and (later) the MCP server.

Each tool is a `ToolSpec`: a name, a Pydantic argument model (its docstring is the
tool description the LLM sees) and an async runner. Which tools are exposed is set
in `config/tools.json` (override the path with `RAG_TOOLS_CONFIG`), so adding or
hiding a tool never needs a code change in the graph.
"""

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from common.telemetry import tool_call_scope
from documents.pdf_report import create_answer_pdf
from rag.schemas import CreatePdf, GetArticle, SearchLaw


logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tools.json"


@dataclass
class ToolContext:
    pipeline: Any
    use_reranking: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[BaseModel]
    run: Callable[[ToolContext, Any], Awaitable[Any]]

    @property
    def description(self) -> str:
        return (self.args_model.__doc__ or "").strip()


def exact_article_results(retriever: Any, article_number: int) -> list[dict]:
    expected = f"제{article_number}조"
    results: list[dict] = []
    seen: set[str] = set()
    for chunk in retriever.chunks_by_key.values():
        article = re.sub(r"\s+", "", str(chunk.get("article") or ""))
        if article != expected:
            continue
        key = str(chunk.get("chunk_id") or chunk.get("chunk_key") or id(chunk))
        if key not in seen:
            seen.add(key)
            results.append(dict(chunk))
    return results


async def _search_law(context: ToolContext, args: SearchLaw) -> list[dict]:
    return await context.pipeline.retrieve(
        args.query, k=args.top_k, use_reranking=context.use_reranking
    )


async def _get_article(context: ToolContext, args: GetArticle) -> list[dict]:
    return exact_article_results(context.pipeline.retriever, args.article_number)


async def _create_pdf(context: ToolContext, args: CreatePdf) -> str:
    if not context.history:
        raise ValueError("PDF로 만들 이전 답변이 없습니다.")
    latest = context.history[-1]
    _, url = create_answer_pdf(
        title=args.title,
        question=str(latest.get("question", "")),
        answer=str(latest.get("answer", "")),
        source_articles=list(latest.get("source_articles", [])),
        include_sources=args.include_sources,
    )
    return url


REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec("SearchLaw", SearchLaw, _search_law),
        ToolSpec("GetArticle", GetArticle, _get_article),
        ToolSpec("CreatePdf", CreatePdf, _create_pdf),
    )
}


def load_allowed_tools(path: str | Path | None = None) -> frozenset[str]:
    """Read the allowlist. Unknown names are dropped with a warning."""
    config_path = Path(path or os.getenv("RAG_TOOLS_CONFIG") or DEFAULT_CONFIG_PATH)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    names = [str(name) for name in data.get("allowed", [])]
    unknown = [name for name in names if name not in REGISTRY]
    if unknown:
        logger.warning("등록되지 않은 도구는 무시합니다: %s", ", ".join(unknown))
    return frozenset(name for name in names if name in REGISTRY)


@lru_cache(maxsize=1)
def _default_allowed() -> frozenset[str]:
    return load_allowed_tools()


def allowed_tools() -> frozenset[str]:
    return _default_allowed()


def allowed_specs(allowed: frozenset[str] | None = None) -> list[ToolSpec]:
    names = allowed if allowed is not None else allowed_tools()
    return [spec for name, spec in REGISTRY.items() if name in names]


async def execute_tool(
    pipeline: Any,
    name: str,
    arguments: dict,
    *,
    use_reranking: bool = False,
    history: list[dict[str, Any]] | None = None,
    allowed: frozenset[str] | None = None,
    channel: str = "api",
) -> Any:
    """Validate the arguments against the tool's schema and run it.

    Raises ValueError for an unknown or disallowed tool and for invalid arguments
    (pydantic.ValidationError is a ValueError subclass).
    """
    async with tool_call_scope(name, channel=channel):
        names = allowed if allowed is not None else allowed_tools()
        spec = REGISTRY.get(name)
        if spec is None or name not in names:
            raise ValueError(f"허용되지 않은 도구입니다: {name}")
        args = spec.args_model.model_validate(arguments)
        context = ToolContext(pipeline, use_reranking, list(history or []))
        return await spec.run(context, args)
