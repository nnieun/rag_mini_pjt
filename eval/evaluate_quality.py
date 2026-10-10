import argparse
import asyncio
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from common.ai_model import get_llm_model
from rag.pipeline import RAGPipeline, is_abstention
from rag.retry import retry_rate_limit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_SET = ROOT / "eval" / "golden_set_v2.jsonl"
DEFAULT_RESULT_DIR = ROOT / "eval" / "results"


@dataclass
class JudgeScore:
    correctness: int
    relevance: int
    faithfulness: int
    hallucination: bool
    reason: str


def load_golden_set(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def parse_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Judge JSON을 찾지 못했습니다: {text[:300]}")
    return json.loads(match.group())


async def judge_answer(
    judge: Any,
    item: dict[str, Any],
    answer: str,
    sources: list[dict[str, str]],
    *,
    max_retries: int,
    wait_seconds: int,
) -> JudgeScore:
    evidence = "\n\n".join(
        f"[{source['source_id']}] {source['article']} {source['title']}\n"
        f"{source['content']}"
        for source in sources
    )[:16000]
    prompt = f"""다음 AI 기본법 답변을 평가하세요.

질문: {item['question']}
정답 핵심: {json.dumps(item['answer_points'], ensure_ascii=False)}
정답 조문: {json.dumps(item['answer_articles'], ensure_ascii=False)}
답변: {answer}
검색 근거:
{evidence}

0~2 정수로 채점하세요.
- correctness: 핵심 내용과 조건의 정확성
- relevance: 질문에 직접 답하는 정도
- faithfulness: 답변의 핵심 주장이 검색 근거로 뒷받침되는 정도
- hallucination: 검색 근거에 없는 법률 사실을 단정했으면 true

JSON 객체만 출력하세요:
{{"correctness": 0, "relevance": 0, "faithfulness": 0,
  "hallucination": false, "reason": "간단한 근거"}}
"""
    response = await retry_rate_limit(
        lambda: judge.ainvoke(
            [
                ("system", "당신은 법률 RAG 평가자입니다. 반드시 JSON만 출력하세요."),
                ("human", prompt),
            ]
        ),
        label="LLM Judge",
        max_retries=max_retries,
        wait_seconds=wait_seconds,
    )
    parsed = parse_json_object(str(response.content))
    scores = {
        name: max(0, min(2, int(parsed[name])))
        for name in ("correctness", "relevance", "faithfulness")
    }
    return JudgeScore(
        **scores,
        hallucination=bool(parsed["hallucination"]),
        reason=str(parsed.get("reason", "")),
    )


async def evaluate_answer_quality(
    pipeline: RAGPipeline,
    judge: Any,
    items: list[dict[str, Any]],
    *,
    use_reranking: bool,
) -> list[dict[str, Any]]:
    rows = []
    for index, item in enumerate(items, start=1):
        result = await pipeline.answer(
            item["question"],
            use_reranking=use_reranking,
        )
        source_dicts = [source.as_dict() for source in result.sources]
        score = await judge_answer(
            judge,
            item,
            result.answer,
            source_dicts,
            max_retries=pipeline.max_retries,
            wait_seconds=pipeline.retry_wait_seconds,
        )
        rows.append(
            {
                "question_id": item["id"],
                "question": item["question"],
                "method": result.method,
                "correctness": score.correctness,
                "relevance": score.relevance,
                "faithfulness": score.faithfulness,
                "hallucination": score.hallucination,
                "judge_reason": score.reason,
                "answer": result.answer,
                "gold_articles": json.dumps(item["answer_articles"], ensure_ascii=False),
                "retrieved_articles": json.dumps(result.retrieved_articles, ensure_ascii=False),
                "sources": json.dumps(source_dicts, ensure_ascii=False),
            }
        )
        print(f"[답변 평가 {index}/{len(items)}] {item['id']} 완료")
    return rows


async def evaluate_abstention(
    pipeline: RAGPipeline,
    items: list[dict[str, Any]],
    *,
    use_reranking: bool,
) -> list[dict[str, Any]]:
    rows = []
    for index, item in enumerate(items, start=1):
        result = await pipeline.answer(
            item["question"],
            use_reranking=use_reranking,
        )
        abstained = is_abstention(result.answer)
        rows.append(
            {
                "question_id": item["id"],
                "question": item["question"],
                "expected_abstention": True,
                "abstained": abstained,
                "correct": abstained,
                "answer": result.answer,
                "retrieved_articles": json.dumps(result.retrieved_articles, ensure_ascii=False),
            }
        )
        print(f"[Abstention {index}/{len(items)}] {item['id']} 완료: {abstained}")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="AI 기본법 답변 및 Abstention 평가")
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--answer-count", type=int, default=10)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    args = parser.parse_args()
    if args.answer_count < 10:
        raise ValueError("답변 품질 평가는 최소 10문항이어야 합니다.")

    golden_set = load_golden_set(args.golden_set)
    answer_items = [item for item in golden_set if item["answerable"]][
        : args.answer_count
    ]
    abstention_items = [
        item
        for item in golden_set
        if not item["answerable"] and item.get("added_in") == "v2"
    ]
    if len(abstention_items) != 5:
        raise ValueError(f"v2 범위 밖 질문은 5개여야 합니다: {len(abstention_items)}개")

    pipeline = RAGPipeline.create_default()
    judge = get_llm_model(max_tokens=500)
    try:
        answer_rows = await evaluate_answer_quality(
            pipeline,
            judge,
            answer_items,
            use_reranking=args.rerank,
        )
        abstention_rows = await evaluate_abstention(
            pipeline,
            abstention_items,
            use_reranking=args.rerank,
        )
    finally:
        pipeline.close()

    args.result_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    answer_path = args.result_dir / f"answer_quality_{timestamp}.csv"
    abstention_path = args.result_dir / f"abstention_{timestamp}.csv"
    summary_path = args.result_dir / f"quality_summary_{timestamp}.json"
    write_csv(answer_path, answer_rows)
    write_csv(abstention_path, abstention_rows)

    summary = {
        "judge": "LLM Judge (human review required)",
        "answer_question_count": len(answer_rows),
        "average_correctness": sum(row["correctness"] for row in answer_rows) / len(answer_rows),
        "average_relevance": sum(row["relevance"] for row in answer_rows) / len(answer_rows),
        "average_faithfulness": sum(row["faithfulness"] for row in answer_rows) / len(answer_rows),
        "hallucination_rate": sum(row["hallucination"] for row in answer_rows) / len(answer_rows),
        "abstention_question_count": len(abstention_rows),
        "abstention_accuracy": sum(row["correct"] for row in abstention_rows) / len(abstention_rows),
        "answer_csv": str(answer_path),
        "abstention_csv": str(abstention_path),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"요약 저장: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
