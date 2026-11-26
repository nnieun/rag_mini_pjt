"""External MCP servers as extra agent tools (langchain-mcp-adapters).

`config/mcp_servers.json` (override with `RAG_MCP_SERVERS_CONFIG`) lists servers
in the MultiServerMCPClient connection format:

    {"servers": {"filesystem": {"transport": "stdio", "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-filesystem", "./generated_reports"]}}}

Each server is loaded separately: a server that fails to start or list its tools is
skipped with a warning, and the other servers' tools stay available. Tool names get
the server name as a prefix (`filesystem_list_directory`) so they cannot collide
with the built-in tools.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from common.telemetry import tool_call_scope

logger = logging.getLogger(__name__)

DEFAULT_SERVERS_PATH = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.json"
OUTPUT_LIMIT = 8000
CONNECT_TIMEOUT_SECONDS = 20.0


def load_server_config(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    config_path = Path(path or os.getenv("RAG_MCP_SERVERS_CONFIG") or DEFAULT_SERVERS_PATH)
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    servers = data.get("servers") or {}
    if not isinstance(servers, dict):
        raise ValueError(f"{config_path}: 'servers'는 이름별 연결 설정 객체여야 합니다.")
    return {str(name): dict(connection) for name, connection in servers.items()}


async def _load_one(client: Any, name: str, timeout: float) -> list[BaseTool]:
    try:
        return await asyncio.wait_for(client.get_tools(server_name=name), timeout=timeout)
    except Exception as error:  # 연결 실패·타임아웃·목록 오류 모두 해당 서버만 제외
        logger.warning("외부 MCP 서버 '%s'를 사용할 수 없어 제외합니다: %s", name, error)
        return []


async def load_external_tools(
    servers: dict[str, dict[str, Any]] | None = None,
    *,
    client_factory: Any = None,
    timeout: float = CONNECT_TIMEOUT_SECONDS,
) -> list[BaseTool]:
    """Load tools from every configured server, skipping the ones that fail."""
    servers = load_server_config() if servers is None else servers
    if not servers:
        return []
    if client_factory is None:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        def client_factory(connections):
            return MultiServerMCPClient(connections, tool_name_prefix=True)

    client = client_factory(servers)
    results = await asyncio.gather(*(_load_one(client, name, timeout) for name in servers))
    tools = [tool for group in results for tool in group]
    if tools:
        logger.info("외부 MCP 도구 %d개를 불러왔습니다: %s", len(tools), ", ".join(t.name for t in tools))
    return tools


def tool_output_text(output: Any) -> str:
    """Flatten a tool result (str, content blocks or (content, artifact)) into text."""
    if isinstance(output, tuple) and len(output) == 2:
        output = output[0]
    if isinstance(output, str):
        text = output
    elif isinstance(output, list):
        parts = []
        for block in output:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(getattr(block, "text", block)))
        text = "\n".join(part for part in parts if part)
    else:
        text = str(getattr(output, "content", output))
    return text[:OUTPUT_LIMIT]


async def run_external_tool(tool: BaseTool, arguments: dict[str, Any]) -> str:
    """Call an external MCP tool, recorded as a tool call with channel 'mcp_client'."""
    async with tool_call_scope(tool.name, channel="mcp_client", arguments=arguments):
        return tool_output_text(await tool.ainvoke(arguments))
