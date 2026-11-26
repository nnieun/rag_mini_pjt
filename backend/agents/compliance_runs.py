"""Compliance runs: persistence, background execution and progress events.

`ComplianceService` starts the agent in a background task, records the run in a
`ComplianceRunStore` and publishes progress events that the SSE endpoint streams.

Run status: queued -> running -> awaiting_approval -> completed | rejected,
or failed on error.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from common.telemetry import RequestTrace, trace_scope

logger = logging.getLogger(__name__)

TERMINAL = {"completed", "rejected", "failed"}
STOP_STATUSES = TERMINAL | {"awaiting_approval"}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docker" / "postgres-init" / "005_compliance_runs.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ComplianceRun:
    id: str
    thread_id: str
    status: str
    description_hash: str
    source_type: str = "text"
    filename: str | None = None
    high_impact: str | None = None
    confidence: float | None = None
    assessment: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    review_request: dict[str, Any] | None = None
    report_url: str | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComplianceRunStore(Protocol):
    async def create(self, run: ComplianceRun) -> None: ...
    async def update(self, run: ComplianceRun) -> None: ...
    async def get(self, run_id: str) -> ComplianceRun | None: ...


class InMemoryComplianceRunStore:
    def __init__(self) -> None:
        self.runs: dict[str, ComplianceRun] = {}

    async def create(self, run: ComplianceRun) -> None:
        self.runs[run.id] = run

    async def update(self, run: ComplianceRun) -> None:
        self.runs[run.id] = run

    async def get(self, run_id: str) -> ComplianceRun | None:
        return self.runs.get(run_id)


class PostgresComplianceRunStore:
    """compliance_runs table (docker/postgres-init/005_compliance_runs.sql)."""

    COLUMNS = (
        "id", "thread_id", "status", "source_type", "filename", "description_hash",
        "high_impact", "confidence", "assessment", "review", "report_url", "error_code",
    )

    def __init__(self, pool: Any):
        self.pool = pool
        # 승인 요청 내용은 체크포인트에서 다시 읽으므로 메모리에만 둔다.
        self._review_requests: dict[str, dict[str, Any] | None] = {}

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=5.0)
        sql = SCHEMA_PATH.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
        async with self.pool.connection() as connection:
            await connection.execute(sql)
            await connection.commit()

    async def close(self) -> None:
        await self.pool.close()

    def _values(self, run: ComplianceRun) -> tuple:
        from psycopg.types.json import Jsonb

        return (
            run.id, run.thread_id, run.status, run.source_type, run.filename, run.description_hash,
            run.high_impact, run.confidence,
            Jsonb(run.assessment) if run.assessment is not None else None,
            Jsonb(run.review) if run.review is not None else None,
            run.report_url, run.error_code,
        )

    async def create(self, run: ComplianceRun) -> None:
        placeholders = ", ".join(["%s"] * len(self.COLUMNS))
        async with self.pool.connection() as connection:
            await connection.execute(
                f"INSERT INTO compliance_runs ({', '.join(self.COLUMNS)}) VALUES ({placeholders})",
                self._values(run),
            )
            await connection.commit()
        self._review_requests[run.id] = run.review_request

    async def update(self, run: ComplianceRun) -> None:
        assignments = ", ".join(f"{column} = %s" for column in self.COLUMNS[2:])
        values = self._values(run)
        async with self.pool.connection() as connection:
            await connection.execute(
                f"UPDATE compliance_runs SET {assignments}, updated_at = now() WHERE id = %s",
                (*values[2:], run.id),
            )
            await connection.commit()
        self._review_requests[run.id] = run.review_request

    async def get(self, run_id: str) -> ComplianceRun | None:
        try:
            uuid.UUID(run_id)
        except ValueError:
            return None
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                f"SELECT {', '.join(self.COLUMNS)}, created_at, updated_at FROM compliance_runs WHERE id = %s",
                (run_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        values = dict(zip((*self.COLUMNS, "created_at", "updated_at"), row))
        values["id"] = str(values["id"])
        values["created_at"] = values["created_at"].isoformat()
        values["updated_at"] = values["updated_at"].isoformat()
        values["review_request"] = self._review_requests.get(values["id"])
        return ComplianceRun(**values)


class EventHub:
    """Per-run event history plus live subscribers (for SSE)."""

    def __init__(self, history_limit: int = 200, keepalive_seconds: float = 15.0) -> None:
        self.keepalive_seconds = keepalive_seconds
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.history_limit = history_limit

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        event = {**event, "run_id": run_id, "at": _now()}
        history = self.history.setdefault(run_id, [])
        history.append(event)
        del history[: -self.history_limit]
        for queue in self.subscribers.get(run_id, set()):
            queue.put_nowait(event)

    @staticmethod
    def _is_stop(event: dict[str, Any]) -> bool:
        return event.get("step") == "status" and event.get("status") in STOP_STATUSES

    async def subscribe(self, run_id: str, *, is_done) -> AsyncIterator[dict[str, Any]]:
        """Replay history, then stream live events until the run stops.

        A run stops at a terminal status or at awaiting_approval; after approval the
        client opens the stream again.
        """
        queue: asyncio.Queue = asyncio.Queue()
        # 구독 등록과 기록 복사 사이에 await가 없어 이벤트가 겹치거나 빠지지 않는다.
        self.subscribers.setdefault(run_id, set()).add(queue)
        snapshot = list(self.history.get(run_id, []))
        try:
            for event in snapshot:
                yield event
            last = snapshot[-1] if snapshot else {}
            if self._is_stop(last):
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.keepalive_seconds)
                except asyncio.TimeoutError:
                    if await is_done():
                        return
                    yield {"step": "keepalive", "run_id": run_id}
                    continue
                yield event
                if self._is_stop(event):
                    return
        finally:
            self.subscribers[run_id].discard(queue)


def description_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ComplianceService:
    def __init__(
        self,
        agent: Any,
        store: ComplianceRunStore,
        *,
        events: EventHub | None = None,
        on_finished=None,
        trace_sink=None,
    ):
        self.agent = agent
        # 백그라운드 실행마다 RequestTrace를 따로 만들고, 끝나면 trace_sink(trace)로 넘긴다.
        self.trace_sink = trace_sink
        self.store = store
        self.events = events or EventHub()
        self.tasks: set[asyncio.Task] = set()
        # 실행이 승인 대기·완료·실패로 끝날 때 호출(보고서 생성, 알림 등). 예외는 무시된다.
        self.on_finished = on_finished

    async def _set_status(self, run: ComplianceRun, status: str, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(run, key, value)
        run.status = status
        run.updated_at = _now()
        await self.store.update(run)
        self.events.publish(run.id, {"step": "status", "status": status})

    def _apply_result(self, run: ComplianceRun, result: dict[str, Any]) -> str:
        assessment = result.get("assessment")
        if assessment is not None:
            run.assessment = assessment.model_dump()
            run.high_impact = assessment.high_impact
            run.confidence = assessment.confidence
        run.review = result.get("review")
        run.review_request = result.get("review_request")
        return result["status"] if result["status"] in STOP_STATUSES else "failed"

    def _spawn(self, coroutine) -> None:
        # 요청의 RequestTrace가 백그라운드 작업에 복사되지 않도록 빈 컨텍스트에서 시작한다.
        import contextvars

        task = asyncio.create_task(coroutine, context=contextvars.Context())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def create_run(self, description: str, *, source_type: str = "text", filename: str | None = None) -> ComplianceRun:
        text = description.strip()
        if len(text) < 10:
            raise ValueError("서비스 설명이 너무 짧습니다(10자 이상).")
        run_id = str(uuid.uuid4())
        run = ComplianceRun(
            id=run_id,
            thread_id=f"compliance-{run_id}",
            status="queued",
            description_hash=description_hash(text),
            source_type=source_type,
            filename=filename,
        )
        await self.store.create(run)
        self.events.publish(run.id, {"step": "status", "status": "queued"})
        self._spawn(self._execute(run, text))
        return run

    async def _traced(self, endpoint: str, coroutine):
        trace = RequestTrace(endpoint=endpoint)
        with trace_scope(trace):
            try:
                result = await coroutine
                trace.status = "ok"
                return result
            except Exception as error:
                trace.status = "error"
                trace.errors.append(type(error).__name__)
                raise
            finally:
                trace.finish()
                if self.trace_sink is not None:
                    try:
                        self.trace_sink(trace)
                    except Exception as error:
                        logger.warning("컴플라이언스 실행 추적 저장 실패: %s", error)

    async def _execute(self, run: ComplianceRun, description: str) -> None:
        await self._set_status(run, "running")
        try:
            result = await self._traced("compliance:run", self.agent.start(
                description,
                thread_id=run.thread_id,
                on_event=lambda event: self.events.publish(run.id, event),
            ))
            status = self._apply_result(run, result)
        except Exception as error:
            logger.exception("컴플라이언스 실행 실패 run_id=%s", run.id)
            await self._set_status(run, "failed", error_code=type(error).__name__)
            return
        await self._finish(run, status)

    async def _finish(self, run: ComplianceRun, status: str) -> None:
        if self.on_finished is not None:
            try:
                changes = await self._traced("compliance:finish", self.on_finished(run, status))
                for key, value in (changes or {}).items():
                    setattr(run, key, value)
            except Exception as error:
                logger.warning("실행 후처리 실패 run_id=%s: %s", run.id, error)
        await self._set_status(run, status)

    async def approve(self, run_id: str, *, approved: bool, reviewer: str = "", comment: str = "") -> ComplianceRun:
        run = await self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != "awaiting_approval":
            raise ValueError(f"승인 대기 상태가 아닙니다: {run.status}")
        await self._set_status(run, "running")
        try:
            result = await self._traced("compliance:approve", self.agent.resume(
                run.thread_id,
                approved=approved,
                reviewer=reviewer,
                comment=comment,
                on_event=lambda event: self.events.publish(run.id, event),
            ))
            status = self._apply_result(run, result)
        except Exception as error:
            await self._set_status(run, "failed", error_code=type(error).__name__)
            raise
        await self._finish(run, status)
        return run

    async def get(self, run_id: str) -> ComplianceRun | None:
        run = await self.store.get(run_id)
        if run is not None and run.status == "awaiting_approval" and run.review_request is None:
            # 재시작 후에는 승인 요청 내용을 체크포인트에서 다시 읽는다.
            try:
                run.review_request = (await self.agent.result(run.thread_id)).get("review_request")
            except Exception as error:
                logger.warning("승인 요청 내용을 읽지 못함 run_id=%s: %s", run_id, error)
        return run

    async def is_done(self, run_id: str) -> bool:
        run = await self.store.get(run_id)
        return run is None or run.status in STOP_STATUSES

    async def stream(self, run_id: str) -> AsyncIterator[str]:
        async for event in self.events.subscribe(run_id, is_done=lambda: self.is_done(run_id)):
            yield f"event: {event.get('step', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def close(self) -> None:
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
