import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from agents.compliance_report import chain_hooks, compliance_notification
from agents.compliance_runs import ComplianceRun
from common.notifier import (
    DiscordWebhookNotifier,
    Notification,
    NullNotifier,
    notifier_from_env,
    notify_safely,
)
from common.telemetry import RequestTrace, trace_scope
from tests.test_compliance_api import ENV, assessment, make_pipeline_class, wait_for
from tests.test_compliance_graph import HIRING

WEBHOOK = "https://discord.com/api/webhooks/1/token"


def mock_client(status=204, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class RecordingNotifier:
    name = "Recording"

    def __init__(self):
        self.sent = []

    async def notify(self, notification):
        self.sent.append(notification)


class DiscordNotifierTest(unittest.IsolatedAsyncioTestCase):
    async def test_posts_embed_without_mentions(self):
        seen = []
        notifier = DiscordWebhookNotifier(WEBHOOK, client=mock_client(seen=seen))
        notification = Notification(
            title="AI 기본법 점검 완료", summary="요약", status="completed",
            url="https://example.com/reports/a.pdf", fields=[("고영향", "해당")], footer="법률 자문 아님",
        )
        trace = RequestTrace()
        with trace_scope(trace):
            self.assertTrue(await notify_safely(notifier, notification))
        embed = seen[0]["embeds"][0]
        self.assertEqual(seen[0]["allowed_mentions"], {"parse": []})
        self.assertEqual(embed["url"], "https://example.com/reports/a.pdf")
        self.assertEqual(embed["fields"][0], {"name": "고영향", "value": "해당", "inline": True})
        self.assertEqual(trace.tool_calls[0]["channel"], "notify")

    async def test_failure_is_recorded_not_raised(self):
        notifier = DiscordWebhookNotifier(WEBHOOK, client=mock_client(status=500))
        trace = RequestTrace()
        with trace_scope(trace), self.assertLogs("common.notifier", level="WARNING"):
            self.assertFalse(await notify_safely(notifier, Notification(title="x")))
        self.assertEqual(trace.tool_calls[0]["status"], "error")
        self.assertEqual(trace.tool_calls[0]["error_code"], "HTTPStatusError")

    def test_env_configuration(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
            self.assertIsInstance(notifier_from_env(), NullNotifier)
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": WEBHOOK}):
            self.assertIsInstance(notifier_from_env(), DiscordWebhookNotifier)
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "http://insecure"}), self.assertLogs(
            "common.notifier", level="WARNING"
        ):
            self.assertIsInstance(notifier_from_env(), NullNotifier)

    def test_compliance_notification_fields(self):
        run = ComplianceRun(id="r1", thread_id="t", status="completed", description_hash="h",
                            filename="service.pdf", report_url="/reports/x.pdf")
        run.assessment = {
            "high_impact": "yes", "high_impact_categories": ["사"], "confidence": 0.8,
            "obligations": [{"article": "제34조제1항", "applies": "해당"}, {"article": "제36조제1항", "applies": "해당 없음"}],
        }
        done = compliance_notification(run, "completed", public_base_url="https://law.example.com/")
        self.assertEqual(done.url, "https://law.example.com/reports/x.pdf")
        self.assertIn(("해당 의무", "제34조제1항"), done.fields)
        waiting = compliance_notification(run, "awaiting_approval")
        self.assertIsNone(waiting.url)
        self.assertIn(("승인", "POST /agents/compliance/runs/r1/approve"), waiting.fields)


class HookChainTest(unittest.IsolatedAsyncioTestCase):
    async def test_failing_hook_does_not_stop_next(self):
        calls = []

        async def broken(run, status):
            raise RuntimeError("pdf failed")

        async def second(run, status):
            calls.append(status)
            return {"report_url": None}

        run = ComplianceRun(id="r", thread_id="t", status="x", description_hash="h")
        with self.assertLogs("agents.compliance_report", level="WARNING"):
            await chain_hooks(broken, second)(run, "completed")
        self.assertEqual(calls, ["completed"])


class ServiceNotificationTest(unittest.TestCase):
    def test_waiting_and_completed_runs_notify(self):
        notifier = RecordingNotifier()
        with TemporaryDirectory() as directory, patch.dict(os.environ, ENV), patch(
            "app.main.notifier_from_env", lambda: notifier
        ), patch("documents.pdf_report.REPORT_DIR", Path(directory)):
            with TestClient(create_app_with(assessment("yes"))) as client:
                run_id = client.post("/agents/compliance/runs", json={"description": HIRING}).json()["run_id"]
                wait_for(client, run_id, {"awaiting_approval"})
                client.post(f"/agents/compliance/runs/{run_id}/approve", json={"approved": True})
        self.assertEqual([n.status for n in notifier.sent], ["awaiting_approval", "completed"])
        self.assertTrue(dict(notifier.sent[1].fields)["보고서"].startswith("/reports/compliance-report-"))


def create_app_with(value):
    from app.main import create_app

    return create_app(make_pipeline_class(value))


if __name__ == "__main__":
    unittest.main()
