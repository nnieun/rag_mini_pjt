"""Request-scoped tracing for model calls and tool calls.

- `trace_scope()` opens one `RequestTrace` per HTTP request and stores it in a contextvar.
- `TraceCallbackHandler` is attached to the LLM, so every LangChain call made while a
  trace is active is recorded with its token usage and latency.
- `record_tool_call()` wraps a tool execution and records its status and latency.

Code that runs outside a request (scripts, tests) has no active trace; every
recording helper then does nothing.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, TypeVar
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackHandler

T = TypeVar("T")


@dataclass
class RequestTrace:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    endpoint: str = ""
    started_at: float = field(default_factory=perf_counter)
    ended_at: float | None = None
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "running"
    cache_hit: bool = False

    def add_model_call(
        self,
        response: Any,
        purpose: str,
        elapsed_ms: float,
        *,
        model_name: str | None = None,
        error_code: str | None = None,
    ) -> None:
        usage = _usage_from(response)
        self.model_calls.append(
            {
                "purpose": purpose,
                "model_name": model_name,
                "elapsed_ms": round(elapsed_ms, 2),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "error_code": error_code,
            }
        )

    def add_tool_call(
        self,
        tool_name: str,
        status: str,
        elapsed_ms: float,
        *,
        error_code: str | None = None,
        channel: str = "api",
    ) -> None:
        self.tool_calls.append(
            {
                "tool_name": tool_name,
                "status": status,
                "elapsed_ms": round(elapsed_ms, 2),
                "error_code": error_code,
                "channel": channel,
            }
        )

    def finish(self) -> None:
        if self.ended_at is None:
            self.ended_at = perf_counter()

    @property
    def elapsed_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else perf_counter()
        return round((end - self.started_at) * 1000, 2)

    def token_totals(self) -> dict[str, int]:
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for call in self.model_calls:
            for key in totals:
                totals[key] += int(call.get(key) or 0)
        return totals


_current_trace: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def get_current_trace() -> RequestTrace | None:
    return _current_trace.get()


@contextmanager
def trace_scope(trace: RequestTrace | None = None):
    """Make `trace` the active trace for the code inside the block."""
    trace = trace or RequestTrace()
    token = _current_trace.set(trace)
    try:
        yield trace
    finally:
        _current_trace.reset(token)


@asynccontextmanager
async def tool_call_scope(tool_name: str, *, channel: str = "api") -> AsyncIterator[None]:
    started = perf_counter()
    try:
        yield
    except Exception as error:
        trace = get_current_trace()
        if trace is not None:
            trace.add_tool_call(
                tool_name,
                "error",
                (perf_counter() - started) * 1000,
                error_code=type(error).__name__,
                channel=channel,
            )
        raise
    trace = get_current_trace()
    if trace is not None:
        trace.add_tool_call(
            tool_name, "ok", (perf_counter() - started) * 1000, channel=channel
        )


async def record_tool_call(
    tool_name: str, call: Callable[[], Awaitable[T]], *, channel: str = "api"
) -> T:
    async with tool_call_scope(tool_name, channel=channel):
        return await call()


def _usage_from(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return dict(usage)
    return {}


class TraceCallbackHandler(AsyncCallbackHandler):
    """Records every chat model call into the active `RequestTrace`.

    The purpose of a call is the LangGraph node that made it (`langgraph_node`
    metadata), or "llm" when it was called outside the graph.
    """

    def __init__(self) -> None:
        self._runs: dict[UUID, tuple[float, str, str | None]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if get_current_trace() is None:
            return
        metadata = metadata or {}
        purpose = str(metadata.get("langgraph_node") or metadata.get("purpose") or "llm")
        model_name = metadata.get("ls_model_name")
        self._runs[run_id] = (perf_counter(), purpose, model_name)

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._runs.pop(run_id, None)
        trace = get_current_trace()
        if started is None or trace is None:
            return
        began, purpose, model_name = started
        message = None
        try:
            message = response.generations[0][0].message
        except (AttributeError, IndexError, TypeError):
            pass
        trace.add_model_call(
            message, purpose, (perf_counter() - began) * 1000, model_name=model_name
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._runs.pop(run_id, None)
        trace = get_current_trace()
        if started is None or trace is None:
            return
        began, purpose, model_name = started
        trace.add_model_call(
            None,
            purpose,
            (perf_counter() - began) * 1000,
            model_name=model_name,
            error_code=type(error).__name__,
        )


trace_callback_handler = TraceCallbackHandler()
