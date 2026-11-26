import unittest
from unittest.mock import patch

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import build_server
from rag.models import AnswerResult, Source
from tests.test_agentic_features import AgenticFakePipeline


class FakeAnswerer:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.questions = []

    async def answer(self, question):
        self.questions.append(question)
        source = Source("S1", "제33조", "제1항", "", "", "고영향 인공지능의 확인", "내용")
        return AnswerResult(
            answer="제33조에 따라 확인을 요청할 수 있습니다. [S1]",
            sources=[source],
            method="langgraph",
            retrieved_articles=["제33조"],
        )


class McpServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.created = 0

        def factory():
            self.created += 1
            return AgenticFakePipeline()

        self.answerers = []

        def answerer_factory(pipeline):
            answerer = FakeAnswerer(pipeline)
            self.answerers.append(answerer)
            return answerer

        self.server = build_server(factory, answerer_factory)

    async def test_lists_tools_without_loading_pipeline(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        self.assertEqual(set(tools), {"search_law", "get_article", "get_related_articles", "ask_law", "create_compliance_report"})
        schema = tools["search_law"].inputSchema
        self.assertEqual(schema["properties"]["top_k"]["maximum"], 20)
        self.assertEqual(self.created, 0)

    async def test_get_article_and_search(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            article = await client.call_tool("get_article", {"article_number": 33})
            search = await client.call_tool("search_law", {"query": "고영향 확인", "top_k": 3})
        self.assertFalse(article.isError)
        self.assertEqual(article.structuredContent["result"][0]["article"], "제33조")
        self.assertFalse(search.isError)
        self.assertEqual(self.created, 1)

    async def test_invalid_arguments_return_error(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            bad = await client.call_tool("get_article", {"article_number": 0})
            missing = await client.call_tool("get_article", {"article_number": 999})
        self.assertTrue(bad.isError)
        self.assertTrue(missing.isError)
        self.assertIn("제999조", missing.content[0].text)

    async def test_hidden_tools_are_not_registered(self):
        with (
            patch("mcp_server.server.allowed_tools", lambda: frozenset({"GetArticle"})),
            patch.dict("os.environ", {"RAG_MCP_ASK_ENABLED": "false", "RAG_MCP_COMPLIANCE_ENABLED": "false"}),
        ):
            server = build_server(AgenticFakePipeline)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
            unknown = await client.call_tool("search_law", {"query": "고영향"})
        self.assertEqual(names, ["get_article"])
        self.assertTrue(unknown.isError)

    async def test_tool_calls_are_traced_with_mcp_channel(self):
        traces = []
        server = build_server(AgenticFakePipeline, FakeAnswerer, trace_sink=traces.append)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            await client.call_tool("get_article", {"article_number": 33})
            await client.call_tool("get_article", {"article_number": 999})
            await client.call_tool("ask_law", {"question": "고영향 AI 확인 절차는?"})
        self.assertEqual(
            [(trace.endpoint, trace.status) for trace in traces],
            [("mcp:GetArticle", "ok"), ("mcp:GetArticle", "ok"), ("mcp:AskLaw", "ok")],
        )
        call = traces[0].tool_calls[0]
        self.assertEqual(call["channel"], "mcp")
        self.assertEqual(len(call["arguments_hash"]), 64)
        self.assertNotEqual(call["arguments_hash"], traces[1].tool_calls[0]["arguments_hash"])
        self.assertEqual(traces[2].tool_calls[0]["tool_name"], "AskLaw")
        self.assertIsNotNone(traces[0].ended_at)

    async def test_failed_tool_call_trace_has_error_status(self):
        traces = []

        def broken():
            raise RuntimeError("qdrant down")

        server = build_server(broken, FakeAnswerer, trace_sink=traces.append)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            result = await client.call_tool("search_law", {"query": "고영향"})
        self.assertTrue(result.isError)
        self.assertEqual(traces[0].status, "error")
        self.assertEqual(traces[0].errors, ["RuntimeError"])

    async def test_ask_law_returns_answer_with_sources(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            first = await client.call_tool("ask_law", {"question": "고영향 AI 확인 절차는?"})
            await client.call_tool("ask_law", {"question": "다시 질문"})
        self.assertFalse(first.isError)
        payload = first.structuredContent
        self.assertIn("[S1]", payload["answer"])
        self.assertEqual(payload["sources"][0]["article"], "제33조")
        self.assertEqual(len(self.answerers), 1)
        self.assertEqual(self.created, 1)

    async def test_resources_and_prompt(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            templates = (await client.list_resource_templates()).resourceTemplates
            resources = (await client.list_resources()).resources
            toc = await client.read_resource("law://ai-basic-act/toc")
            article = await client.read_resource("law://ai-basic-act/articles/33")
            prompts = (await client.list_prompts()).prompts
            prompt = await client.get_prompt(
                "compliance_check", {"service_description": "채용 서류 자동 평가 서비스"}
            )
        self.assertEqual(
            templates[0].uriTemplate, "law://ai-basic-act/articles/{article_number}"
        )
        self.assertIn("law://ai-basic-act/toc", [str(resource.uri) for resource in resources])
        self.assertIn("제33조", toc.contents[0].text)
        self.assertIn("제33조", article.contents[0].text)
        self.assertEqual([item.name for item in prompts], ["compliance_check"])
        self.assertIn("채용 서류 자동 평가 서비스", prompt.messages[0].content.text)

    async def test_missing_article_resource_is_error(self):
        from mcp.shared.exceptions import McpError

        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            with self.assertRaises(McpError):
                await client.read_resource("law://ai-basic-act/articles/999")


if __name__ == "__main__":
    unittest.main()
