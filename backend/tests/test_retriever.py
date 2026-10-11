import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rag.retriever import (
    HybridRetriever,
    apply_definition_metadata_ranking,
    is_definition_query,
    reciprocal_rank_fusion,
    tokenize,
)


class FakeEmbedding:
    calls = 0

    async def aembed_query(self, question):
        self.calls += 1
        return [1.0, 0.0]


class FakeQdrant:
    def __init__(self):
        self.query_filter = None
        self.payloads = [
            {
                "chunk_id": "a",
                "chunk_key": "a",
                "search_enabled": True,
                "article": "제33조",
                "title": "고영향 인공지능의 확인",
                "content": "고영향 인공지능 해당 여부를 확인한다.",
            },
            {
                "chunk_id": "b",
                "chunk_key": "b",
                "search_enabled": True,
                "article": "제2조",
                "title": "정의",
                "content": "고영향 인공지능이란 기본권에 중대한 영향을 미치는 시스템이다.",
            },
        ]

    def scroll(self, **kwargs):
        points = [
            SimpleNamespace(id=item["chunk_id"], payload=item)
            for item in self.payloads
        ]
        return points, None

    def query_points(self, **kwargs):
        self.query_filter = kwargs.get("query_filter")
        points = [
            SimpleNamespace(id="a", payload=self.payloads[0], score=0.6),
            SimpleNamespace(id="b", payload=self.payloads[1], score=0.59),
        ]
        return SimpleNamespace(points=points)


class RetrieverTest(unittest.TestCase):
    def test_tokenize(self):
        self.assertEqual(
            tokenize("고영향 인공지능이란 무엇인가요?"),
            ["고영향", "인공지능", "무엇"],
        )

    def test_rrf_combines_rankings(self):
        first = [{"chunk_id": "a"}, {"chunk_id": "b"}]
        second = [{"chunk_id": "b"}, {"chunk_id": "a"}]
        result = reciprocal_rank_fusion([first, second])
        self.assertEqual({item["chunk_id"] for item in result}, {"a", "b"})
        self.assertIn("rrf_score", result[0])

    def test_hybrid_search_and_embedding_cache(self):
        qdrant = FakeQdrant()
        embedding = FakeEmbedding()
        retriever = HybridRetriever(
            qdrant_client=qdrant,
            embedding_client=embedding,
            collection_name="test",
            top_k=2,
            candidate_k=2,
        )

        async def run():
            async def immediate(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch("rag.retriever.asyncio.to_thread", side_effect=immediate):
                first = await retriever.search("고영향 인공지능 정의")
                second = await retriever.search("고영향 인공지능 정의")
                return first, second

        first, second = asyncio.run(run())
        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)
        self.assertEqual(embedding.calls, 1)
        self.assertIsNotNone(qdrant.query_filter)

    def test_definition_query_detection_is_conditional(self):
        self.assertTrue(is_definition_query("고영향 인공지능이란 무엇인가요?"))
        self.assertTrue(is_definition_query("생성형 인공지능은 어떻게 정의되나요?"))
        self.assertFalse(is_definition_query("고영향 인공지능 확인 절차는 무엇인가요?"))

    def test_definition_metadata_ranking_promotes_definition(self):
        results = [
            {
                "chunk_id": "confirm",
                "title": "고영향 인공지능의 확인",
                "content": "해당 여부를 확인한다.",
            },
            {
                "chunk_id": "definition",
                "title": "정의",
                "chunk_role": "anchor",
                "content": "고영향 인공지능이란 시스템을 말한다.",
            },
        ]
        ranked = apply_definition_metadata_ranking(
            "고영향 인공지능이란 무엇인가요?",
            results,
        )
        self.assertEqual(ranked[0]["chunk_id"], "definition")


if __name__ == "__main__":
    unittest.main()
