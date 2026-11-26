import unittest
from types import SimpleNamespace

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import build_server
from rag.chunker import AdaptiveLawChunker
from rag.loader import LawXMLLoader
from rag.references import ReferenceGraph, attach_references, extract_references, reference_rows
from rag.tools import execute_tool
from tests.test_mcp_server import FakeAnswerer


def law_chunks():
    loader = LawXMLLoader("data/ai_basic_law/ai_basic_law.xml")
    root = loader.load()
    return AdaptiveLawChunker().chunk(root, loader.metadata(root))


class ExtractReferencesTest(unittest.TestCase):
    def test_external_laws_and_self_are_ignored(self):
        text = (
            "제36조(국내대리인 지정) 「에너지법」 제2조제1호에 따른 에너지, 「교통안전법」 제2조제1호부터 "
            "제3호까지, 제32조제2항에 따른 제출, 제33조제1항에 따른 요청, 제32조제2항 다시, 제36조 자기 자신"
        )
        self.assertEqual(
            extract_references(text, "제36조"),
            [{"article": "제32조", "paragraph": "제2항"}, {"article": "제33조", "paragraph": "제1항"}],
        )

    def test_branch_articles(self):
        self.assertEqual(extract_references("제12조의2에 따라", "제1조")[0]["article"], "제12조의2")


class ReferenceGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = law_chunks()
        cls.graph = ReferenceGraph(cls.chunks)

    def test_real_law_links(self):
        related = dict(self.graph.related("제36조"))
        self.assertEqual(related["제43조"], "cited_by")  # 과태료
        self.assertEqual(related["제34조"], "cites")
        self.assertEqual(self.graph.related("제2조"), [])  # 정의 조문은 다른 법률만 인용

    def test_attach_and_rows(self):
        chunks = attach_references([dict(chunk) for chunk in self.chunks])
        by_article = {c["article"]: c for c in chunks if c.get("article") == "제36조"}
        self.assertIn("제34조", by_article["제36조"]["references"])
        rows = reference_rows(self.chunks)
        self.assertIn(("제43조", "제36조"), {(row[0], row[1]) for row in rows})
        self.assertFalse(any(row[0] == row[1] for row in rows))


class RelatedArticlesToolTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        chunks = law_chunks()
        cls.pipeline = SimpleNamespace(
            retriever=SimpleNamespace(chunks_by_key={c["chunk_key"]: c for c in chunks}), llm=None
        )

    async def test_tool_returns_neighbour_chunks(self):
        documents = await execute_tool(
            self.pipeline, "GetRelatedArticles", {"article_number": 36, "direction": "in"}
        )
        self.assertEqual({d["article"] for d in documents}, {"제43조"})
        self.assertTrue(all(d["relation"] == "cited_by" for d in documents))

    async def test_mcp_tool(self):
        server = build_server(lambda: self.pipeline, FakeAnswerer)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            result = await client.call_tool("get_related_articles", {"article_number": 31})
        self.assertIn("get_related_articles", names)
        self.assertEqual(
            {(item["article"], item["relation"]) for item in result.structuredContent["result"]},
            {("제40조", "cited_by"), ("제43조", "cited_by")},
        )


if __name__ == "__main__":
    unittest.main()
