"""Cross-references between articles of the AI Basic Act.

`extract_references` finds `제N조` mentions in an article's text that point into the
same law. Mentions of other laws (`「에너지법」 제2조제1호`) are removed first.
The reference graph lets the agent follow one hop: the articles an article cites and
the articles that cite it (for example 제36조 국내대리인 <- 제43조 과태료).
"""

import re
from collections import defaultdict
from typing import Any

# 「다른 법률」 다음에 붙는 조·항·호 표기(… 제2조제1호부터 제3호까지)를 통째로 지운다.
_UNIT = r"제\s*\d+\s*(?:조|항|호)(?:\s*의\s*\d+)?"
EXTERNAL_REFERENCE = re.compile(
    r"「[^」]*」\s*"
    rf"(?:(?:{_UNIT})+(?:\s*(?:부터|및|ㆍ|·|와|과)\s*(?:같은\s*(?:조|항)\s*)?(?:{_UNIT})+)*(?:\s*까지)?)?"
)
REFERENCE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?")


def article_id(number: int | str, branch: int | str | None = None) -> str:
    return f"제{number}조" + (f"의{branch}" if branch else "")


def extract_references(text: str, self_article: str = "") -> list[dict[str, str]]:
    """References to articles of this law, in order, without duplicates or self-references."""
    cleaned = EXTERNAL_REFERENCE.sub(" ", text or "")
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    own = re.sub(r"\s+", "", self_article)
    for match in REFERENCE.finditer(cleaned):
        target = article_id(match.group(1), match.group(2))
        paragraph = f"제{match.group(3)}항" if match.group(3) else ""
        if target == own or (target, paragraph) in seen:
            continue
        seen.add((target, paragraph))
        found.append({"article": target, "paragraph": paragraph})
    return found


def _content_without_heading(chunk: dict) -> str:
    # 첫 줄 "제36조(국내대리인 지정)"는 자기 자신이므로 빼도 되지만 self 검사로 걸러진다.
    return str(chunk.get("content") or "")


def attach_references(chunks: list[dict]) -> list[dict]:
    """Add a `references` payload (cited article ids) to every chunk, for indexing."""
    for chunk in chunks:
        refs = extract_references(_content_without_heading(chunk), str(chunk.get("article") or ""))
        chunk["references"] = list(dict.fromkeys(ref["article"] for ref in refs))
    return chunks


def reference_rows(chunks: list[dict]) -> list[tuple[str, str, str, str]]:
    """(source_article, target_article, target_paragraph, chunk_key) rows for article_references."""
    rows = []
    for chunk in chunks:
        source = str(chunk.get("article") or "")
        if not source:
            continue
        for ref in extract_references(_content_without_heading(chunk), source):
            rows.append((source, ref["article"], ref["paragraph"], str(chunk.get("chunk_key") or "")))
    return list(dict.fromkeys(rows))


class ReferenceGraph:
    def __init__(self, chunks: list[dict]):
        self.outgoing: dict[str, set[str]] = defaultdict(set)
        self.incoming: dict[str, set[str]] = defaultdict(set)
        self.chunks_by_article: dict[str, list[dict]] = defaultdict(list)
        for chunk in chunks:
            source = re.sub(r"\s+", "", str(chunk.get("article") or ""))
            if not source:
                continue
            self.chunks_by_article[source].append(chunk)
            for ref in extract_references(_content_without_heading(chunk), source):
                if ref["article"] != source:
                    self.outgoing[source].add(ref["article"])
                    self.incoming[ref["article"]].add(source)

    @staticmethod
    def _order(article: str) -> tuple[int, int]:
        match = re.match(r"제(\d+)조(?:의(\d+))?", article)
        return (int(match.group(1)), int(match.group(2) or 0)) if match else (10**6, 0)

    def related(self, article: str, direction: str = "both") -> list[tuple[str, str]]:
        """[(article, relation)], relation is 'cites' or 'cited_by'."""
        result: list[tuple[str, str]] = []
        if direction in {"both", "out"}:
            result += [(a, "cites") for a in sorted(self.outgoing.get(article, ()), key=self._order)]
        if direction in {"both", "in"}:
            result += [(a, "cited_by") for a in sorted(self.incoming.get(article, ()), key=self._order)]
        return result

    def related_chunks(self, article: str, *, direction: str = "both", limit: int = 10) -> list[dict]:
        documents = []
        for target, relation in self.related(article, direction)[:limit]:
            candidates = self.chunks_by_article.get(target, [])
            # 검색 대상(child) 청크를 우선하고, 없으면 부모 청크를 쓴다.
            preferred = [c for c in candidates if c.get("search_enabled") in (True, "True")] or candidates
            for chunk in preferred:
                documents.append({**chunk, "relation": relation, "related_to": article})
        return documents


def graph_for_retriever(retriever: Any) -> ReferenceGraph:
    """Graph over the retriever's chunks, built once per retriever."""
    cached = getattr(retriever, "_reference_graph", None)
    if cached is None:
        cached = ReferenceGraph(list(retriever.chunks_by_key.values()))
        try:
            retriever._reference_graph = cached
        except AttributeError:
            pass
    return cached
