from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class LawMetadata:
    law_name: str
    law_id: str
    promulgation_no: str
    promulgation_date: str
    enforce_date: str
    source: str


def _text(element: ET.Element, tag: str) -> str:
    return " ".join((element.findtext(tag) or "").split())


class LawXMLLoader:
    """국가법령정보센터 XML을 검증하고 ElementTree로 로딩한다."""

    def __init__(self, xml_path: str | Path):
        self.xml_path = Path(xml_path).expanduser().resolve()

    def load(self) -> ET.Element:
        if not self.xml_path.exists():
            raise FileNotFoundError(f"법령 XML이 없습니다: {self.xml_path}")

        root = ET.parse(self.xml_path).getroot()
        if root.tag != "법령":
            message = " ".join("".join(root.itertext()).split())
            raise ValueError(
                f"정상 법령 XML이 아닙니다. root={root.tag}, message={message[:200]}"
            )
        if root.find("./기본정보") is None:
            raise ValueError("법령 XML에 기본정보가 없습니다.")
        if not root.findall("./조문/조문단위"):
            raise ValueError("법령 XML에 조문단위가 없습니다.")
        return root

    def metadata(self, root: ET.Element | None = None) -> LawMetadata:
        if root is None:
            root = self.load()
        info = root.find("./기본정보")
        if info is None:
            raise ValueError("법령 XML에 기본정보가 없습니다.")
        return LawMetadata(
            law_name=_text(info, "법령명_한글"),
            law_id=_text(info, "법령ID"),
            promulgation_no=_text(info, "공포번호"),
            promulgation_date=_text(info, "공포일자"),
            enforce_date=_text(info, "시행일자"),
            source=self.xml_path.name,
        )
