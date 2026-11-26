"""HTTP API for the compliance agent.

POST /agents/compliance/runs                 start a run from a text description
POST /agents/compliance/runs/upload          start a run from an uploaded document
GET  /agents/compliance/runs/{run_id}        run status and result
POST /agents/compliance/runs/{run_id}/approve  approve or reject a run awaiting approval
GET  /agents/compliance/runs/{run_id}/events   progress as Server-Sent Events
"""

import os
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.compliance_runs import ComplianceRun, ComplianceService
from documents.processor import extract_document

router = APIRouter(prefix="/agents/compliance", tags=["compliance"])


class ComplianceRunRequest(BaseModel):
    description: str = Field(min_length=10, max_length=20000, description="AI 서비스 설명")


class ApprovalRequest(BaseModel):
    approved: bool
    reviewer: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=2000)


class ComplianceRunResponse(BaseModel):
    run_id: str
    status: str
    source_type: str
    filename: str | None = None
    high_impact: str | None = None
    confidence: float | None = None
    assessment: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    review_request: dict[str, Any] | None = None
    report_url: str | None = None
    error_code: str | None = None
    created_at: str
    updated_at: str
    events_url: str


def _service(request: Request) -> ComplianceService:
    service = getattr(request.app.state, "compliance_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="컴플라이언스 에이전트를 사용할 수 없습니다.")
    return service


def _response(run: ComplianceRun) -> ComplianceRunResponse:
    data = run.as_dict()
    return ComplianceRunResponse(
        run_id=data.pop("id"),
        events_url=f"/agents/compliance/runs/{run.id}/events",
        **{key: value for key, value in data.items() if key not in {"thread_id", "description_hash"}},
    )


@router.post("/runs", response_model=ComplianceRunResponse, status_code=202)
async def create_run(payload: ComplianceRunRequest, request: Request) -> ComplianceRunResponse:
    try:
        run = await _service(request).create_run(payload.description)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _response(run)


@router.post("/runs/upload", response_model=ComplianceRunResponse, status_code=202)
async def create_run_from_file(request: Request, file: UploadFile = File(...)) -> ComplianceRunResponse:
    try:
        extracted = extract_document(
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            await file.read(),
            max_bytes=int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024))),
        )
        run = await _service(request).create_run(
            extracted.text, source_type="file", filename=(file.filename or "upload")[:255]
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _response(run)


@router.get("/runs/{run_id}", response_model=ComplianceRunResponse)
async def get_run(run_id: str, request: Request) -> ComplianceRunResponse:
    run = await _service(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다.")
    return _response(run)


@router.post("/runs/{run_id}/approve", response_model=ComplianceRunResponse)
async def approve_run(run_id: str, payload: ApprovalRequest, request: Request) -> ComplianceRunResponse:
    try:
        run = await _service(request).approve(
            run_id, approved=payload.approved, reviewer=payload.reviewer, comment=payload.comment
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _response(run)


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    service = _service(request)
    if await service.get(run_id) is None:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다.")
    return StreamingResponse(
        service.stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
