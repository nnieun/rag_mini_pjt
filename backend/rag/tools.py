import re
from typing import Any

from rag.schemas import GetArticle, SearchLaw


ALLOWED_TOOLS = {"SearchLaw", "GetArticle"}


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


async def execute_tool(
    pipeline: Any,
    name: str,
    arguments: dict,
    *,
    use_reranking: bool = False,
) -> list[dict]:
    if name not in ALLOWED_TOOLS:
        raise ValueError(f"허용되지 않은 도구입니다: {name}")
    if name == "GetArticle":
        args = GetArticle.model_validate(arguments)
        return exact_article_results(pipeline.retriever, args.article_number)
    args = SearchLaw.model_validate(arguments)
    return await pipeline.retrieve(
        args.query,
        k=args.top_k,
        use_reranking=use_reranking,
    )
