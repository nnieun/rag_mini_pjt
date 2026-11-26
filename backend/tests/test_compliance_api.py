import io
import json
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.main import create_app
from tests.test_compliance_graph import HIRING, LawPipeline, ScriptedLLM, call

ENV = {
    "RAG_ANSWER_CACHE_ENABLED": "false",
    "RAG_RERANK_PRELOAD": "false",
    "RAG_CHECKPOINT_ENABLED": "false",
    "RAG_TRACE_STORE_ENABLED": "false",
    "RAG_COMPLIANCE_STORE_ENABLED": "false",
    "RAG_MCP_CLIENT_ENABLED": "false",
}


def make_pipeline_class(assessment):
    class Pipeline(LawPipeline):
        def __init__(self):
            super().__init__()
            self.llm = ScriptedLLM(
                [AIMessage("", tool_calls=[call("GetArticle", {"article_number": 33}, "c1")])],
                structured={"ComplianceAssessment": assessment},
            )

        def close(self):
            pass

    return Pipeline


def assessment(high="yes"):
    return {
        "high_impact": high,
        "high_impact_categories": ["사"] if high == "yes" else [],
        "obligations": [{"article": "제33조제1항", "applies": "해당", "source_ids": ["S1"]}],
        "confidence": 0.9,
    }


def wait_for(client, run_id, statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/agents/compliance/runs/{run_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.02)
    raise AssertionError(f"status not reached: {body['status']}")


class ComplianceApiTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_high_impact_run_waits_then_approves(self):
        with TestClient(create_app(make_pipeline_class(assessment("yes")))) as client:
            created = client.post("/agents/compliance/runs", json={"description": HIRING})
            self.assertEqual(created.status_code, 202)
            run_id = created.json()["run_id"]
            self.assertEqual(created.json()["events_url"], f"/agents/compliance/runs/{run_id}/events")

            waiting = wait_for(client, run_id, {"awaiting_approval"})
            self.assertEqual(waiting["high_impact"], "yes")
            self.assertEqual(waiting["review_request"]["reasons"], ["고영향 인공지능 해당"])

            approved = client.post(
                f"/agents/compliance/runs/{run_id}/approve",
                json={"approved": True, "reviewer": "kim"},
            )
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "completed")
            self.assertEqual(approved.json()["review"]["status"], "approved")

            again = client.post(f"/agents/compliance/runs/{run_id}/approve", json={"approved": True})
            self.assertEqual(again.status_code, 409)

    def test_events_stream_replays_steps_until_stop(self):
        with TestClient(create_app(make_pipeline_class(assessment("yes")))) as client:
            run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
            events = []
            with client.stream("GET", f"/agents/compliance/runs/{run_id}/events") as response:
                self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
        steps = [event["step"] for event in events]
        for step in ("ingest", "profile", "agent", "tools", "assess", "validate", "awaiting_approval"):
            self.assertIn(step, steps)
        self.assertEqual(events[-1], {**events[-1], "step": "status", "status": "awaiting_approval"})
        tools = next(event for event in events if event["step"] == "tools")
        self.assertEqual(tools["calls"], [{"name": "GetArticle", "status": "ok"}])

    def test_non_high_impact_completes_without_approval(self):
        with TestClient(create_app(make_pipeline_class(assessment("no")))) as client:
            run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
            done = wait_for(client, run_id, {"completed"})
        self.assertEqual(done["review"]["status"], "not_required")
        self.assertEqual(done["assessment"]["obligations"][0]["article"], "제33조제1항")

    def test_upload_and_validation_errors(self):
        with TestClient(create_app(make_pipeline_class(assessment("no")))) as client:
            uploaded = client.post(
                "/agents/compliance/runs/upload",
                files={"file": ("service.txt", io.BytesIO(HIRING.encode()), "text/plain")},
            )
            short = client.post("/agents/compliance/runs", json={"description": "짧다"})
            missing = client.get("/agents/compliance/runs/00000000-0000-0000-0000-000000000000")
            events_missing = client.get("/agents/compliance/runs/nope/events")
            self.assertEqual(uploaded.status_code, 202)
            self.assertEqual(uploaded.json()["source_type"], "file")
            self.assertEqual(uploaded.json()["filename"], "service.txt")
            wait_for(client, uploaded.json()["run_id"], {"completed"})
        self.assertEqual(short.status_code, 422)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(events_missing.status_code, 404)

    def test_agent_failure_marks_run_failed(self):
        with TestClient(create_app(make_pipeline_class(assessment("no")))) as client:
            client.app.state.compliance_service.agent.start = _raise
            run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
            failed = wait_for(client, run_id, {"failed"})
        self.assertEqual(failed["error_code"], "RuntimeError")


async def _raise(*args, **kwargs):
    raise RuntimeError("qdrant down")


if __name__ == "__main__":
    unittest.main()
