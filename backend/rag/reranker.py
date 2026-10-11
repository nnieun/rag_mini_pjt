from typing import Any


class QwenReranker:
    """선택적으로 사용하는 로컬 CrossEncoder 재정렬기."""

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-Reranker-0.6B",
        max_length: int = 2048,
        batch_size: int = 1,
        device: str | None = None,
    ):
        self.model_id = model_id
        self.max_length = max_length
        self.batch_size = batch_size
        self.device = device
        self._model: Any | None = None

    def _load(self):
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            device = self.device or (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
            self._model = CrossEncoder(
                self.model_id,
                device=device,
                max_length=self.max_length,
            )
        return self._model

    def rerank(
        self,
        question: str,
        candidates: list[dict],
        k: int = 5,
    ) -> list[dict]:
        if not candidates:
            return []
        model = self._load()
        pairs = [
            (question, searchable_candidate(document))
            for document in candidates
        ]
        scores = model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        scored = [
            {**document, "rerank_score": float(score)}
            for document, score in zip(candidates, scores)
        ]
        return sorted(
            scored,
            key=lambda document: document["rerank_score"],
            reverse=True,
        )[:k]

    def warmup(self) -> None:
        """서버 시작 시 모델 로딩과 첫 추론 비용을 미리 지불합니다."""
        model = self._load()
        model.predict(
            [("인공지능이란 무엇인가요?", "인공지능의 정의")],
            batch_size=1,
            show_progress_bar=False,
        )


def searchable_candidate(document: dict) -> str:
    return "\n".join(
        filter(
            None,
            [
                " ".join(
                    str(document.get(field) or "")
                    for field in (
                        "article",
                        "paragraph",
                        "item",
                        "subitem",
                        "title",
                    )
                ),
                str(document.get("content") or ""),
            ],
        )
    )
