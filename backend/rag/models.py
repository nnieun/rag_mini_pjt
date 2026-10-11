from dataclasses import dataclass, field
from typing import Any


@dataclass
class LawNode:
    level: str
    own: str
    no: str | None = None
    branch: str | None = None
    children: list["LawNode"] = field(default_factory=list)


@dataclass
class RetrievedDocument:
    chunk_id: str
    content: str
    payload: dict[str, Any]
    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.payload,
            "chunk_id": self.chunk_id,
            "content": self.content,
            "dense_score": self.dense_score,
            "bm25_score": self.bm25_score,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
        }


@dataclass
class Source:
    source_id: str
    article: str
    paragraph: str
    item: str
    subitem: str
    title: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "article": self.article,
            "paragraph": self.paragraph,
            "item": self.item,
            "subitem": self.subitem,
            "title": self.title,
            "content": self.content,
        }


@dataclass
class AnswerResult:
    answer: str
    sources: list[Source]
    method: str
    retrieved_articles: list[str]
    cache_hit: bool = False
    processing_ms: float = 0.0
    total_relevant: int = 0
    displayed_count: int = 0
    has_more: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": [source.as_dict() for source in self.sources],
            "method": self.method,
            "retrieved_articles": self.retrieved_articles,
            "cache_hit": self.cache_hit,
            "processing_ms": self.processing_ms,
            "total_relevant": self.total_relevant,
            "displayed_count": self.displayed_count,
            "has_more": self.has_more,
        }
