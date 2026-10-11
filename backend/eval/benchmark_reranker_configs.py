import asyncio
import gc
import json
import time
from pathlib import Path

import pandas as pd
import torch

from common.ai_model import get_embedding_model
from common.qdrant import get_qdrant_client
from rag.reranker import QwenReranker
from rag.retriever import HybridRetriever
from rag.retry import retry_rate_limit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET_PATH = BACKEND_ROOT / "eval" / "golden_set_v2.jsonl"
OUTPUT_PATH = BACKEND_ROOT / "eval" / "results" / "reranker_config_benchmark.csv"
COLLECTION_NAME = "ai_basic_law_adaptive_anchor_v1"
TOP_K = 5

CONFIGS = (
    {
        "name": "baseline",
        "candidate_k": 20,
        "max_length": 2048,
        "batch_size": 1,
    },
    {
        "name": "recommended",
        "candidate_k": 10,
        "max_length": 768,
        "batch_size": 4,
    },
    {
        "name": "max_speed",
        "candidate_k": 5,
        "max_length": 512,
        "batch_size": 5,
    },
)


def load_definition_items():
    with GOLDEN_SET_PATH.open(encoding="utf-8") as file:
        return [
            item
            for line in file
            if line.strip()
            for item in [json.loads(line)]
            if item.get("type") == "정의"
        ]


def metrics(results_by_question, items):
    hits = []
    recalls = []
    reciprocal_ranks = []
    rankings = []
    for item, results in zip(items, results_by_question):
        articles = HybridRetriever.unique_articles(results[:TOP_K])
        gold = set(item["answer_articles"])
        found = gold.intersection(articles)
        hits.append(float(bool(found)))
        recalls.append(len(found) / len(gold))
        reciprocal_ranks.append(next(
            (1 / rank for rank, article in enumerate(articles, 1) if article in gold),
            0.0,
        ))
        rankings.append(f"{item['id']}:{','.join(articles)}")
    return {
        "Hit@5": sum(hits) / len(hits),
        "Recall@5": sum(recalls) / len(recalls),
        "MRR@5": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "rankings": " | ".join(rankings),
    }


async def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"벤치마크 장치: {device}")
    if device == "cpu":
        print(
            "주의: GPU를 찾지 못했습니다. GPU 성능을 비교하려면 "
            "nvidia-smi와 torch.cuda.is_available()을 먼저 확인하세요."
        )
    items = load_definition_items()
    retriever = HybridRetriever(
        qdrant_client=get_qdrant_client(),
        embedding_client=get_embedding_model(),
        collection_name=COLLECTION_NAME,
        top_k=TOP_K,
        candidate_k=20,
    )
    questions = [item["question"] for item in items]
    vectors = await retry_rate_limit(
        lambda: retriever.embedding_client.aembed_documents(questions),
        label="정의형 질문 Embedding",
        max_retries=100,
        wait_seconds=65,
    )
    retriever.query_embedding_cache.update(zip(questions, vectors))
    candidates = [
        await retriever.search(question, k=20)
        for question in questions
    ]

    rows = []
    for config in CONFIGS:
        reranker = QwenReranker(
            max_length=config["max_length"],
            batch_size=config["batch_size"],
            device=device,
        )
        first_candidates = candidates[0][:config["candidate_k"]]
        started = time.perf_counter()
        reranker.rerank(questions[0], first_candidates, TOP_K)
        cold_ms = (time.perf_counter() - started) * 1000

        results = []
        warm_times = []
        for question, question_candidates in zip(questions, candidates):
            started = time.perf_counter()
            ranked = reranker.rerank(
                question,
                question_candidates[:config["candidate_k"]],
                TOP_K,
            )
            warm_times.append((time.perf_counter() - started) * 1000)
            results.append(ranked)

        rows.append({
            **config,
            **metrics(results, items),
            "cold_ms": round(cold_ms, 2),
            "warm_avg_ms": round(sum(warm_times) / len(warm_times), 2),
            "warm_min_ms": round(min(warm_times), 2),
            "warm_max_ms": round(max(warm_times), 2),
        })
        print(rows[-1])
        del reranker
        gc.collect()

    retriever.client.close()
    result = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    print("\n[비교 결과]")
    print(result.drop(columns=["rankings"]).to_string(index=False))
    print(f"\n저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
