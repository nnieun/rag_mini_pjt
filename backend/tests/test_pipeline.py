import asyncio
from types import SimpleNamespace
import unittest

from rag.pipeline import RAGPipeline, is_abstention


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
