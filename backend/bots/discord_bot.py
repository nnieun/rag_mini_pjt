"""Discord bot for the AI Basic Act service.

    uv sync --extra discord
    uv run python -m bots.discord_bot

Commands
- /law <질문>: calls POST /ask and shows the answer with its source articles.
- /compliance <서비스 설명>: starts a compliance run and reports the verdict.
- /review <run_id>: shows a run waiting for approval with Approve / Reject buttons.

Buttons survive bot restarts (custom_id carries the run id). Only members with the
role DISCORD_APPROVER_ROLE_ID, or with Manage Server when no role is configured,
can approve or reject.

Settings (.env only, never committed): DISCORD_BOT_TOKEN, LAW_API_BASE_URL,
DISCORD_GUILD_ID (optional, syncs commands to one server instantly),
DISCORD_APPROVER_ROLE_ID (optional).
"""

import asyncio
import logging
import os
import re
from typing import Any

import discord
from discord import app_commands

from bots.law_client import LawApiClient, LawApiError

logger = logging.getLogger(__name__)

EMBED_LIMIT = 4000
POLL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 300.0
COLORS = {
    "answered": 0x1565C0,
    "completed": 0x2E7D32,
    "awaiting_approval": 0xF9A825,
    "rejected": 0x6D4C41,
    "failed": 0xC62828,
}
HIGH_IMPACT_TEXT = {"yes": "해당", "no": "해당 없음", "uncertain": "판단 보류"}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def answer_embed(question: str, answer: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=_truncate(question, 250),
        description=_truncate(str(answer.get("answer") or ""), EMBED_LIMIT),
        color=COLORS["answered"],
    )
    for source in (answer.get("sources") or [])[:5]:
        label = " ".join(
            str(source[key]) for key in ("article", "paragraph", "item") if source.get(key)
        ) or source.get("source_id", "")
        embed.add_field(
            name=_truncate(f"[{source.get('source_id', '')}] {label}", 250),
            value=_truncate(str(source.get("title") or source.get("content") or "-"), 1000),
            inline=False,
        )
    embed.set_footer(text="AI 기본법 원문 기반 답변 · 법률 자문 아님")
    return embed


def run_embed(run: dict[str, Any], *, public_base_url: str = "") -> discord.Embed:
    assessment = run.get("assessment") or {}
    status = str(run.get("status") or "")
    embed = discord.Embed(
        title=f"AI 기본법 점검 · {status}",
        description=_truncate(str(assessment.get("summary") or ""), EMBED_LIMIT),
        color=COLORS.get(status, COLORS["answered"]),
    )
    embed.add_field(name="고영향 인공지능", value=HIGH_IMPACT_TEXT.get(assessment.get("high_impact"), "-"))
    embed.add_field(
        name="해당 목", value=", ".join(f"{c}목" for c in assessment.get("high_impact_categories") or []) or "-"
    )
    embed.add_field(name="신뢰도", value=f"{float(assessment.get('confidence') or 0):.2f}")
    applicable = [
        item.get("article", "")
        for item in assessment.get("obligations") or []
        if item.get("applies") in {"해당", "해당 가능"}
    ]
    embed.add_field(name="해당 의무", value=_truncate(", ".join(applicable) or "-", 1000), inline=False)
    request = run.get("review_request") or {}
    if request.get("reasons"):
        embed.add_field(name="검토 사유", value=", ".join(request["reasons"]), inline=False)
    if run.get("report_url"):
        base = public_base_url.rstrip("/")
        embed.add_field(name="보고서", value=f"{base}{run['report_url']}" if base else run["report_url"], inline=False)
    embed.set_footer(text=f"run {run.get('run_id', '')} · 법률 자문 아님")
    return embed


def can_review(member: Any, approver_role_id: int | None) -> bool:
    """Approver role if configured, otherwise the Manage Server permission."""
    if approver_role_id:
        return any(getattr(role, "id", None) == approver_role_id for role in getattr(member, "roles", []))
    permissions = getattr(member, "guild_permissions", None)
    return bool(getattr(permissions, "manage_guild", False))


async def decide(api: LawApiClient, run_id: str, *, approved: bool, reviewer: str) -> tuple[bool, str]:
    """Send the decision; return (ok, message for the user)."""
    try:
        run = await api.approve(run_id, approved=approved, reviewer=reviewer)
    except LawApiError as error:
        if error.status_code == 409:
            return False, "이미 처리된 실행입니다."
        if error.status_code == 404:
            return False, "실행을 찾을 수 없습니다."
        return False, f"처리하지 못했습니다: {error.detail}"
    verdict = "승인" if approved else "반려"
    return True, f"{reviewer}님이 {verdict}했습니다. 상태: {run.get('status')}"


