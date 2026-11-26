import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from common.telemetry import RequestTrace
from common.trace_store import PostgresTraceStore, save_trace_safely, schema_sql
from tests.test_api import FakePipeline
from tests.test_telemetry import FakeGraph


class FakeCursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, existing_request_ids):
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.existing = existing_request_ids

    async def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))
        if "INSERT INTO request_runs" in sql:
            if params[0] in self.existing:
                return FakeCursor(None)
            return FakeCursor(("run-uuid",))
        return FakeCursor(None)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakePool:
    def __init__(self, existing=(), fail=False):
        self.connections = []
        self.existing = set(existing)
        self.fail = fail

    def connection(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                if pool.fail:
                    raise ConnectionError("db down")
                conn = FakeConnection(pool.existing)
                pool.connections.append(conn)
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def sample_trace():
    trace = RequestTrace(endpoint="/ask", status="answered")
    trace.add_model_call(None, "generate", 120.5, model_name="gpt-test")
    trace.model_calls[0].update(input_tokens=10, output_tokens=4, total_tokens=14)
    trace.add_tool_call("SearchLaw", "ok", 30.0)
    trace.add_tool_call("GetArticle", "error", 1.0, error_code="ValueError")
    trace.finish()
    return trace


class TraceStoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_saves_run_then_model_and_tool_calls_in_one_transaction(self):
        pool = FakePool()
        trace = sample_trace()
        await PostgresTraceStore(pool, pipeline_version="v-test").save(trace)

        conn = pool.connections[0]
        tables = [sql.split()[2] for sql, _ in conn.statements]
        self.assertEqual(tables, ["request_runs", "model_calls", "tool_calls", "tool_calls"])
        run_params = conn.statements[0][1]
        self.assertEqual(run_params[0], trace.request_id)
        self.assertEqual(run_params[1:4], ("v-test", "answered", False))
        self.assertEqual(conn.statements[1][1][0], "run-uuid")
        self.assertEqual(conn.statements[1][1][1:6], ("generate", "gpt-test", 10, 4, 14))
        self.assertEqual(conn.statements[3][1][1:3], ("GetArticle", "error"))
        self.assertTrue(conn.committed)

    async def test_duplicate_request_id_is_skipped(self):
        trace = sample_trace()
        pool = FakePool(existing={trace.request_id})
        await PostgresTraceStore(pool, pipeline_version="v").save(trace)
        conn = pool.connections[0]
        self.assertEqual(len(conn.statements), 1)
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)

    async def test_database_failure_is_swallowed(self):
        store = PostgresTraceStore(FakePool(fail=True), pipeline_version="v")
        with self.assertLogs("common.trace_store", level="WARNING"):
            await save_trace_safely(store, sample_trace())

    def test_schema_sql_has_three_tables_without_transaction_wrapper(self):
        sql = schema_sql()
        for table in ("request_runs", "model_calls", "tool_calls"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)
        self.assertNotIn("BEGIN;", sql)


class RecordingStore:
    def __init__(self, fail=False):
        self.saved = []
        self.fail = fail

    async def save(self, trace):
        if self.fail:
            raise ConnectionError("db down")
        self.saved.append(trace)


class MiddlewareWriteTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            os.environ,
            {
                "RAG_ANSWER_CACHE_ENABLED": "false",
                "RAG_RERANK_PRELOAD": "false",
                "RAG_TRACE_STORE_ENABLED": "false",
                "RAG_CHECKPOINT_ENABLED": "false",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_ask(self, store):
        with TestClient(create_app(FakePipeline)) as client:
            client.app.state.rag_graph = FakeGraph()
            client.app.state.trace_store = store
            ask = client.post("/ask", json={"question": "고영향 인공지능이란?"})
            health = client.get("/health")
        return ask, health

    def test_ask_is_saved_and_health_is_not(self):
        store = RecordingStore()
        ask, health = self.run_ask(store)
        self.assertEqual(ask.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(len(store.saved), 1)
        saved = store.saved[0]
        self.assertEqual(saved.request_id, ask.json()["request_id"])
        self.assertEqual(saved.status, "answered")
        self.assertIsNotNone(saved.ended_at)
        self.assertEqual(saved.tool_calls[0]["tool_name"], "SearchLaw")

    def test_store_failure_does_not_break_response(self):
        with self.assertLogs("common.trace_store", level="WARNING"):
            ask, _ = self.run_ask(RecordingStore(fail=True))
        self.assertEqual(ask.status_code, 200)

    def test_validation_error_is_still_traced(self):
        store = RecordingStore()
        with TestClient(create_app(FakePipeline)) as client:
            client.app.state.trace_store = store
            response = client.post("/ask", json={"question": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(store.saved[0].status, "http_422")


if __name__ == "__main__":
    unittest.main()
