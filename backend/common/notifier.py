"""Outbound notifications (Discord webhook first, Slack later behind the same interface).

A notifier must never break the work that triggered it: `notify_safely` records the
attempt as a tool call (`channel='notify'`) in the active RequestTrace and swallows
errors.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx

from common.telemetry import tool_call_scope

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    title: str
    summary: str = ""
    status: str = "info"  # completed | awaiting_approval | rejected | failed | info
    url: str | None = None
    fields: list[tuple[str, str]] = field(default_factory=list)
    footer: str = ""


class Notifier(Protocol):
    name: str

    async def notify(self, notification: Notification) -> None: ...


class NullNotifier:
    name = "none"

    async def notify(self, notification: Notification) -> None:
        return None


STATUS_COLORS = {
    "completed": 0x2E7D32,
    "awaiting_approval": 0xF9A825,
    "rejected": 0x6D4C41,
    "failed": 0xC62828,
    "info": 0x1565C0,
}


class DiscordWebhookNotifier:
    """Posts one embed to a Discord channel webhook."""

    name = "DiscordWebhook"

    def __init__(self, webhook_url: str, *, client: httpx.AsyncClient | None = None, timeout: float = 10.0):
        if not webhook_url.startswith("https://"):
            raise ValueError("Discord 웹훅 URL은 https://로 시작해야 합니다.")
        self.webhook_url = webhook_url
        self.client = client
        self.timeout = timeout

    def payload(self, notification: Notification) -> dict:
        embed = {
            "title": notification.title[:256],
            "description": notification.summary[:4000],
            "color": STATUS_COLORS.get(notification.status, STATUS_COLORS["info"]),
            "fields": [
                {"name": name[:256], "value": (value or "-")[:1024], "inline": True}
                for name, value in notification.fields[:25]
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if notification.url:
            embed["url"] = notification.url
        if notification.footer:
            embed["footer"] = {"text": notification.footer[:2048]}
        # 멘션으로 사람을 호출하지 않는다.
        return {"username": "AI 기본법 점검", "embeds": [embed], "allowed_mentions": {"parse": []}}

    async def notify(self, notification: Notification) -> None:
        payload = self.payload(notification)
        if self.client is not None:
            response = await self.client.post(self.webhook_url, json=payload, timeout=self.timeout)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=self.timeout)
        response.raise_for_status()


def notifier_from_env() -> Notifier:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return NullNotifier()
    try:
        return DiscordWebhookNotifier(url)
    except ValueError as error:
        logger.warning("알림을 끕니다: %s", error)
        return NullNotifier()


async def notify_safely(notifier: Notifier, notification: Notification) -> bool:
    """Send and report success. Failures are logged and kept in tool_calls only."""
    if isinstance(notifier, NullNotifier):
        return False
    try:
        async with tool_call_scope(notifier.name, channel="notify"):
            await notifier.notify(notification)
    except Exception as error:
        logger.warning("알림 전송 실패(%s): %s", notifier.name, type(error).__name__)
        return False
    return True