async def wait_for_run(api: LawApiClient, run_id: str, *, timeout: float = POLL_TIMEOUT_SECONDS,
                       interval: float = POLL_SECONDS) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        run = await api.get_run(run_id)
        if run.get("status") in {"awaiting_approval", "completed", "rejected", "failed"}:
            return run
        if asyncio.get_running_loop().time() >= deadline:
            return run
        await asyncio.sleep(interval)


class DecisionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"compliance:(?P<action>approve|reject):(?P<run_id>[0-9a-f-]{36})"):
    def __init__(self, action: str, run_id: str):
        approve = action == "approve"
        super().__init__(
            discord.ui.Button(
                label="승인" if approve else "반려",
                style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
                custom_id=f"compliance:{action}:{run_id}",
            )
        )
        self.action = action
        self.run_id = run_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], match["run_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LawBot = interaction.client  # type: ignore[assignment]
        if not can_review(interaction.user, bot.approver_role_id):
            await interaction.response.send_message("승인 권한이 없습니다.", ephemeral=True)
            return
        await interaction.response.defer()
        ok, message = await decide(
            bot.api, self.run_id, approved=self.action == "approve", reviewer=interaction.user.display_name
        )
        if ok:
            run = await bot.api.get_run(self.run_id)
            await interaction.edit_original_response(embed=run_embed(run, public_base_url=bot.public_base_url), view=None)
        await interaction.followup.send(message, ephemeral=not ok)


def decision_view(run_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DecisionButton("approve", run_id))
    view.add_item(DecisionButton("reject", run_id))
    return view


class LawBot(discord.Client):
    def __init__(self, api: LawApiClient, *, guild_id: int | None = None, approver_role_id: int | None = None,
                 public_base_url: str = ""):
        super().__init__(intents=discord.Intents.default())
        self.api = api
        self.guild_id = guild_id
        self.approver_role_id = approver_role_id
        self.public_base_url = public_base_url
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DecisionButton)
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self) -> None:
        await self.api.close()
        await super().close()


def register_commands(bot: LawBot) -> None:
    @bot.tree.command(name="law", description="AI 기본법에 질문하고 근거 조문과 함께 답을 받습니다")
    @app_commands.describe(question="질문")
    async def law(interaction: discord.Interaction, question: app_commands.Range[str, 2, 1000]) -> None:
        await interaction.response.defer(thinking=True)
        try:
            # 같은 채널의 대화는 같은 thread_id로 이어진다(서버 체크포인터).
            answer = await bot.api.ask(question, thread_id=f"discord-{interaction.channel_id}")
        except LawApiError as error:
            await interaction.followup.send(f"답변하지 못했습니다: {error.detail}")
            return
        await interaction.followup.send(embed=answer_embed(question, answer))

    @bot.tree.command(name="compliance", description="AI 서비스 설명으로 AI 기본법 준수 점검을 실행합니다")
    @app_commands.describe(description="서비스 설명")
    async def compliance(interaction: discord.Interaction, description: app_commands.Range[str, 10, 4000]) -> None:
        await interaction.response.defer(thinking=True)
        try:
            started = await bot.api.start_compliance(description)
            run = await wait_for_run(bot.api, started["run_id"])
        except LawApiError as error:
            await interaction.followup.send(f"점검을 시작하지 못했습니다: {error.detail}")
            return
        view = decision_view(run["run_id"]) if run.get("status") == "awaiting_approval" else discord.utils.MISSING
        await interaction.followup.send(embed=run_embed(run, public_base_url=bot.public_base_url), view=view)

    @bot.tree.command(name="review", description="승인 대기 중인 점검을 승인 버튼과 함께 보여줍니다")
    @app_commands.describe(run_id="실행 ID")
    async def review(interaction: discord.Interaction, run_id: str) -> None:
        try:
            run = await bot.api.get_run(run_id.strip())
        except LawApiError as error:
            await interaction.response.send_message(f"실행을 찾지 못했습니다: {error.detail}", ephemeral=True)
            return
        view = decision_view(run["run_id"]) if run.get("status") == "awaiting_approval" else discord.utils.MISSING
        await interaction.response.send_message(embed=run_embed(run, public_base_url=bot.public_base_url), view=view)


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else None


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN이 .env에 없습니다.")
    bot = LawBot(
        LawApiClient(os.getenv("LAW_API_BASE_URL", "http://localhost:8000")),
        guild_id=_optional_int("DISCORD_GUILD_ID"),
        approver_role_id=_optional_int("DISCORD_APPROVER_ROLE_ID"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", ""),
    )
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
