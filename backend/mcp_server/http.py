"""Serve the MCP server over Streamable HTTP inside the FastAPI app, at /mcp.

The HTTP transport reuses the pipeline and LangGraph agent that the FastAPI
lifespan already loaded, so there is one Qdrant/BM25 index per process.

Settings (environment):
- RAG_MCP_HTTP_ENABLED: mount /mcp (default true)
- RAG_MCP_TOKEN: if set, requests need `Authorization: Bearer <token>`
- RAG_MCP_ALLOWED_HOSTS / RAG_MCP_ALLOWED_ORIGINS: comma-separated, for DNS
  rebinding protection. Defaults allow localhost only; "*" turns the check off.
"""

import hmac
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_server.server import TraceSink, build_server

MCP_PATH = "/mcp"
LOCAL_HOSTS = "127.0.0.1:*,localhost:*,[::1]:*"
LOCAL_ORIGINS = "http://127.0.0.1:*,http://localhost:*,http://[::1]:*"


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def transport_security_from_env() -> TransportSecuritySettings:
    hosts = _split(os.getenv("RAG_MCP_ALLOWED_HOSTS", LOCAL_HOSTS))
    origins = _split(os.getenv("RAG_MCP_ALLOWED_ORIGINS", LOCAL_ORIGINS))
    if hosts == ["*"]:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[] if origins == ["*"] else origins,
    )


class BearerTokenGuard:
    """Reject requests without the configured bearer token."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if not hmac.compare_digest(headers.get(b"authorization", b""), self.expected):
                response = JSONResponse({"detail": "MCP 인증 토큰이 필요합니다."}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_http_server(app_state: Any, trace_sink: TraceSink | None = None) -> FastMCP:
    """MCP server whose tools use the FastAPI app's pipeline and agent."""

    return build_server(
        lambda: app_state.pipeline,
        lambda _pipeline: app_state.rag_graph,
        trace_sink=trace_sink,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security_from_env(),
    )


def mcp_route(server: FastMCP) -> Route:
    """The /mcp route, ready to add to the FastAPI router.

    Adding the route itself (instead of mounting a sub-app) keeps the URL at /mcp
    without a trailing-slash redirect. The caller must run
    `server.session_manager.run()` in the app lifespan.
    """
    route = next(
        route for route in server.streamable_http_app().routes if getattr(route, "path", "") == MCP_PATH
    )
    token = os.getenv("RAG_MCP_TOKEN", "").strip()
    if not token:
        return route
    return Route(MCP_PATH, endpoint=BearerTokenGuard(route.app, token))
