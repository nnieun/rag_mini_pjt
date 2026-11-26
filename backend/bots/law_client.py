"""Small async client for the backend API, used by chat bots."""

from typing import Any

import httpx


class LawApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class LawApiClient:
    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None, timeout: float = 150.0):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise LawApiError(response.status_code, str(detail))
        return response.json()

    async def ask(self, question: str, *, thread_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if thread_id:
            payload["thread_id"] = thread_id[:100]
        return await self._request("POST", "/ask", json=payload)

    async def start_compliance(self, description: str) -> dict[str, Any]:
        return await self._request("POST", "/agents/compliance/runs", json={"description": description})

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/agents/compliance/runs/{run_id}")

    async def approve(self, run_id: str, *, approved: bool, reviewer: str, comment: str = "") -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/agents/compliance/runs/{run_id}/approve",
            json={"approved": approved, "reviewer": reviewer[:100], "comment": comment[:2000]},
        )
