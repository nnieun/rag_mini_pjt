import os
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
        return await self.retriever.search(question, k=k)

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
        selected: list[dict] = []
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
            selected.append(document)

        context_parts: list[str] = []
        sources: list[Source] = []
        for index, document in enumerate(selected, start=1):
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
                )
            )
        return "\n\n".join(context_parts), sources

    async def answer(
        self,
        question: str,
        *,
        use_reranking: bool = False,
        bypass_cache: bool = False,
    ) -> AnswerResult:
        question = question.strip()
        if len(question) < 2:
            raise ValueError("질문은 두 글자 이상이어야 합니다.")

        if self.answer_cache is not None and not bypass_cache:
            cached = await self.answer_cache.get(question)
            if cached is not None:
                return cached

        processing_started = time.perf_counter()

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
        messages = [
            (
                "system",
                "당신은 AI 기본법 안내자입니다. 제공된 법령 근거만 사용해 "
                "한국어로 답하세요. 각 핵심 주장 뒤에 [S1] 형식으로 출처를 "
                "표시하세요. 질문이 법률의 범위를 벗어나거나, 금액·요건·절차 "
                "등 질문받은 구체적 내용이 근거에 없으면 반드시 '"
                f"{ABSTENTION_PHRASE}'라고 먼저 밝히세요. 관련 조문이 검색되어도 "
                "질문의 직접적인 답이 없으면 답을 추측하지 마세요.",
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
        if not isinstance(answer, str):
            answer = str(answer)
        result = AnswerResult(
            answer=answer,
            sources=sources,
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
        )
        if self.answer_cache is not None:
            await self.answer_cache.put(question, result)
        return result

    def close(self) -> None:
        self.retriever.query_embedding_cache.clear()
        close = getattr(self.retriever.client, "close", None)
        if callable(close):
            close()


def is_abstention(answer: str) -> bool:
    normalized = " ".join(answer.split())
    return any(marker in normalized for marker in ABSTENTION_MARKERS)
