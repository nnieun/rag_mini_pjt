import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.tools import StructuredTool

from common.telemetry import RequestTrace, trace_scope
from rag.graph import LangGraphRAG
from rag.mcp_client import load_external_tools, load_server_config, tool_output_text
from tests.test_agentic_features import AgenticFakePipeline
from tests.test_tool_selection import FakeBoundLLM

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_stdio_server.py"
BACKEND = Path(__file__).resolve().parents[1]


def list_reports(directory: str = ".") -> str:
    """List generated report files."""
    return f"[FILE] report-1.pdf in {directory}"


class ServerConfigTest(unittest.TestCase):
    def test_missing_file_means_no_servers(self):
        self.assertEqual(load_server_config("/nonexistent/mcp_servers.json"), {})

    def test_reads_servers_object(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "servers.json"
            path.write_text('{"servers": {"fs": {"transport": "stdio", "command": "x"}}}')
            self.assertEqual(load_server_config(path)["fs"]["command"], "x")

    def test_default_config_is_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAG_MCP_SERVERS_CONFIG", None)
            self.assertEqual(load_server_config(), {})

    def test_output_text_flattens_content_blocks(self):
        blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        self.assertEqual(tool_output_text(blocks), "a\nb")
        self.assertEqual(tool_output_text((blocks, None)), "a\nb")


class ExternalToolLoadingTest(unittest.IsolatedAsyncioTestCase):
    async def test_failing_server_is_skipped_and_others_load(self):
        servers = {
            "law": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(FIXTURE)],
                "cwd": str(BACKEND),
            },
            "broken": {"transport": "stdio", "command": "/nonexistent/mcp-server", "args": []},
        }
        with self.assertLogs("rag.mcp_client", level="WARNING") as logs:
            tools = await load_external_tools(servers, timeout=30)
        names = {tool.name for tool in tools}
        self.assertEqual(names, {"law_search_law", "law_get_article", "law_get_related_articles", "law_ask_law"})
        self.assertTrue(any("broken" in line for line in logs.output))

        get_article = next(tool for tool in tools if tool.name == "law_get_article")
        output = tool_output_text(await get_article.ainvoke({"article_number": 33}))
        self.assertIn("제33조", output)

    async def test_no_servers_returns_empty_list(self):
        self.assertEqual(await load_external_tools({}), [])


class GraphExternalToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_llm_can_route_to_external_tool(self):
        tool = StructuredTool.from_function(list_reports, name="filesystem_list_directory")
        pipeline = AgenticFakePipeline()
        pipeline.llm = FakeBoundLLM(
            [{"name": "filesystem_list_directory", "args": {"directory": "reports"}}]
        )
        rag = LangGraphRAG(pipeline, external_tools=[tool])
        trace = RequestTrace(endpoint="/ask")
        with (
            patch.dict(os.environ, {"RAG_LLM_ANALYSIS_ENABLED": "false"}),
            trace_scope(trace),
        ):
            result = await rag.answer("생성된 보고서 파일 목록 보여줘")
        self.assertEqual(result.method, "ToolCalling(MCP:filesystem_list_directory)")
        self.assertIn("report-1.pdf in reports", result.answer)
        self.assertEqual(trace.tool_calls[0]["channel"], "mcp_client")
        self.assertEqual(trace.tool_calls[0]["tool_name"], "filesystem_list_directory")

    async def test_external_tool_failure_becomes_message(self):
        def explode(directory: str = ".") -> str:
            """Always fails."""
            raise RuntimeError("disk gone")

        tool = StructuredTool.from_function(explode, name="filesystem_list_directory")
        pipeline = AgenticFakePipeline()
        pipeline.llm = FakeBoundLLM([{"name": "filesystem_list_directory", "args": {}}])
        rag = LangGraphRAG(pipeline, external_tools=[tool])
        with patch.dict(os.environ, {"RAG_LLM_ANALYSIS_ENABLED": "false"}):
            result = await rag.answer("보고서 목록")
        self.assertIn("실행에 실패했습니다", result.answer)

    async def test_unknown_tools_without_external_tools_fall_back_to_search(self):
        pipeline = AgenticFakePipeline()
        pipeline.llm = FakeBoundLLM([{"name": "filesystem_list_directory", "args": {}}])
        rag = LangGraphRAG(pipeline)
        with patch.dict(os.environ, {"RAG_LLM_ANALYSIS_ENABLED": "false"}):
            result = await rag.answer("고영향 인공지능 확인")
        self.assertNotIn("MCP:", result.method)


if __name__ == "__main__":
    unittest.main()
