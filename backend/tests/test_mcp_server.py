import unittest
from unittest.mock import patch

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import build_server
from tests.test_agentic_features import AgenticFakePipeline



class McpServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.created = 0

        def factory():
            self.created += 1
            return AgenticFakePipeline()

        self.server = build_server(factory)

    async def test_lists_tools_without_loading_pipeline(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        self.assertEqual(set(tools), {"search_law", "get_article"})
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
        with patch("mcp_server.server.allowed_tools", lambda: frozenset({"GetArticle"})):
            server = build_server(AgenticFakePipeline)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
            unknown = await client.call_tool("search_law", {"query": "고영향"})
        self.assertEqual(names, ["get_article"])
        self.assertTrue(unknown.isError)

    async def test_tool_call_is_traced_with_mcp_channel(self):
        from mcp_server import server as module

        captured = []
        original = module.trace_scope

        def capture(trace):
            captured.append(trace)
            return original(trace)

        with patch.object(module, "trace_scope", capture):
            async with create_connected_server_and_client_session(self.server._mcp_server) as client:
                await client.call_tool("get_article", {"article_number": 33})
        self.assertEqual(captured[0].tool_calls[0]["channel"], "mcp")
        self.assertEqual(captured[0].endpoint, "mcp:GetArticle")


if __name__ == "__main__":
    unittest.main()
