import asyncio
from types import SimpleNamespace
import unittest

from rag.pipeline import RAGPipeline, is_abstention


class FakeRetriever:
    method = "Hybrid(Dense+BM25+RRF)"
    top_k = 5
    candidate_k = 20

    def __init__(self):
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


if __name__ == "__main__":
    unittest.main()
