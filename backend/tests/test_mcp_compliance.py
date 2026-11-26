import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session

import documents.pdf_report as pdf_report
from agents.compliance_graph import ComplianceAgent
from agents.compliance_report import report_on_completion
from agents.compliance_runs import ComplianceService, InMemoryComplianceRunStore
from app.main import create_app
from mcp_server.server import build_server
from tests.test_compliance_api import ENV, assessment, make_pipeline_class
from tests.test_compliance_graph import HIRING
from tests.test_mcp_server import FakeAnswerer


def server_for(value, base_url="https://law.example.com"):
    pipeline_class = make_pipeline_class(value)

    def factory(pipeline):
        agent = ComplianceAgent(pipeline)
        return ComplianceService(agent, InMemoryComplianceRunStore(), on_finished=report_on_completion(agent))

    return build_server(pipeline_class, FakeAnswerer, compliance_factory=factory, public_base_url=base_url)


class McpComplianceToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(pdf_report, "REPORT_DIR", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def call(self, server, description=HIRING):
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            return await client.call_tool("create_compliance_report", {"service_description": description})

    async def test_completed_run_returns_pdf_link(self):
        result = await self.call(server_for(assessment("no")))
        payload = result.structuredContent
        self.assertFalse(result.isError)
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["report_url"].startswith("https://law.example.com/reports/compliance-report-"))
        self.assertEqual(payload["applicable_obligations"][0]["article"], "제33조제1항")

    async def test_high_impact_run_waits_for_human(self):
        payload = (await self.call(server_for(assessment("yes")))).structuredContent
        self.assertEqual(payload["status"], "awaiting_approval")
        self.assertIsNone(payload["report_url"])
        self.assertEqual(payload["review_reasons"], ["고영향 인공지능 해당"])
        self.assertIn(f"/review {payload['run_id']}", payload["message"])

    async def test_short_description_is_rejected(self):
        self.assertTrue((await self.call(server_for(assessment("no")), "짧음")).isError)

    async def test_disabled_flag_hides_tool(self):
        with patch.dict(os.environ, {"RAG_MCP_COMPLIANCE_ENABLED": "false"}):
            server = server_for(assessment("no"))
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
        self.assertNotIn("create_compliance_report", names)


class McpHttpComplianceTest(unittest.IsolatedAsyncioTestCase):
    async def test_http_tool_uses_app_service(self):
        env = {**ENV, "RAG_MCP_ALLOWED_HOSTS": "testserver", "RAG_MCP_ALLOWED_ORIGINS": "*"}
        with TemporaryDirectory() as directory, patch.dict(os.environ, env), patch.object(
            pdf_report, "REPORT_DIR", Path(directory)
        ):
            app = create_app(make_pipeline_class(assessment("yes")))
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                    async with streamable_http_client("http://testserver/mcp", http_client=http) as (r, w, _):
                        async with ClientSession(r, w) as session:
                            await session.initialize()
                            result = await session.call_tool("create_compliance_report", {"service_description": HIRING})
                    run_id = result.structuredContent["run_id"]
                    # MCP로 시작한 실행이 앱 API에 그대로 보이고, 승인하면 PDF가 생긴다.
                    seen = (await http.get(f"/agents/compliance/runs/{run_id}")).json()
                    approved = (await http.post(f"/agents/compliance/runs/{run_id}/approve", json={"approved": True})).json()
        self.assertEqual(seen["source_type"], "mcp")
        self.assertEqual(seen["status"], "awaiting_approval")
        self.assertTrue(approved["report_url"].startswith("/reports/compliance-report-"))


if __name__ == "__main__":
    unittest.main()
