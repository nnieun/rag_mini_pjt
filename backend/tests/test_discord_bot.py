import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

try:
    import discord  # noqa: F401
except ImportError:  # discord extra not installed
    discord = None

from bots.law_client import LawApiClient, LawApiError

RUN_ID = "0b6f7a52-6f3e-4c1e-9d1e-3c2b9a8f7e61"


def api_with(handler):
    return LawApiClient("http://api", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def waiting_run(status="awaiting_approval"):
    return {
        "run_id": RUN_ID,
        "status": status,
        "assessment": {
            "high_impact": "yes",
            "high_impact_categories": ["사"],
            "confidence": 0.8,
            "summary": "채용 평가는 고영향",
            "obligations": [{"article": "제34조제1항", "applies": "해당"}],
        },
        "review_request": {"reasons": ["고영향 인공지능 해당"]},
        "report_url": "/reports/x.pdf" if status == "completed" else None,
    }


class LawApiClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_requests_and_errors(self):
        seen = []

        def handler(request):
            seen.append((request.method, request.url.path, json.loads(request.content or b"null")))
            if request.url.path.endswith("/approve"):
                return httpx.Response(409, json={"detail": "승인 대기 상태가 아닙니다: completed"})
            return httpx.Response(200, json={"answer": "ok", "sources": []})

        api = api_with(handler)
        await api.ask("질문입니다", thread_id="discord-1")
        with self.assertRaises(LawApiError) as caught:
            await api.approve(RUN_ID, approved=True, reviewer="kim")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(seen[0], ("POST", "/ask", {"question": "질문입니다", "thread_id": "discord-1"}))
        self.assertEqual(seen[1][2], {"approved": True, "reviewer": "kim", "comment": ""})


@unittest.skipIf(discord is None, "discord.py 미설치 (uv sync --extra discord)")
class DiscordBotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from bots import discord_bot

        self.bot_module = discord_bot

    def test_answer_embed_lists_sources(self):
        embed = self.bot_module.answer_embed(
            "고영향 AI란?",
            {"answer": "x" * 5000, "sources": [{"source_id": "S1", "article": "제2조", "item": "제4호", "title": "정의"}]},
        )
        self.assertLessEqual(len(embed.description), 4000)
        self.assertEqual(embed.fields[0].name, "[S1] 제2조 제4호")

    def test_run_embed(self):
        embed = self.bot_module.run_embed(waiting_run("completed"), public_base_url="https://law.example.com")
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["해당 목"], "사목")
        self.assertEqual(fields["보고서"], "https://law.example.com/reports/x.pdf")

    def test_can_review(self):
        role = SimpleNamespace(id=42)
        self.assertTrue(self.bot_module.can_review(SimpleNamespace(roles=[role]), 42))
        self.assertFalse(self.bot_module.can_review(SimpleNamespace(roles=[]), 42))
        admin = SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=True))
        self.assertTrue(self.bot_module.can_review(admin, None))
        self.assertFalse(self.bot_module.can_review(SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=False)), None))

    async def test_decide_messages(self):
        api = api_with(lambda request: httpx.Response(200, json={**waiting_run("completed")}))
        ok, message = await self.bot_module.decide(api, RUN_ID, approved=True, reviewer="kim")
        self.assertTrue(ok)
        self.assertIn("kim님이 승인", message)
        conflict = api_with(lambda request: httpx.Response(409, json={"detail": "x"}))
        self.assertEqual(
            await self.bot_module.decide(conflict, RUN_ID, approved=False, reviewer="kim"),
            (False, "이미 처리된 실행입니다."),
        )

    async def test_wait_for_run_polls_until_stop(self):
        statuses = iter(["queued", "running", "awaiting_approval"])
        api = api_with(lambda request: httpx.Response(200, json={"run_id": RUN_ID, "status": next(statuses)}))
        run = await self.bot_module.wait_for_run(api, RUN_ID, interval=0)
        self.assertEqual(run["status"], "awaiting_approval")

    def test_button_custom_id_round_trip(self):
        button = self.bot_module.DecisionButton("approve", RUN_ID)
        self.assertEqual(button.item.custom_id, f"compliance:approve:{RUN_ID}")
        match = self.bot_module.DecisionButton.__discord_ui_compiled_template__.fullmatch(button.item.custom_id)
        self.assertEqual((match["action"], match["run_id"]), ("approve", RUN_ID))

    def interaction(self, bot, member):
        return SimpleNamespace(
            client=bot,
            user=member,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_button_callback_checks_permission_then_approves(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json=waiting_run("completed"))

        bot = SimpleNamespace(api=api_with(handler), approver_role_id=7, public_base_url="")
        button = self.bot_module.DecisionButton("approve", RUN_ID)

        outsider = self.interaction(bot, SimpleNamespace(roles=[], display_name="lee"))
        await button.callback(outsider)
        outsider.response.send_message.assert_awaited_once()
        self.assertEqual(calls, [])

        reviewer = self.interaction(bot, SimpleNamespace(roles=[SimpleNamespace(id=7)], display_name="kim"))
        await button.callback(reviewer)
        self.assertEqual(calls, [f"/agents/compliance/runs/{RUN_ID}/approve", f"/agents/compliance/runs/{RUN_ID}"])
        reviewer.edit_original_response.assert_awaited_once()
        self.assertIsNone(reviewer.edit_original_response.await_args.kwargs["view"])

    async def test_bot_registers_commands(self):
        bot = self.bot_module.LawBot(api_with(lambda r: httpx.Response(200, json={})))
        names = sorted(command.name for command in bot.tree.get_commands())
        self.assertEqual(names, ["compliance", "law", "review"])
        await bot.api.close()


if __name__ == "__main__":
    unittest.main()
