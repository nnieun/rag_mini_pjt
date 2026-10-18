import os
import re
import time
from typing import Any

from common.ai_model import get_embedding_model, get_llm_model
from common.qdrant import get_qdrant_client
from rag.models import AnswerResult, Source
from rag.reranker import QwenReranker
from rag.retriever import HybridRetriever, is_definition_query
from rag.retry import retry_rate_limit


ABSTENTION_PHRASE = "제공된 AI 기본법 근거에서는 확인할 수 없습니다"
ABSTENTION_MARKERS = (
    ABSTENTION_PHRASE,
    "확인할 수 없습니다",
    "규정되어 있지 않습니다",
    "명시되어 있지 않습니다",
    "근거가 없습니다",
)
LIST_QUERY_PATTERNS = (
    "관련 조문",
    "전체 조문",
    "모든 조문",
    "전부",
    "목록",
    "정리해",
    "정리하",
    "몇 개",
    "몇개",
    "어떤 조문",
)
RELATED_SOURCES_PATTERN = re.compile(
    r"\[\[RELATED_SOURCES:\s*([^\]]*)\]\]",
    re.IGNORECASE,
)
ANSWERABILITY_PATTERN = re.compile(
    r"\[\[ANSWERABLE:\s*(YES|NO)\s*\]\]",
    re.IGNORECASE,
)


