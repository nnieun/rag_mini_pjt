import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import documents.pdf_report as pdf_report
from agents.compliance_schemas import HIGH_IMPACT_CATEGORIES, ComplianceAssessment
from app.main import create_app
from documents.processor import extract_document
from tests.test_compliance_api import ENV, assessment, make_pipeline_class, wait_for
from tests.test_compliance_graph import HIRING

SOURCES = {
    "S1": {"article": "제33조", "paragraph": "①", "title": "고영향 인공지능의 확인", "content": "사전에 검토하여야 하며"},
    "S2": {"article": "제34조", "paragraph": "①", "title": "사업자의 책무", "content": "위험관리방안의 수립"},
}


def pdf_text(path: Path) -> str:
    return extract_document(path.name, "application/pdf", path.read_bytes()).text


class CompliancePdfTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(pdf_report, "REPORT_DIR", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_contains_tables_citations_and_disclaimer(self):
        result = ComplianceAssessment.model_validate(
            {
                "high_impact": "yes",
                "high_impact_categories": ["사"],
                "obligations": [
                    {"article": "제33조제1항", "title": "사전 검토", "applies": "해당", "source_ids": ["S1"],
                     "actions": ["고영향 해당 여부 검토 기록"]},
                    {"article": "제34조제1항", "title": "안전성·신뢰성 확보 조치", "applies": "해당", "source_ids": ["S2"]},
                    {"article": "제36조제1항", "title": "국내대리인", "applies": "해당 없음"},
                ],
                "confidence": 0.82,
                "assumptions": ["국내 법인으로 가정"],
            }
        )
        path, url = pdf_report.create_compliance_pdf(
            service_name="채용 보조 AI",
            assessment=result.model_dump(),
            sources=SOURCES,
            categories=HIGH_IMPACT_CATEGORIES,
            review={"status": "approved", "reviewer": "kim", "comment": "확인함"},
            run_id="run-1",
        )
        self.assertTrue(url.startswith("/reports/compliance-report-"))
        self.assertTrue(path.exists())
        if not pdf_report.has_korean_font():
            self.skipTest("한글 글꼴이 없어 텍스트 검사를 건너뜀")
        text = pdf_text(path)
        for expected in ("채용 보조 AI", "사목", "제34조제1항", "[S2]", "위험관리방안", "법률 자문 아님", "승인됨", "국내 법인으로 가정"):
            self.assertIn(expected, text.replace("\n", " "))


class ComplianceReportHookTest(unittest.TestCase):
    def test_completed_run_gets_report_url(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, ENV), patch.object(
            pdf_report, "REPORT_DIR", Path(directory)
        ):
            with TestClient(create_app(make_pipeline_class(assessment("no")))) as client:
                run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
                done = wait_for(client, run_id, {"completed"})
                self.assertTrue(done["report_url"].startswith("/reports/compliance-report-"))
                self.assertTrue((Path(directory) / done["report_url"].rsplit("/", 1)[1]).exists())

    def test_report_waits_for_approval(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, ENV), patch.object(
            pdf_report, "REPORT_DIR", Path(directory)
        ):
            with TestClient(create_app(make_pipeline_class(assessment("yes")))) as client:
                run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
                waiting = wait_for(client, run_id, {"awaiting_approval"})
                self.assertIsNone(waiting["report_url"])
                rejected = client.post(f"/agents/compliance/runs/{run_id}/approve", json={"approved": False}).json()
                self.assertIsNone(rejected["report_url"])


if __name__ == "__main__":
    unittest.main()
