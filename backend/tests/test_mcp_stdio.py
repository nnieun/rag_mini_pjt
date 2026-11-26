"""End-to-end check of the stdio transport in a real subprocess."""

import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_stdio_server.py"
BACKEND = Path(__file__).resolve().parents[1]


class McpStdioTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_lists_and_calls_tools(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(FIXTURE)],
            cwd=str(BACKEND),
            env={**os.environ, "RAG_ANSWER_CACHE_ENABLED": "false"},
        )
        with open(os.devnull, "w") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = {tool.name for tool in (await session.list_tools()).tools}
                    article = await session.call_tool("get_article", {"article_number": 33})
                    invalid = await session.call_tool("search_law", {"query": "x"})
                    hidden = await session.call_tool("create_pdf", {"title": "t"})
                    answer = await session.call_tool("ask_law", {"question": "고영향 AI 확인 절차는?"})
                    toc = await session.read_resource("law://ai-basic-act/toc")

        self.assertEqual(init.serverInfo.name, "ai-basic-act")
        self.assertIn("AI 기본법", init.instructions or "")
        self.assertEqual(tools, {"search_law", "get_article", "get_related_articles", "ask_law"})
        self.assertEqual(article.structuredContent["result"][0]["article"], "제33조")
        self.assertTrue(invalid.isError)  # query min_length=2
        self.assertTrue(hidden.isError)  # CreatePdf is not exposed over MCP
        self.assertFalse(answer.isError)
        self.assertIn("제33조", toc.contents[0].text)


if __name__ == "__main__":
    unittest.main()
