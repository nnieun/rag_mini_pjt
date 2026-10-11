import asyncio
from types import SimpleNamespace
import unittest

from rag.pipeline import (
    ABSTENTION_PHRASE,
    RAGPipeline,
    extract_answerability,
    extract_related_source_ids,
    is_abstention,
    is_list_query,
    is_pure_abstention,
)


class FakeRetriever:
    method = "Hybrid(Dense+BM25+RRF)"
    top_k = 5
    candidate_k = 20

    def __init__(self):
        self.last_k = None
        self.chunks_by_key = {
            "parent-2": {
                "chunk_id": "parent-point",
                "chunk_key": "parent-2",
                "article": "제2조",
                "paragraph": "",
                "item": "",
                "subitem": "",
                "title": "정의",
                "content": "고영향 인공지능의 전체 정의",
            }
        }
        self.query_embedding_cache = {}
        self.client = SimpleNamespace(close=lambda: None)

    async def search(self, question, k=None):
        self.last_k = k
        return [
            {
                "chunk_id": "child-2-4",
                "parent_id": "parent-2",
                "article": "제2조",
                "content": "고영향 인공지능이란...",
            }
        ]

    @staticmethod
    def unique_articles(results):
        return ["제2조"]


class FakeLLM:
    async def ainvoke(self, messages):
        return SimpleNamespace(content="고영향 인공지능은 ... [S1]")


class AbstainingFakeLLM:
    async def ainvoke(self, messages):
        return SimpleNamespace(
            content="제공된 AI 기본법 근거에서는 확인할 수 없습니다."
        )


class QualifiedAnswerFakeLLM:
    async def ainvoke(self, messages):
        return SimpleNamespace(
            content=(
                "일부 내용은 확인할 수 없습니다. "
                "다만 관련 의무는 제2조에 규정되어 있습니다. [S1]"
            )
        )


class OutOfScopeAnswerFakeLLM:
    async def ainvoke(self, messages):
        return SimpleNamespace(
            content=(
                "[[ANSWERABLE:NO]]\n"
                "저녁에는 비빔밥을 추천합니다. [S1]\n"
                "AI 기본법에서는 확인할 수 없습니다."
            )
        )


class FakeReranker:
    def __init__(self):
        self.calls = 0
        self.warmup_calls = 0

    def rerank(self, question, candidates, k=5):
        self.calls += 1
        return candidates[:k]

    def warmup(self):
        self.warmup_calls += 1


class FakeAnswerCache:
    def __init__(self):
        self.value = None
        self.put_calls = 0

    async def get(self, question):
        if self.value is None:
            return None
        self.value.cache_hit = True
        return self.value

    async def put(self, question, result):
        self.put_calls += 1
        self.value = result


class PipelineTest(unittest.TestCase):
    def test_parent_expansion_and_answer(self):
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=FakeLLM(),
        )
        result = asyncio.run(pipeline.answer("고영향 인공지능이란?"))
        self.assertEqual(result.sources[0].article, "제2조")
        self.assertEqual(result.sources[0].content, "고영향 인공지능의 전체 정의")
        self.assertIn("[S1]", result.answer)

    def test_abstention_detection(self):
        self.assertTrue(
            is_abstention("제공된 AI 기본법 근거에서는 확인할 수 없습니다")
        )
        self.assertFalse(is_abstention("제2조에 따라 적용됩니다."))
        self.assertTrue(is_pure_abstention("확인할 수 없습니다."))
        self.assertFalse(
            is_pure_abstention("일부는 확인할 수 없습니다. 관련 조문입니다. [S1]")
        )

    def test_list_query_and_related_source_marker(self):
        self.assertTrue(is_list_query("사업자의 의무 관련 조문을 정리해줘"))
        self.assertFalse(is_list_query("고영향 인공지능이란 무엇인가요?"))

        source_ids, answer = extract_related_source_ids(
            "[[RELATED_SOURCES:S2,S4,S2]]\n관련 조문은 2개입니다."
        )

        self.assertEqual(source_ids, ["S2", "S4"])
        self.assertEqual(answer, "관련 조문은 2개입니다.")

    def test_answerability_marker(self):
        answerable, answer = extract_answerability(
            "[[ANSWERABLE:NO]]\n제공된 근거로 답할 수 없습니다."
        )
        self.assertFalse(answerable)
        self.assertEqual(answer, "제공된 근거로 답할 수 없습니다.")

    def test_abstention_answer_does_not_expose_sources(self):
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=AbstainingFakeLLM(),
        )

        result = asyncio.run(pipeline.answer("저녁 메뉴를 추천해줘"))

        self.assertEqual(result.sources, [])
        self.assertTrue(is_abstention(result.answer))

    def test_out_of_scope_marker_discards_generated_answer_and_sources(self):
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=OutOfScopeAnswerFakeLLM(),
        )

        result = asyncio.run(pipeline.answer("저녁 메뉴를 추천해줘"))

        self.assertEqual(result.answer, f"{ABSTENTION_PHRASE}.")
        self.assertEqual(result.sources, [])

    def test_answer_with_citation_keeps_sources(self):
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=QualifiedAnswerFakeLLM(),
        )

        result = asyncio.run(pipeline.answer("의무를 정리해줘"))

        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].article, "제2조")

    def test_conditional_reranking_only_for_definition_query(self):
        reranker = FakeReranker()
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=FakeLLM(),
            reranker=reranker,
            conditional_reranking=True,
            rerank_candidate_k=5,
        )

        definition = asyncio.run(pipeline.answer("고영향 인공지능이란 무엇인가요?"))
        self.assertEqual(pipeline.retriever.last_k, 5)

        general = asyncio.run(pipeline.answer("표시 의무를 알려주세요"))

        self.assertEqual(reranker.calls, 1)
        self.assertEqual(pipeline.retriever.last_k, None)
        self.assertEqual(
            definition.method,
            "Hybrid(Dense+BM25+RRF)+Reranking",
        )
        self.assertEqual(general.method, "Hybrid(Dense+BM25+RRF)")

        pipeline.preload_reranker()
        self.assertEqual(reranker.warmup_calls, 1)

    def test_completed_answer_is_reused_from_cache(self):
        cache = FakeAnswerCache()
        pipeline = RAGPipeline(
            retriever=FakeRetriever(),
            llm=FakeLLM(),
            answer_cache=cache,
        )

        first = asyncio.run(pipeline.answer("고영향 인공지능이란?"))
        self.assertFalse(first.cache_hit)
        second = asyncio.run(pipeline.answer("고영향 인공지능이란?"))
        refreshed = asyncio.run(
            pipeline.answer("고영향 인공지능이란?", bypass_cache=True)
        )

        self.assertEqual(cache.put_calls, 2)
        self.assertTrue(second.cache_hit)
        self.assertFalse(refreshed.cache_hit)
        self.assertEqual(first.answer, second.answer)


if __name__ == "__main__":
    unittest.main()
