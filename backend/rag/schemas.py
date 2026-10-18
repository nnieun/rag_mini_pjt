from typing import Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "definition",
    "article_lookup",
    "obligation",
    "comparison",
    "summary",
    "general",
    "out_of_scope",
    "clarification",
]


class RequestAnalysis(BaseModel):
    intent: Intent = "general"
    law_name: str | None = "인공지능기본법"
    article_number: int | None = Field(default=None, ge=1)
    keywords: list[str] = Field(default_factory=list)
    target: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class ConversationHistoryItem(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    answer: str = Field(min_length=1, max_length=8000)
    source_articles: list[str] = Field(default_factory=list, max_length=30)


class FollowUpResolution(BaseModel):
    is_follow_up: bool
    standalone_query: str = Field(min_length=2, max_length=1200)


class SearchLaw(BaseModel):
    """Search the AI Basic Act for evidence relevant to a user question."""

    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class GetArticle(BaseModel):
    """Get one exact article from the indexed AI Basic Act."""

    article_number: int = Field(ge=1)


class CreatePdf(BaseModel):
    """Create a PDF report from the latest verified answer and its sources."""

    title: str = Field(default="AI 기본법 답변 보고서", min_length=1, max_length=150)
    include_sources: bool = True


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
