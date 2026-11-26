"""Run the five plugin demo scenarios against an MCP server and print Markdown.

    # backend가 떠 있을 때 (/mcp, Streamable HTTP)
    uv run python scripts/mcp_demo.py --url http://localhost:8000/mcp > ../docs/PLUGIN_DEMO.result.md

    # stdio 서버를 직접 띄워서
    uv run python scripts/mcp_demo.py --stdio

Each scenario calls the MCP tools, resources and prompts the plugin's skills use,
so the output shows what Claude receives in those steps.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

BACKEND = Path(__file__).resolve().parents[1]

SCENARIOS = [
    ("조문 원문 조회", "tool", "get_article", {"article_number": 33}),
    ("키워드로 조문 검색", "tool", "search_law", {"query": "생성형 인공지능 결과물 표시 의무", "top_k": 3}),
    ("근거 있는 답변", "tool", "ask_law", {"question": "고영향 인공지능 사업자는 어떤 의무가 있나요?"}),
    ("목차 리소스", "resource", "law://ai-basic-act/toc", None),
    ("준수 점검 프롬프트", "prompt", "compliance_check", {"service_description": "이력서를 읽고 지원자 점수를 매기는 채용 보조 AI"}),
]


@asynccontextmanager
async def open_session(args):
    if args.stdio:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_server"], cwd=str(BACKEND), env=dict(os.environ)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                yield session
    else:
        import httpx

        headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
        timeout = httpx.Timeout(120.0)  # ask_law는 LLM 답변까지 기다린다
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
            async with streamable_http_client(args.url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    yield session


def shorten(text: str, limit: int = 1500) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…(생략)"


async def run(args) -> None:
    async with open_session(args) as session:
        init = await session.initialize()
        tools = [tool.name for tool in (await session.list_tools()).tools]
        print("# MCP 데모 실행 결과\n")
        print(f"- 서버: `{init.serverInfo.name}` {init.serverInfo.version}")
        print(f"- 연결: {'stdio' if args.stdio else args.url}")
        print(f"- 도구: {', '.join(f'`{name}`' for name in tools)}\n")
        for number, (title, kind, name, arguments) in enumerate(SCENARIOS, start=1):
            started = time.perf_counter()
            if kind == "tool":
                result = await session.call_tool(name, arguments)
                body = (
                    json.dumps(result.structuredContent, ensure_ascii=False, indent=2)
                    if result.structuredContent
                    else "\n".join(getattr(block, "text", "") for block in result.content)
                )
                status = "오류" if result.isError else "성공"
            elif kind == "resource":
                result = await session.read_resource(name)
                body = result.contents[0].text
                status = "성공"
            else:
                result = await session.get_prompt(name, arguments)
                body = result.messages[0].content.text
                status = "성공"
            elapsed = (time.perf_counter() - started) * 1000
            print(f"## {number}. {title}\n")
            call = f"{name}({json.dumps(arguments, ensure_ascii=False)})" if arguments else name
            print(f"- 호출: `{call}`")
            print(f"- 결과: {status}, {elapsed:.0f} ms\n")
            print("```text\n" + shorten(body) + "\n```\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("AI_BASIC_ACT_MCP_URL", "http://localhost:8000/mcp"))
    parser.add_argument("--token", default=os.getenv("AI_BASIC_ACT_MCP_TOKEN", ""))
    parser.add_argument("--stdio", action="store_true", help="python -m mcp_server를 직접 띄운다")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
