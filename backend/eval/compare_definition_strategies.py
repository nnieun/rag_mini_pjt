import asyncio
import json
import time
from pathlib import Path

import pandas as pd

from common.ai_model import get_embedding_model
from common.qdrant import get_qdrant_client
from rag.reranker import QwenReranker
from rag.retriever import (
    HybridRetriever,
    apply_definition_metadata_ranking,
    is_definition_query,
    reciprocal_rank_fusion,
)
from rag.retry import retry_rate_limit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET_PATH = BACKEND_ROOT / "eval" / "golden_set_v2.jsonl"
OUTPUT_DIR = BACKEND_ROOT / "eval" / "results"
COLLECTION_NAME = "ai_basic_law_adaptive_anchor_v1"
TOP_K = 5
CANDIDATE_K = 20


def load_golden_set():
    with GOLDEN_SET_PATH.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def get_gold_articles(item):
    key = "answer_articles" if item.get("answerable", True) else "related_articles"
    return item.get(key, [])


def retrieval_metrics(results, gold):
    retrieved = HybridRetriever.unique_articles(results[:TOP_K])
    if not gold:
        return {"Hit@5": None, "Recall@5": None, "MRR@5": None,
                "retrieved_articles": retrieved}
    gold_set = set(gold)
    found = gold_set.intersection(retrieved)
    reciprocal_rank = next(
        (1 / rank for rank, article in enumerate(retrieved, 1)
         if article in gold_set),
        0.0,
    )
    return {
        "Hit@5": float(bool(found)),
        "Recall@5": len(found) / len(gold_set),
        "MRR@5": reciprocal_rank,
        "retrieved_articles": retrieved,
    }


def combine_rankings(metadata_results, reranked_results):
    return reciprocal_rank_fusion([metadata_results, reranked_results])


async def prefetch_embeddings(retriever, questions):
    vectors = await retry_rate_limit(
        lambda: retriever.embedding_client.aembed_documents(questions),
        label="Golden Set Embedding",
        max_retries=100,
        wait_seconds=65,
    )
    retriever.query_embedding_cache.update(zip(questions, vectors))


async def evaluate():
    golden_set = load_golden_set()
    retriever = HybridRetriever(
        qdrant_client=get_qdrant_client(),
        embedding_client=get_embedding_model(),
        collection_name=COLLECTION_NAME,
        top_k=TOP_K,
        candidate_k=CANDIDATE_K,
    )
    reranker = QwenReranker()
    await prefetch_embeddings(retriever, [item["question"] for item in golden_set])

    rows = []
    for index, item in enumerate(golden_set, 1):
        question = item["question"]
        definition_query = is_definition_query(question)

        started = time.perf_counter()
        baseline = await retriever.search(question, CANDIDATE_K)
        baseline_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        metadata = apply_definition_metadata_ranking(question, baseline)
        metadata_ms = (time.perf_counter() - started) * 1000

        rerank_ms = 0.0
        reranked = baseline
        combined = metadata
        if definition_query:
            started = time.perf_counter()
            reranked = await asyncio.to_thread(
                reranker.rerank, question, baseline, CANDIDATE_K
            )
            rerank_ms = (time.perf_counter() - started) * 1000
            combined = combine_rankings(metadata, reranked)

        methods = {
            "Hybrid": (baseline, baseline_ms),
            "Hybrid+DefinitionMetadata": (metadata, baseline_ms + metadata_ms),
            "Hybrid+ConditionalRerank": (reranked, baseline_ms + rerank_ms),
            "Hybrid+Metadata+ConditionalRerank": (
                combined, baseline_ms + metadata_ms + rerank_ms
            ),
        }
        for method, (results, elapsed_ms) in methods.items():
            rows.append({
                "question_id": item["id"],
                "question_type": item.get("type", ""),
                "definition_query": definition_query,
                "method": method,
                **retrieval_metrics(results, get_gold_articles(item)),
                "elapsed_ms": elapsed_ms,
            })
        print(f"[{index}/{len(golden_set)}] {item['id']} 완료")

    detail = pd.DataFrame(rows)
    columns = ["Hit@5", "Recall@5", "MRR@5", "elapsed_ms"]
    overall = detail.groupby("method", sort=False)[columns].mean().reset_index()
    definition = (
        detail[detail["question_type"] == "정의"]
        .groupby("method", sort=False)[columns]
        .mean()
        .reset_index()
    )
    return detail, overall, definition


async def main():
    detail, overall, definition = await evaluate()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    detail.to_csv(OUTPUT_DIR / "definition_strategy_detail.csv", index=False)
    overall.to_csv(OUTPUT_DIR / "definition_strategy_overall.csv", index=False)
    definition.to_csv(OUTPUT_DIR / "definition_strategy_definition.csv", index=False)
    print("\n[전체 45문항]")
    print(overall.to_string(index=False))
    print("\n[정의형 5문항]")
    print(definition.to_string(index=False))
    print(f"\n결과 저장: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
