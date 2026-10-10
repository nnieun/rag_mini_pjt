from collections import Counter
import re
import uuid
import xml.etree.ElementTree as ET

from rag.loader import LawMetadata
from rag.models import LawNode


CHAPTER_RE = re.compile(r"^제\d+장")
SECTION_RE = re.compile(r"^제\d+[절관]")


def clean(value: str | None) -> str:
    return " ".join((value or "").split())


def direct_text(element: ET.Element, tag: str) -> str:
    return clean(element.findtext(f"./{tag}", ""))


def digits(value: str | None) -> str | None:
    found = re.sub(r"\D", "", value or "")
    return found or None


def paragraph_no(value: str | None) -> str | None:
    value = (value or "").strip()
    if len(value) == 1 and 0x2460 <= ord(value) <= 0x2473:
        return str(ord(value) - 0x2460 + 1)
    return digits(value)


def stable_point_id(chunk_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_key))


class AdaptiveLawChunker:
    """조·항·호·목 구조를 우선하는 Parent/Child/Anchor 청커."""

    def __init__(
        self,
        max_chars: int = 800,
        overlap: int = 80,
        law_version: str = "282791",
    ):
        if max_chars < 100:
            raise ValueError("max_chars는 100 이상이어야 합니다.")
        if overlap < 0 or overlap >= max_chars:
            raise ValueError("overlap은 0 이상 max_chars 미만이어야 합니다.")
        self.max_chars = max_chars
        self.overlap = overlap
        self.law_version = law_version

    def build_tree(self, unit: ET.Element) -> LawNode:
        def make_subitems(item: ET.Element) -> list[LawNode]:
            return [
                LawNode(
                    "subitem",
                    direct_text(mok, "목내용"),
                    direct_text(mok, "목번호").strip(". ") or None,
                )
                for mok in item.findall("./목")
            ]

        def make_items(parent: ET.Element) -> list[LawNode]:
            return [
                LawNode(
                    "item",
                    direct_text(item, "호내용"),
                    digits(direct_text(item, "호번호")),
                    direct_text(item, "호가지번호") or None,
                    make_subitems(item),
                )
                for item in parent.findall("./호")
            ]

        article = LawNode(
            "article",
            direct_text(unit, "조문내용"),
            direct_text(unit, "조문번호"),
            direct_text(unit, "조문가지번호") or None,
        )
        for paragraph in unit.findall("./항"):
            article.children.append(
                LawNode(
                    "paragraph",
                    direct_text(paragraph, "항내용"),
                    paragraph_no(direct_text(paragraph, "항번호")),
                    children=make_items(paragraph),
                )
            )
        article.children.extend(make_items(unit))
        return article

    def render(self, node: LawNode) -> str:
        lines = [node.own] if node.own else []
        for child in node.children:
            child_text = self.render(child)
            if child_text:
                lines.append(child_text)
        return "\n".join(lines)

    def split_leaf(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text]
        step = self.max_chars - self.overlap
        return [
            text[start : start + self.max_chars]
            for start in range(0, len(text), step)
        ]

    @staticmethod
    def article_label(node: LawNode) -> str:
        return f"제{node.no}조" + (f"의{node.branch}" if node.branch else "")

    @staticmethod
    def location_segment(node: LawNode) -> str:
        if node.level == "paragraph":
            return f"{node.no}항" if node.no else ""
        if node.level == "item":
            return f"{node.no}" + (f"의{node.branch}" if node.branch else "") + "호"
        if node.level == "subitem":
            return f"{node.no}목" if node.no else ""
        return ""

    def chunk(
        self,
        root: ET.Element,
        metadata: LawMetadata,
    ) -> list[dict]:
        common = {
            "law_name": metadata.law_name,
            "law_id": metadata.law_id,
            "law_version": self.law_version,
            "promulgation_no": metadata.promulgation_no,
            "promulgation_date": metadata.promulgation_date,
            "enforce_date": metadata.enforce_date,
            "source": metadata.source,
        }
        chunks: list[dict] = []
        chapter = section = None

        def add(
            content: str,
            search_text: str,
            chunk_metadata: dict,
            chunk_key: str,
        ) -> None:
            if not content.strip():
                return
            chunks.append(
                {
                    "point_id": stable_point_id(chunk_key),
                    "chunk_key": chunk_key,
                    "content": content,
                    "search_text": search_text,
                    **common,
                    **chunk_metadata,
                }
            )

        for unit in root.findall("./조문/조문단위"):
            if direct_text(unit, "조문여부") == "전문":
                heading = direct_text(unit, "조문내용")
                if CHAPTER_RE.match(heading):
                    chapter, section = heading, None
                elif SECTION_RE.match(heading):
                    section = heading
                continue

            article = self.build_tree(unit)
            article_name = self.article_label(article)
            title = direct_text(unit, "조문제목")
            title_label = f"{article_name}({title})" if title else article_name
            full_text = self.render(article)
            article_key = (
                f"{self.law_version}:{metadata.law_id}:{article_name}"
            )
            parent_key = f"{article_key}:parent"
            parent_point_id = stable_point_id(parent_key)
            base = {
                "source_type": "article",
                "chapter": chapter,
                "section": section,
                "article": article_name,
                "article_no": article.no,
                "article_branch_no": article.branch,
                "title": title,
            }

            def path_metadata(path: list[LawNode], role: str) -> dict:
                paragraph = next(
                    (node.no for node in path if node.level == "paragraph"),
                    None,
                )
                item = next(
                    (node.no for node in path if node.level == "item"),
                    None,
                )
                subitem = next(
                    (node.no for node in path if node.level == "subitem"),
                    None,
                )
                return {
                    **base,
                    "unit_level": path[-1].level,
                    "chunk_role": role,
                    "search_enabled": role in {"child", "anchor"},
                    "paragraph": f"{paragraph}항" if paragraph else "",
                    "paragraph_no": paragraph,
                    "item": f"{item}호" if item else "",
                    "item_no": item,
                    "subitem": f"{subitem}목" if subitem else "",
                    "subitem_no": subitem,
                    "parent_id": parent_key,
                    "parent_point_id": parent_point_id,
                }

            def make_search_text(path: list[LawNode], body: str) -> str:
                location = " > ".join(
                    filter(
                        None,
                        [
                            metadata.law_name,
                            chapter,
                            section,
                            title_label,
                            *[
                                self.location_segment(node)
                                for node in path[1:]
                            ],
                        ],
                    )
                )
                ancestors = [node.own for node in path[:-1] if node.own]
                context = "\n".join(ancestors[-2:])
                return "\n".join(filter(None, [location, context, body]))

            if len(full_text) <= self.max_chars:
                key = f"{article_key}:child"
                child_metadata = path_metadata([article], "child")
                child_metadata.update(
                    {
                        "parent_id": key,
                        "parent_point_id": stable_point_id(key),
                    }
                )
                add(
                    full_text,
                    make_search_text([article], full_text),
                    child_metadata,
                    key,
                )
                continue

            parent_metadata = path_metadata([article], "parent")
            parent_metadata.update(
                {
                    "search_enabled": False,
                    "parent_id": None,
                    "parent_point_id": None,
                }
            )
            add(full_text, "", parent_metadata, parent_key)

            def emit(path: list[LawNode]) -> None:
                node = path[-1]
                subtree = self.render(node)
                path_key = "/".join(
                    filter(
                        None,
                        [
                            article_name,
                            *[
                                self.location_segment(item)
                                for item in path[1:]
                            ],
                        ],
                    )
                )
                if len(subtree) <= self.max_chars:
                    key = f"{article_key}:{path_key}:child"
                    add(
                        subtree,
                        make_search_text(path, subtree),
                        path_metadata(path, "child"),
                        key,
                    )
                    return

                if node.level != "article" and node.own:
                    key = f"{article_key}:{path_key}:anchor"
                    add(
                        node.own,
                        make_search_text(path, node.own),
                        path_metadata(path, "anchor"),
                        key,
                    )

                if node.children:
                    for child in node.children:
                        emit(path + [child])
                    return

                for part_no, part in enumerate(
                    self.split_leaf(subtree), start=1
                ):
                    key = f"{article_key}:{path_key}:child:{part_no}"
                    part_metadata = path_metadata(path, "child")
                    part_metadata["part"] = part_no
                    add(
                        part,
                        make_search_text(path, part),
                        part_metadata,
                        key,
                    )

            for child in article.children:
                emit([article, child])

        self._add_supplementary(root, metadata, common, chunks, add)
        return chunks

    def _add_supplementary(
        self,
        root: ET.Element,
        metadata: LawMetadata,
        common: dict,
        chunks: list[dict],
        add,
    ) -> None:
        del common, chunks
        empty_location = {
            "chapter": "",
            "section": "",
            "article": "",
            "article_no": None,
            "article_branch_no": None,
            "paragraph": "",
            "paragraph_no": None,
            "item": "",
            "item_no": None,
            "subitem": "",
            "subitem_no": None,
            "chunk_role": "child",
            "search_enabled": True,
            "parent_id": None,
            "parent_point_id": None,
        }

        for index, addendum in enumerate(
            root.findall("./부칙/부칙단위"), start=1
        ):
            raw = clean(addendum.findtext("./부칙내용", ""))
            if not raw:
                continue
            promulgation_no = direct_text(addendum, "부칙공포번호")
            for part_no, part in enumerate(self.split_leaf(raw), start=1):
                key = (
                    f"{self.law_version}:{metadata.law_id}:addendum:"
                    f"{promulgation_no}:{index}:{part_no}"
                )
                add(
                    part,
                    f"{metadata.law_name} 부칙 제{promulgation_no}호\n{part}",
                    {
                        **empty_location,
                        "source_type": "addendum",
                        "title": "부칙",
                        "unit_level": "addendum",
                        "addendum_promulgation_no": promulgation_no,
                        "addendum_promulgation_date": direct_text(
                            addendum, "부칙공포일자"
                        ),
                    },
                    key,
                )

        for index, reason in enumerate(
            root.findall("./제개정이유/제개정이유내용"), start=1
        ):
            raw = clean("".join(reason.itertext()))
            for part_no, part in enumerate(self.split_leaf(raw), start=1):
                key = (
                    f"{self.law_version}:{metadata.law_id}:reason:"
                    f"{index}:{part_no}"
                )
                add(
                    part,
                    f"{metadata.law_name} 제개정이유\n{part}",
                    {
                        **empty_location,
                        "source_type": "reason",
                        "title": "제개정이유",
                        "unit_level": "reason",
                    },
                    key,
                )

    @staticmethod
    def summary(chunks: list[dict]) -> dict:
        return {
            "total": len(chunks),
            "searchable": sum(bool(chunk["search_enabled"]) for chunk in chunks),
            "roles": dict(Counter(chunk["chunk_role"] for chunk in chunks)),
            "levels": dict(Counter(chunk["unit_level"] for chunk in chunks)),
        }
