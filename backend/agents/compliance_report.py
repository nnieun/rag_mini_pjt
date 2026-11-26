"""What happens when a compliance run stops: PDF report and notification."""

import asyncio
import logging
from typing import Any

from agents.compliance_schemas import APPLIES, HIGH_IMPACT_CATEGORIES
from common.notifier import Notification, Notifier, notify_safely
from documents.pdf_report import create_compliance_pdf

logger = logging.getLogger(__name__)


async def build_compliance_report(agent: Any, run: Any) -> str:
    """Render the run's assessment to a PDF and return its /reports URL."""
    result = await agent.result(run.thread_id)
    assessment = result.get("assessment")
    if assessment is None:
        raise ValueError("판정 결과가 없어 보고서를 만들 수 없습니다.")
    profile = result.get("profile")
    service_name = (getattr(profile, "name", "") or run.filename or "AI 서비스").strip()
    _, url = await asyncio.to_thread(
        create_compliance_pdf,
        service_name=service_name,
        assessment=assessment.model_dump(),
        sources=result.get("sources") or {},
        categories=HIGH_IMPACT_CATEGORIES,
        review=result.get("review"),
        run_id=run.id,
    )
    return url


def report_on_completion(agent: Any):
    """`ComplianceService(on_finished=...)` hook: completed runs get a PDF report."""

    async def hook(run: Any, status: str) -> dict[str, Any]:
        if status != "completed":
            return {}
        return {"report_url": await build_compliance_report(agent, run)}

    return hook


STATUS_TITLES = {
    "completed": "점검 완료",
    "awaiting_approval": "사람 검토 필요",
    "rejected": "검토에서 반려됨",
}
HIGH_IMPACT_TEXT = {"yes": "해당", "no": "해당 없음", "uncertain": "판단 보류"}


def compliance_notification(run: Any, status: str, *, public_base_url: str = "") -> Notification:
    assessment = run.assessment or {}
    applicable = [
        item.get("article", "")
        for item in assessment.get("obligations") or []
        if item.get("applies") in APPLIES
    ]
    categories = ", ".join(f"{c}목" for c in assessment.get("high_impact_categories") or []) or "-"
    base = public_base_url.rstrip("/")
    report = f"{base}{run.report_url}" if run.report_url and base else None
    fields = [
        ("고영향 인공지능", HIGH_IMPACT_TEXT.get(assessment.get("high_impact"), "-")),
        ("해당 목", categories),
        ("신뢰도", f"{float(assessment.get('confidence') or 0):.2f}"),
        ("해당 의무", ", ".join(applicable) or "-"),
    ]
    if status == "awaiting_approval":
        reasons = ", ".join((run.review_request or {}).get("reasons") or [])
        fields.append(("검토 사유", reasons or "-"))
        fields.append(("승인", f"POST /agents/compliance/runs/{run.id}/approve"))
    elif run.report_url:
        fields.append(("보고서", report or run.report_url))
    return Notification(
        title=f"AI 기본법 {STATUS_TITLES.get(status, status)}: {run.filename or '서비스 설명'}",
        summary=str(assessment.get("summary") or ""),
        status=status,
        url=report,
        fields=fields,
        footer=f"run {run.id} · 법률 자문 아님",
    )


def notify_on_finish(notifier: Notifier, *, public_base_url: str = ""):
    async def hook(run: Any, status: str) -> dict[str, Any]:
        if status in STATUS_TITLES:
            await notify_safely(notifier, compliance_notification(run, status, public_base_url=public_base_url))
        return {}

    return hook


def chain_hooks(*hooks):
    """Run finish hooks in order; each sees the run with the previous hooks' changes."""

    async def hook(run: Any, status: str) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for item in hooks:
            try:
                update = await item(run, status) or {}
            except Exception as error:
                # 보고서 생성이 실패해도 알림은 보낸다.
                logger.warning("실행 후처리 단계 실패 run_id=%s: %s", run.id, error)
                continue
            for key, value in update.items():
                setattr(run, key, value)
            changes.update(update)
        return changes

    return hook
