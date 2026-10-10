import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


def is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "429" in message
        or "rate limit" in message
        or "rate_limit" in message
    )


async def retry_rate_limit(
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    max_retries: int = 3,
    wait_seconds: int = 65,
) -> T:
    if max_retries < 1:
        raise ValueError("max_retries는 1 이상이어야 합니다.")
    for attempt in range(1, max_retries + 1):
        try:
            return await operation()
        except Exception as error:
            if not is_rate_limit_error(error) or attempt == max_retries:
                raise
            print(
                f"{label} Rate Limit: {wait_seconds}초 후 재시도 "
                f"({attempt}/{max_retries - 1})"
            )
            await asyncio.sleep(wait_seconds)
    raise RuntimeError(f"{label} 호출에 실패했습니다.")
