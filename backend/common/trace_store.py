"""Persist a finished RequestTrace into request_runs, model_calls and tool_calls.

Tables are defined in docker/postgres-init/003_observability.sql and
004_tool_calls_channel.sql. `open()` applies the same idempotent DDL so an existing
database volume picks them up too.
"""

import logging
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from common.telemetry import RequestTrace


logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docker" / "postgres-init"
SCHEMA_FILES = ("003_observability.sql", "004_tool_calls_channel.sql")

INSERT_RUN = """
INSERT INTO request_runs (
    request_id, pipeline_version, endpoint, status, cache_hit, elapsed_ms, error_code
) VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (request_id) DO NOTHING
RETURNING id
"""

INSERT_MODEL_CALL = """
INSERT INTO model_calls (
    request_run_id, purpose, model_name, input_tokens, output_tokens,
    total_tokens, elapsed_ms, error_code
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

INSERT_TOOL_CALL = """
INSERT INTO tool_calls (
    request_run_id, tool_name, channel, arguments_hash, status, elapsed_ms, error_code
) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def schema_sql() -> str:
    sql = "\n".join((SCHEMA_DIR / name).read_text(encoding="utf-8") for name in SCHEMA_FILES)
    # 파일의 BEGIN/COMMIT은 초기화 스크립트용이다. 여기서는 연결의 트랜잭션을 쓴다.
    return sql.replace("BEGIN;", "").replace("COMMIT;", "")


class PostgresTraceStore:
    def __init__(self, pool: AsyncConnectionPool, *, pipeline_version: str):
        self.pool = pool
        self.pipeline_version = pipeline_version

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=5.0)
        async with self.pool.connection() as connection:
            await connection.execute(schema_sql())
            await connection.commit()

    async def close(self) -> None:
        await self.pool.close()

    async def save(self, trace: RequestTrace) -> None:
        """Write one request and its calls in a single transaction."""
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                INSERT_RUN,
                (
                    trace.request_id,
                    self.pipeline_version,
                    (trace.endpoint or None) and trace.endpoint[:100],
                    trace.status[:30],
                    trace.cache_hit,
                    trace.elapsed_ms,
                    (trace.errors[0] if trace.errors else None),
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                # 같은 request_id가 이미 저장됨(재시도된 요청 등).
                await connection.rollback()
                return
            run_id = row[0]
            for call in trace.model_calls:
                await connection.execute(
                    INSERT_MODEL_CALL,
                    (
                        run_id,
                        str(call["purpose"])[:50],
                        call.get("model_name"),
                        call.get("input_tokens"),
                        call.get("output_tokens"),
                        call.get("total_tokens"),
                        call.get("elapsed_ms"),
                        call.get("error_code"),
                    ),
                )
            for call in trace.tool_calls:
                await connection.execute(
                    INSERT_TOOL_CALL,
                    (
                        run_id,
                        str(call["tool_name"])[:100],
                        str(call.get("channel") or "api")[:20],
                        call.get("arguments_hash"),
                        str(call["status"])[:30],
                        call.get("elapsed_ms"),
                        call.get("error_code"),
                    ),
                )
            await connection.commit()


async def save_trace_safely(store: PostgresTraceStore | None, trace: RequestTrace) -> None:
    """Never let a tracing failure affect the user's response."""
    if store is None:
        return
    try:
        await store.save(trace)
    except Exception as error:
        logger.warning("요청 추적 저장 실패(request_id=%s): %s", trace.request_id, error)
