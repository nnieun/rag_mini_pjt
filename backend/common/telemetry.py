from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4


@dataclass
class RequestTrace:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=perf_counter)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_model_call(self, response: Any, purpose: str, elapsed_ms: float) -> None:
        usage = getattr(response, "usage_metadata", None) or {}
        self.model_calls.append(
            {
                "purpose": purpose,
                "elapsed_ms": round(elapsed_ms, 2),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        )

    @property
    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.started_at) * 1000, 2)