class RAGPipeline:
    def __init__(
        self,
        *,
        retriever: HybridRetriever,
        llm: Any,
        reranker: QwenReranker | None = None,
        answer_cache: Any | None = None,
        conditional_reranking: bool = False,
        rerank_candidate_k: int | None = None,
        list_candidate_k: int = 20,
        max_retries: int = 3,
        retry_wait_seconds: int = 65,
    ):
        self.retriever = retriever
        self.llm = llm
        self.reranker = reranker
        self.answer_cache = answer_cache
        self.conditional_reranking = conditional_reranking
        self.rerank_candidate_k = (
            rerank_candidate_k or retriever.candidate_k
        )
        self.list_candidate_k = list_candidate_k
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds

    @classmethod
    def create_default(cls) -> "RAGPipeline":
        collection_name = os.getenv(
            "QDRANT_COLLECTION_NAME",
            "ai_basic_law_adaptive_anchor_v1",
        )
        max_retries = int(os.getenv("RAG_MAX_RETRIES", "3"))
        wait_seconds = int(os.getenv("RAG_RETRY_WAIT_SECONDS", "65"))
        retriever = HybridRetriever(
            qdrant_client=get_qdrant_client(),
            embedding_client=get_embedding_model(),
            collection_name=collection_name,
            top_k=int(os.getenv("RAG_TOP_K", "5")),
            candidate_k=int(os.getenv("RAG_CANDIDATE_K", "20")),
            rrf_k=int(os.getenv("RAG_RRF_K", "60")),
            max_retries=max_retries,
            retry_wait_seconds=wait_seconds,
        )
        return cls(
            retriever=retriever,
            llm=get_llm_model(max_tokens=1200),
            reranker=QwenReranker(
                max_length=int(os.getenv("RAG_RERANK_MAX_LENGTH", "512")),
                batch_size=int(os.getenv("RAG_RERANK_BATCH_SIZE", "5")),
            ),
            conditional_reranking=(
                os.getenv("RAG_CONDITIONAL_RERANK", "true").lower()
                in {"1", "true", "yes", "on"}
            ),
            rerank_candidate_k=int(
                os.getenv("RAG_RERANK_CANDIDATE_K", "5")
            ),
            list_candidate_k=int(os.getenv("RAG_LIST_CANDIDATE_K", "20")),
            max_retries=max_retries,
            retry_wait_seconds=wait_seconds,
        )

    async def retrieve(
        self,
        question: str,
        *,
        k: int | None = None,
        use_reranking: bool = False,
    ) -> list[dict]:
        should_rerank = self.should_rerank(question, use_reranking)
        if should_rerank:
            if self.reranker is None:
                self.reranker = QwenReranker()
            candidates = await self.retriever.search(
                question,
                k=self.rerank_candidate_k,
            )
            return self.reranker.rerank(
                question,
                candidates,
                k or self.retriever.top_k,
            )
        search_k = k
        if search_k is None and is_list_query(question):
            search_k = self.list_candidate_k
        return await self.retriever.search(question, k=search_k)

    def preload_reranker(self) -> None:
        if self.conditional_reranking:
            if self.reranker is None:
                self.reranker = QwenReranker()
            self.reranker.warmup()

    def should_rerank(self, question: str, force_reranking: bool = False) -> bool:
        return force_reranking or (
            self.conditional_reranking and is_definition_query(question)
        )

    def build_context(
        self,
        results: list[dict],
    ) -> tuple[str, list[Source]]:
        selected: list[tuple[dict, dict]] = []
        seen: set[str] = set()
        for result in results:
            parent_id = result.get("parent_id")
            document = self.retriever.chunks_by_key.get(
                str(parent_id), result
            )
            key = str(document.get("chunk_id") or document.get("chunk_key"))
            if key in seen:
                continue
            seen.add(key)
            selected.append((document, result))

        context_parts: list[str] = []
        sources: list[Source] = []
        for index, (document, matched_chunk) in enumerate(selected, start=1):
            source_id = f"S{index}"
            content = str(document["content"])
            location = " ".join(
                str(document.get(field) or "")
                for field in (
                    "article",
                    "paragraph",
                    "item",
                    "subitem",
                    "title",
                )
            ).strip()
            context_parts.append(f"[{source_id}] {location}\n{content}")
            sources.append(
                Source(
                    source_id=source_id,
                    article=str(document.get("article") or ""),
                    paragraph=str(document.get("paragraph") or ""),
                    item=str(document.get("item") or ""),
                    subitem=str(document.get("subitem") or ""),
                    title=str(document.get("title") or ""),
                    content=content,
                    highlight_text=(
                        str(matched_chunk.get("content") or "")
                        if str(matched_chunk.get("content") or "").strip()
                        != content.strip()
                        else ""
                    ),
                )
            )
        return "\n\n".join(context_parts), sources

    async def answer(
        self,
        question: str,
        *,
        use_reranking: bool = False,
        bypass_cache: bool = False,
        retrieved_results: list[dict] | None = None,
        cache_question: str | None = None,
    ) -> AnswerResult:
        question = question.strip()
        cache_key_question = (cache_question or question).strip()
        if len(question) < 2:
            raise ValueError("질문은 두 글자 이상이어야 합니다.")

        if self.answer_cache is not None and not bypass_cache:
            cached = await self.answer_cache.get(cache_key_question)
            if cached is not None:
                return cached

        processing_started = time.perf_counter()

        results = retrieved_results
        if results is None:
            results = await self.retrieve(
                question,
                use_reranking=use_reranking,
            )
        reranking_applied = self.should_rerank(question, use_reranking)
        if not results:
            return AnswerResult(
                answer=ABSTENTION_PHRASE,
                sources=[],
                method=self.retriever.method,
                retrieved_articles=[],
            )

        context, sources = self.build_context(results)
        list_query = is_list_query(question)
        list_instruction = ""
        if list_query:
            list_instruction = (
                " 이 질문은 조문 목록형 질문입니다. 제공된 근거를 모두 검토해 "
                "질문에 직접 관련된 출처 ID 전체를 첫 줄에 반드시 "
                "'[[RELATED_SOURCES:S1,S2]]' 형식으로 출력하세요. 관련 조문의 "
                "개수는 '현재 확장 검색에서 관련 조문 N개를 확인했습니다'라고 "
                "안내하고, 우선 관련도가 높은 5개만 설명한 뒤 나머지 조문을 "
                "더 볼 수 있다고 안내하세요. 관련성이 약한 조문은 "
                "RELATED_SOURCES에 포함하지 마세요."
            )
        messages = [
            (
                "system",
                "당신은 AI 기본법 안내자입니다. 제공된 법령 근거만 사용해 "
                "먼저 질문의 핵심 요청을 제공된 법령 근거만으로 직접 답할 "
                "수 있는지 판단하세요. 답할 수 있으면 첫 줄에 "
                "'[[ANSWERABLE:YES]]', 답할 수 없으면 첫 줄에 "
                "'[[ANSWERABLE:NO]]'를 출력하세요. 음식·날씨·여행·코딩 등 "
                "AI 기본법과 무관한 질문은 검색 결과에 단어가 일부 겹쳐도 "
                "반드시 NO입니다. NO인 경우 일반 지식으로 답하지 마세요. "
                "한국어로 답하세요. 각 핵심 주장 뒤에 [S1] 형식으로 출처를 "
                "표시하세요. 여러 의무나 관련 조문의 정리·요약을 요청받으면 "
                "검색된 관련 조문을 종합하여 답하세요. 관련 근거가 하나라도 "
                "있다면 거절 문구를 사용하지 마세요. 질문이 법률의 범위를 "
                "완전히 벗어나거나 질문받은 내용을 근거에서 전혀 확인할 수 "
                "없는 경우에만 다른 설명이나 인용을 덧붙이지 말고 정확히 '"
                f"{ABSTENTION_PHRASE}.' 한 문장만 출력하세요. 일부 내용만 "
                "확인할 수 있다면 확인 가능한 내용만 근거와 함께 답하고, "
                f"확인할 수 없는 내용을 추측하지 마세요.{list_instruction}",
            ),
            ("human", f"질문: {question}\n\n법령 근거:\n{context}"),
        ]
        response = await retry_rate_limit(
            lambda: self.llm.ainvoke(messages),
            label="LLM",
            max_retries=self.max_retries,
            wait_seconds=self.retry_wait_seconds,
        )
        answer = response.content
        usage = getattr(response, "usage_metadata", None) or {}
        if not isinstance(answer, str):
            answer = str(answer)
        answerable, answer = extract_answerability(answer)
        if answerable is False:
            answer = f"{ABSTENTION_PHRASE}."
            sources = []
        if list_query:
            related_ids, answer = extract_related_source_ids(answer)
            if not related_ids:
                related_ids = extract_cited_source_ids(answer)
            if related_ids:
                sources = filter_unique_sources(sources, related_ids)

        answer_sources = [] if is_pure_abstention(answer) else sources
        total_relevant = len(answer_sources)
        displayed_count = min(self.retriever.top_k, total_relevant)
        result = AnswerResult(
            answer=answer,
            sources=answer_sources,
            method=(
                f"{self.retriever.method}+Reranking"
                if reranking_applied
                else self.retriever.method
            ),
            retrieved_articles=self.retriever.unique_articles(results),
            processing_ms=round(
                (time.perf_counter() - processing_started) * 1000,
                2,
            ),
            total_relevant=total_relevant,
            displayed_count=displayed_count,
            has_more=total_relevant > displayed_count,
            model_usage={
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )
        if self.answer_cache is not None:
            await self.answer_cache.put(cache_key_question, result)
        return result

    def close(self) -> None:
        self.retriever.query_embedding_cache.clear()
        close = getattr(self.retriever.client, "close", None)
        if callable(close):
            close()


def is_abstention(answer: str) -> bool:
    normalized = " ".join(answer.split())
    return any(marker in normalized for marker in ABSTENTION_MARKERS)


def is_pure_abstention(answer: str) -> bool:
    """관련 조문을 실제로 인용하지 않은 거절 답변인지 판별합니다."""
    return is_abstention(answer) and re.search(r"\[S\d+\]", answer) is None


def is_list_query(question: str) -> bool:
    normalized = " ".join(question.split())
    return any(pattern in normalized for pattern in LIST_QUERY_PATTERNS)


def extract_cited_source_ids(answer: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\[(S\d+)\]", answer)))


def extract_related_source_ids(answer: str) -> tuple[list[str], str]:
    match = RELATED_SOURCES_PATTERN.search(answer)
    if match is None:
        return [], answer
    source_ids = list(dict.fromkeys(re.findall(r"S\d+", match.group(1))))
    cleaned = RELATED_SOURCES_PATTERN.sub("", answer, count=1).lstrip()
    return source_ids, cleaned


def extract_answerability(answer: str) -> tuple[bool | None, str]:
    """LLM의 답변 가능 여부 표식을 읽고 사용자 답변에서는 제거합니다."""
    match = ANSWERABILITY_PATTERN.search(answer)
    if match is None:
        return None, answer
    answerable = match.group(1).upper() == "YES"
    cleaned = ANSWERABILITY_PATTERN.sub("", answer, count=1).lstrip()
    return answerable, cleaned


def filter_unique_sources(
    sources: list[Source],
    source_ids: list[str],
) -> list[Source]:
    by_id = {source.source_id: source for source in sources}
    selected: list[Source] = []
    seen_articles: set[str] = set()
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None or source.article in seen_articles:
            continue
        seen_articles.add(source.article)
        selected.append(source)
    return selected
