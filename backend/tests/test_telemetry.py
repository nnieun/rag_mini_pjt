import os
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.main import create_app
from common.telemetry import (
    RequestTrace,
    TraceCallbackHandler,
    get_current_trace,
    record_tool_call,
    trace_scope,
)
from rag.models import AnswerResult, Source
from tests.test_api import FakePipeline


def fake_llm(handler):
    message = AIMessage(
        content="답변",
        usage_metadata={"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
    )
    return GenericFakeChatModel(messages=iter([message]), callbacks=[handler])


class TraceCallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_model_call_is_recorded_with_tokens(self):
        handler = TraceCallbackHandler()
        with trace_scope() as trace:
            await fake_llm(handler).ainvoke("질문")
        self.assertEqual(len(trace.model_calls), 1)
        call = trace.model_calls[0]
        self.assertEqual(call["purpose"], "llm")
        self.assertEqual(call["total_tokens"], 17)
        self.assertGreaterEqual(call["elapsed_ms"], 0)
        self.assertEqual(trace.token_totals()["input_tokens"], 12)

    async def test_purpose_is_langgraph_node(self):
        handler = TraceCallbackHandler()
        llm = fake_llm(handler)

        class State(TypedDict, total=False):
            answer: str

        async def generate(state):
            return {"answer": (await llm.ainvoke("질문")).content}

        builder = StateGraph(State)
        builder.add_node("generate", generate)
        builder.add_edge(START, "generate")
        builder.add_edge("generate", END)
        with trace_scope() as trace:
            await builder.compile().ainvoke({})
        self.assertEqual(trace.model_calls[0]["purpose"], "generate")

    async def test_nothing_is_recorded_without_active_trace(self):
        handler = TraceCallbackHandler()
        await fake_llm(handler).ainvoke("질문")
        self.assertIsNone(get_current_trace())
        self.assertEqual(handler._runs, {})

    async def test_tool_call_success_and_error(self):
        async def ok():
            return [1]

        async def fail():
            raise ValueError("bad")

        with trace_scope() as trace:
            self.assertEqual(await record_tool_call("SearchLaw", ok), [1])
            with self.assertRaises(ValueError):
                await record_tool_call("GetArticle", fail)
        self.assertEqual(
            [(c["tool_name"], c["status"], c["error_code"]) for c in trace.tool_calls],
            [("SearchLaw", "ok", None), ("GetArticle", "error", "ValueError")],
        )

    async def test_execute_tool_records_into_trace(self):
        from tests.test_agentic_features import AgenticFakePipeline
        from rag.tools import execute_tool

        with trace_scope() as trace:
            await execute_tool(AgenticFakePipeline(), "GetArticle", {"article_number": 33})
            with self.assertRaises(ValueError):
                await execute_tool(AgenticFakePipeline(), "Unknown", {})
        self.assertEqual([c["status"] for c in trace.tool_calls], ["ok", "error"])


class FakeGraph:
    def __init__(self):
        self.seen_trace: RequestTrace | None = None

    async def answer(self, question, **kwargs):
        self.seen_trace = get_current_trace()
        await record_tool_call("SearchLaw", self._noop)
        return AnswerResult(
            answer="근거 답변 [S1]",
            sources=[Source("S1", "제2조", "", "", "", "정의", "근거")],
            method="fake",
            retrieved_articles=["제2조"],
        )

    async def _noop(self):
        return []


class RequestTraceMiddlewareTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            os.environ, {"RAG_ANSWER_CACHE_ENABLED": "false", "RAG_RERANK_PRELOAD": "false"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ask_returns_trace_request_id(self):
        with TestClient(create_app(FakePipeline)) as client:
            graph = FakeGraph()
            client.app.state.rag_graph = graph
            response = client.post("/ask", json={"question": "고영향 인공지능이란?"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        UUID(body["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], body["request_id"])
        self.assertEqual(graph.seen_trace.request_id, body["request_id"])
        self.assertEqual(graph.seen_trace.status, "answered")
        self.assertEqual(graph.seen_trace.tool_calls[0]["tool_name"], "SearchLaw")

    def test_incoming_request_id_is_reused_only_if_uuid(self):
        given = "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"
        with TestClient(create_app(FakePipeline)) as client:
            reused = client.get("/health", headers={"X-Request-ID": given})
            replaced = client.get("/health", headers={"X-Request-ID": "not-a-uuid"})
        self.assertEqual(reused.headers["X-Request-ID"], given)
        self.assertNotEqual(replaced.headers["X-Request-ID"], "not-a-uuid")


if __name__ == "__main__":
    unittest.main()
