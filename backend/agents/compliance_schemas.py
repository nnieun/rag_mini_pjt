"""Data models for the AI Basic Act compliance agent.

- `ServiceProfile`: facts extracted from a service description.
- `ComplianceAssessment`: the agent's verdict, one `Obligation` per article/paragraph,
  every obligation backed by source ids of retrieved law chunks.

Article ids use the form `제31조제1항` so predictions and labels compare as strings.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 제2조제4호 각 목: 고영향 인공지능이 활용되는 영역
HIGH_IMPACT_CATEGORIES: dict[str, str] = {
    "가": "에너지의 공급",
    "나": "먹는물의 생산 공정",
    "다": "보건의료의 제공 및 이용체계의 구축·운영",
    "라": "의료기기·디지털의료기기의 개발 및 이용",
    "마": "핵물질·원자력시설의 안전한 관리 및 운영",
    "바": "범죄 수사·체포를 위한 생체인식정보의 분석·활용",
    "사": "채용, 대출 심사 등 개인의 권리·의무 관계에 중대한 영향을 미치는 판단 또는 평가",
    "아": "교통수단·교통시설·교통체계의 주요한 작동 및 운영",
    "자": "국가기관등의 공공서비스 자격 확인·결정·비용징수 등 의사결정",
    "차": "유아·초등·중등교육에서의 학생 평가",
    "카": "그 밖에 대통령령으로 정하는 영역",
}

# 점검 대상 의무. 키는 조·항 id, 값은 의무 이름.
OBLIGATIONS: dict[str, str] = {
    "제31조제1항": "고영향·생성형 인공지능 기반 운용 사실의 사전 고지",
    "제31조제2항": "생성형 인공지능 결과물의 생성 사실 표시",
    "제31조제3항": "실제와 구분하기 어려운 가상 결과물의 고지·표시",
    "제32조제1항": "누적 연산량 기준 이상 시스템의 위험 식별·평가·완화와 위험관리체계",
    "제32조제2항": "안전성 확보 이행 결과 제출",
    "제33조제1항": "고영향 인공지능 해당 여부 사전 검토(필요 시 확인 요청)",
    "제34조제1항": "고영향 인공지능 안전성·신뢰성 확보 조치",
    "제35조제1항": "고영향 인공지능 영향평가(노력 의무)",
    "제36조제1항": "국내대리인 지정·신고",
}

ARTICLE_ID = re.compile(r"^제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?$")

Applicability = Literal["해당", "해당 가능", "해당 없음", "판단 정보 부족"]
APPLIES = {"해당", "해당 가능"}

DISCLAIMER = (
    "이 결과는 AI 기본법 원문에 기반한 자동 점검이며 법률 자문이 아닙니다. "
    "시행령·고시와 구체적 사실관계에 따라 달라질 수 있습니다."
)


def normalize_article_id(value: str) -> str:
    """'제 31조 제1항' -> '제31조제1항'."""
    return re.sub(r"\s+", "", value)


class ServiceProfile(BaseModel):
    """서비스 설명서에서 뽑은, 의무 판단에 필요한 사실."""

    name: str = Field(default="", description="서비스 이름")
    summary: str = Field(default="", description="서비스가 하는 일 한두 문장")
    domains: list[str] = Field(default_factory=list, description="활용 영역(채용, 의료 등)")
    decides_about_individuals: bool | None = Field(
        default=None, description="개인에 대한 판단·평가 결과를 내는지"
    )
    is_generative: bool | None = Field(default=None, description="글·소리·그림·영상을 생성하는지")
    generates_realistic_media: bool | None = Field(
        default=None, description="실제와 구분하기 어려운 음향·이미지·영상을 만드는지"
    )
    operator_role: Literal["developer", "deployer", "both", "unknown"] = Field(
        default="unknown", description="인공지능개발사업자/이용사업자 여부"
    )
    has_domestic_presence: bool | None = Field(
        default=None, description="국내 주소 또는 영업소가 있는지"
    )
    large_training_compute: bool | None = Field(
        default=None, description="학습 누적 연산량이 대통령령 기준 이상인지"
    )
    missing_fields: list[str] = Field(
        default_factory=list, description="판단에 필요한데 설명서에 없는 항목"
    )


class Obligation(BaseModel):
    article: str = Field(description="조·항 id. 예: 제31조제1항")
    title: str = Field(default="", description="의무 이름")
    applies: Applicability
    reason: str = Field(default="", description="해당 여부 판단 근거")
    actions: list[str] = Field(default_factory=list, description="해야 할 일")
    source_ids: list[str] = Field(default_factory=list, description="근거로 쓴 검색 결과 id")

    @field_validator("article")
    @classmethod
    def _article_format(cls, value: str) -> str:
        value = normalize_article_id(value)
        if not ARTICLE_ID.match(value):
            raise ValueError(f"조문 id 형식이 아닙니다: {value}")
        return value


class ComplianceAssessment(BaseModel):
    """AI 기본법 준수 점검 결과."""

    high_impact: Literal["yes", "no", "uncertain"]
    high_impact_categories: list[str] = Field(
        default_factory=list, description="해당하는 제2조제4호 목(가~카)"
    )
    is_generative: bool = False
    obligations: list[Obligation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, description="판단 신뢰도 0~1")
    assumptions: list[str] = Field(default_factory=list, description="설명서에서 추정한 가정")
    summary: str = Field(default="", description="한 문단 요약")
    disclaimer: str = DISCLAIMER

    @field_validator("high_impact_categories")
    @classmethod
    def _known_categories(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip().rstrip("목").strip() for value in values]
        unknown = [value for value in cleaned if value not in HIGH_IMPACT_CATEGORIES]
        if unknown:
            raise ValueError(f"제2조제4호에 없는 목입니다: {', '.join(unknown)}")
        return list(dict.fromkeys(cleaned))

    def applicable_articles(self) -> set[str]:
        return {item.article for item in self.obligations if item.applies in APPLIES}
