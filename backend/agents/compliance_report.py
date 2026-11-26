"""PDF report for a finished compliance run."""

import asyncio
from typing import Any

from agents.compliance_schemas import HIGH_IMPACT_CATEGORIES
from documents.pdf_report import create_compliance_pdf


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
