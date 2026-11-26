"""Does one-hop reference expansion help questions that need several articles?

    # LLM·Qdrant 없이: 정답 조문들이 인용 관계 1단계로 이어지는지
    uv run python eval/related_articles_eval.py --offline

    # 실제 검색: SearchLaw top-5 vs top-5 + 인용 1단계 확장의 Recall@5
    uv run python eval/related_articles_eval.py

Questions: golden_set_v2.jsonl entries with two or more answer_articles.
Expanded Recall@5 keeps the top-5 search articles and adds the one-hop neighbours of
the top-1 article (at most 5 added), so it shows what a GetRelatedArticles call adds.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.chunker import AdaptiveLawChunker  # noqa: E402
from rag.loader import LawXMLLoader  # noqa: E402
from rag.references import ReferenceGraph  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden_set_v2.jsonl"
XML = Path(__file__).resolve().parents[1] / "data" / "ai_basic_law" / "ai_basic_law.xml"


def multi_evidence_cases() -> list[dict]:
    with open(GOLDEN, encoding="utf-8") as file:
        cases = [json.loads(line) for line in file if line.strip()]
    return [case for case in cases if len(case.get("answer_articles", [])) > 1]


def offline_graph() -> ReferenceGraph:
    loader = LawXMLLoader(XML)
    root = loader.load()
    return ReferenceGraph(AdaptiveLawChunker().chunk(root, loader.metadata(root)))


def reachability(cases: list[dict], graph: ReferenceGraph) -> list[dict]:
    rows = []
    for case in cases:
        answers = case["answer_articles"]
        linked = sorted(
            {
                (a, b)
                for a in answers
                for b in answers
                if a < b and (b in {x for x, _ in graph.related(a)})
            }
        )
        rows.append({"id": case["id"], "answers": answers, "linked_pairs": linked})
    return rows


def recall(found: list[str], answers: list[str]) -> float:
    return len(set(found) & set(answers)) / len(answers)


async def search_recall(cases: list[dict]) -> list[dict]:
    from rag.pipeline import RAGPipeline

    pipeline = RAGPipeline.create_default()
    graph = ReferenceGraph(list(pipeline.retriever.chunks_by_key.values()))
    rows = []
    try:
        for case in cases:
            results = await pipeline.retrieve(case["question"], k=5)
            top = list(dict.fromkeys(str(doc.get("article") or "") for doc in results))[:5]
            neighbours = [article for article, _ in graph.related(top[0])][:5] if top else []
            expanded = list(dict.fromkeys(top + neighbours))
            rows.append(
                {
                    "id": case["id"],
                    "answers": case["answer_articles"],
                    "top5": top,
                    "added": [a for a in expanded if a not in top],
                    "recall_base": recall(top, case["answer_articles"]),
                    "recall_expanded": recall(expanded, case["answer_articles"]),
                }
            )
    finally:
        pipeline.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    cases = multi_evidence_cases()
    if args.offline:
        rows = reachability(cases, offline_graph())
        print("| 문항 | 정답 조문 | 1단계 인용으로 이어진 쌍 |\n|---|---|---|")
        for row in rows:
            pairs = ", ".join(f"{a}↔{b}" for a, b in row["linked_pairs"]) or "-"
            print(f"| {row['id']} | {', '.join(row['answers'])} | {pairs} |")
        linked = sum(bool(row["linked_pairs"]) for row in rows)
        print(f"\n복수 근거 {len(rows)}문항 중 {linked}문항이 인용 1단계로 연결됨")
        return
    rows = asyncio.run(search_recall(cases))
    print("| 문항 | 정답 | 검색 top-5 | 확장으로 추가 | Recall@5 | 확장 Recall |\n|---|---|---|---|---|---|")
    for row in rows:
        print(
            f"| {row['id']} | {', '.join(row['answers'])} | {', '.join(row['top5'])} | "
            f"{', '.join(row['added']) or '-'} | {row['recall_base']:.2f} | {row['recall_expanded']:.2f} |"
        )
    base = sum(r["recall_base"] for r in rows) / len(rows)
    expanded = sum(r["recall_expanded"] for r in rows) / len(rows)
    print(f"\n평균 Recall@5 {base:.3f} -> 확장 {expanded:.3f}")


if __name__ == "__main__":
    main()
