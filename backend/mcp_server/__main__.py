"""Run the MCP server over stdio: `uv run python -m mcp_server`.

Tool-call traces are saved to PostgreSQL (request_runs / tool_calls with
channel='mcp') when RAG_TRACE_STORE_ENABLED is on and the database is reachable.
Without a database the server still runs and only logs a warning.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from common.telemetry import RequestTrace
from common.trace_store import PostgresTraceStore, save_trace_safely
from mcp_server.server import build_server

logger = logging.getLogger(__name__)


class TraceStoreSink:
    """Opens the trace store in the server lifespan and saves each finished trace."""

    def __init__(self) -> None:
        self.store: PostgresTraceStore | None = None

    async def __call__(self, trace: RequestTrace) -> None:
        await save_trace_safely(self.store, trace)

    @asynccontextmanager
    async def lifespan(self, _server) -> AsyncIterator[None]:
        enabled = os.getenv("RAG_TRACE_STORE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        if enabled:
            from common.database import create_database_pool

            store = PostgresTraceStore(
                create_database_pool(),
                pipeline_version=os.getenv("RAG_CACHE_VERSION", "conditional-rerank-v10"),
            )
            try:
                await store.open()
            except Exception as error:
                logger.warning("MCP 호출 추적을 저장하지 않습니다(PostgreSQL 연결 실패): %s", error)
                await store.close()
            else:
                self.store = store
        try:
            yield
        finally:
            if self.store is not None:
                await self.store.close()
                self.store = None


def main() -> None:
    sink = TraceStoreSink()
    build_server(trace_sink=sink, lifespan=sink.lifespan).run("stdio")


if __name__ == "__main__":
    main()
