import os
import unittest
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.main import create_app
from tests.test_agentic_features import AgenticFakePipeline

BASE_ENV = {
    "RAG_ANSWER_CACHE_ENABLED": "false",
    "RAG_RERANK_PRELOAD": "false",
    "RAG_CHECKPOINT_ENABLED": "false",
    "RAG_TRACE_STORE_ENABLED": "false",
    "RAG_MCP_ALLOWED_HOSTS": "testserver",
    "RAG_MCP_ALLOWED_ORIGINS": "*",
}


class ClosablePipeline(AgenticFakePipeline):
    created = 0

    def __init__(self):
        super().__init__()
        type(self).created += 1

    def close(self):
        pass


class McpHttpTest(unittest.IsolatedAsyncioTestCase):
    async def run_client(self, app, headers=None):
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", headers=headers or {}
            ) as http_client:
                async with streamable_http_client(
                    "http://testserver/mcp", http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        article = await session.call_tool("get_article", {"article_number": 33})
                        return tools, article

    async def test_streamable_http_reuses_app_pipeline(self):
        ClosablePipeline.created = 0
        with patch.dict(os.environ, BASE_ENV):
            app = create_app(ClosablePipeline)
            tools, article = await self.run_client(app)
        names = {tool.name for tool in tools.tools}
        self.assertIn("get_article", names)
        self.assertFalse(article.isError)
        self.assertEqual(article.structuredContent["result"][0]["article"], "제33조")
        self.assertEqual(ClosablePipeline.created, 1)

    async def test_mcp_calls_are_saved_through_app_trace_store(self):
        import asyncio

        saved = []

        class RecordingStore:
            async def save(self, trace):
                saved.append(trace)

        with patch.dict(os.environ, BASE_ENV):
            app = create_app(ClosablePipeline)
            original = app.router.lifespan_context

            def lifespan_with_store(application):
                class Ctx:
                    async def __aenter__(self_inner):
                        self_inner.inner = original(application)
                        await self_inner.inner.__aenter__()
                        application.state.trace_store = RecordingStore()

                    async def __aexit__(self_inner, *exc):
                        await asyncio.gather(*application.state.pending_trace_writes)
                        return await self_inner.inner.__aexit__(*exc)

                return Ctx()

            app.router.lifespan_context = lifespan_with_store
            await self.run_client(app)
        self.assertEqual([trace.endpoint for trace in saved], ["mcp:GetArticle"])
        self.assertEqual(saved[0].tool_calls[0]["channel"], "mcp")

    async def test_token_is_required_when_configured(self):
        env = {**BASE_ENV, "RAG_MCP_TOKEN": "secret"}
        with patch.dict(os.environ, env):
            app = create_app(ClosablePipeline)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    denied = await client.post("/mcp", json={})
            # 세션 매니저는 lifespan마다 새로 만들어야 하므로 앱을 다시 만든다.
            _, article = await self.run_client(
                create_app(ClosablePipeline), headers={"Authorization": "Bearer secret"}
            )
        self.assertEqual(denied.status_code, 401)
        self.assertFalse(article.isError)

    async def test_unknown_host_is_rejected(self):
        env = {**BASE_ENV, "RAG_MCP_ALLOWED_HOSTS": "localhost:*"}
        with patch.dict(os.environ, env):
            app = create_app(ClosablePipeline)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.post(
                        "/mcp",
                        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                        headers={"Accept": "application/json, text/event-stream"},
                    )
        self.assertEqual(response.status_code, 421)

    def test_disabled_flag_removes_route(self):
        with patch.dict(os.environ, {**BASE_ENV, "RAG_MCP_HTTP_ENABLED": "false"}):
            app = create_app(ClosablePipeline)
        self.assertNotIn("/mcp", [getattr(route, "path", "") for route in app.routes])


if __name__ == "__main__":
    unittest.main()
