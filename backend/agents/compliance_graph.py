"""Compliance agent: service description -> AI Basic Act obligations.

Graph: ingest -> profile -> agent <-> tools -> assess -> validate
       validate -(citation errors, once)-> assess
       validate -(high impact or low confidence)-> human_review (interrupt) -> END
       validate -> finalize -> END

- ingest: normalize the description (text or extracted document text).
- profile: structured extraction of a `ServiceProfile`.
- agent / tools: ReAct loop. The LLM may request several tool calls per turn;
  all of them run, up to `MAX_TOOL_CALLS` in total for the run. Every retrieved
  chunk gets a stable source id (S1, S2, ...) that the assessment must cite.
- assess: structured `ComplianceAssessment` from the profile and the sources. If
  the LLM cannot produce one, a rule-based assessment from the profile is used.
- validate: every applicable obligation must cite at least one known source id.
  On failure the assessment is regenerated once with the errors as feedback.
- human_review: high-impact results, confidence below 0.7 and unresolved citation
  errors stop at `interrupt()` until a person approves or rejects (needs a
  checkpointer; `ComplianceAgent` uses an in-memory one by default).
"""

import json
import logging
import operator
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agents.compliance_schemas import (
    APPLIES,
    HIGH_IMPACT_CATEGORIES,
    OBLIGATIONS,
    ComplianceAssessment,
    Obligation,
    ServiceProfile,
)
from rag.tools import REGISTRY, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
REVIEW_CONFIDENCE = 0.7
MAX_CITATION_RETRIES = 1
MAX_DESCRIPTION_CHARS = 12000
AGENT_TOOLS = ("SearchLaw", "GetArticle", "GetRelatedArticles")


def merge_sources(left: dict[str, dict], right: dict[str, dict]) -> dict[str, dict]:
    return {**(left or {}), **(right or {})}


class ComplianceState(TypedDict, total=False):
    description: str
    profile: dict[str, Any]
    messages: Annotated[list[AnyMessage], add_messages]
    sources: Annotated[dict[str, dict], merge_sources]
    tool_call_count: int
    tool_trace: Annotated[list[dict[str, Any]], operator.add]
    assessment: dict[str, Any]
    assessment_method: str
    citation_errors: list[str]
    citation_retries: int
    next_step: str
    review: dict[str, Any]


PROFILE_PROMPT = (
    "AI 서비스 설명서에서 AI 기본법 의무 판단에 필요한 사실만 추출한다. "
    "설명서에 없는 값은 null로 두고 missing_fields에 적는다. 추측하지 않는다."
)

AGENT_PROMPT = """너는 AI 기본법 준수 점검을 위한 조사 담당이다.
서비스 프로필을 보고, 판단에 필요한 조문을 도구로 찾아라.

반드시 확인할 것:
- 제2조제4호(고영향 인공지능 정의와 각 목)에서 서비스 영역이 해당하는 목
- 제31조(투명성), 제32조(안전성), 제33조(고영향 확인), 제34조(고영향 사업자 책무), 제35조(영향평가), 제36조(국내대리인) 중 관련 조문

GetArticle로 조문 원문을, SearchLaw로 키워드 검색을, GetRelatedArticles로 그 조문이 인용하거나 그 조문을 인용하는 조문(예: 의무 조문을 인용하는 과태료 조문)을 찾는다. 한 번에 여러 도구를 호출해도 된다.
도구 호출은 전체 {limit}회까지다. 근거가 충분하면 도구를 더 부르지 말고 "조사 완료"라고만 답한다."""

ASSESS_PROMPT = """AI 기본법 준수 점검 결과를 작성한다.

규칙:
- 아래 '근거' 목록의 조문만 근거로 쓰고, 각 의무의 source_ids에 그 근거 id(S1 등)를 넣는다.
- high_impact: 제2조제4호 각 목 중 하나에 해당하면 yes, 아니면 no, 정보가 부족하면 uncertain.
- high_impact_categories: 해당하는 목 글자(가~카).
- obligations: 아래 의무 목록 각각에 대해 applies를 해당/해당 가능/해당 없음/판단 정보 부족 중 하나로 쓴다.
- confidence: 설명서 정보가 충분하고 근거가 명확할수록 높게(0~1).
- assumptions: 설명서에 없어서 가정한 내용.

의무 목록:
{obligations}

제2조제4호 각 목:
{categories}"""


def validate_citations(assessment: ComplianceAssessment, sources: dict[str, dict]) -> list[str]:
    """Errors for applicable obligations without a valid source id."""
    errors = []
    for item in assessment.obligations:
        if item.applies not in APPLIES:
            continue
        unknown = [sid for sid in item.source_ids if sid not in sources]
        if unknown:
            errors.append(f"{item.article}: 근거 목록에 없는 id {', '.join(unknown)}")
        if not [sid for sid in item.source_ids if sid in sources]:
            errors.append(f"{item.article}: 유효한 근거 id가 없음")
    return errors


def drop_unknown_sources(assessment: ComplianceAssessment, sources: dict[str, dict]) -> ComplianceAssessment:
    obligations = [
        item.model_copy(update={"source_ids": [sid for sid in item.source_ids if sid in sources]})
        for item in assessment.obligations
    ]
    return assessment.model_copy(update={"obligations": obligations})


def review_reasons(assessment: ComplianceAssessment, citation_errors: list[str]) -> list[str]:
    reasons = []
    if assessment.high_impact == "yes":
        reasons.append("고영향 인공지능 해당")
    if assessment.confidence < REVIEW_CONFIDENCE:
        reasons.append(f"신뢰도 {assessment.confidence:.2f} < {REVIEW_CONFIDENCE}")
    if citation_errors:
        reasons.append("근거 인용 오류가 남아 있음")
    return reasons


def format_source(source_id: str, document: dict) -> str:
    label = " ".join(
        str(document.get(key) or "") for key in ("article", "paragraph", "item", "subitem")
    ).strip()
    title = str(document.get("title") or "")
    content = re.sub(r"\s+", " ", str(document.get("content") or ""))[:1500]
    return f"[{source_id}] {label} ({title}) {content}".strip()


def _source_key(document: dict) -> str:
    return str(
        document.get("chunk_id")
        or document.get("chunk_key")
        or "|".join(str(document.get(k) or "") for k in ("article", "paragraph", "item", "content"))
    )


def register_sources(
    known: dict[str, dict], documents: list[dict]
) -> tuple[dict[str, dict], list[str]]:
    """Give each new chunk the next source id; reuse ids for chunks seen before."""
    by_key = {_source_key(document): source_id for source_id, document in known.items()}
    added: dict[str, dict] = {}
    ids: list[str] = []
    for document in documents:
        key = _source_key(document)
        source_id = by_key.get(key)
        if source_id is None:
            source_id = f"S{len(known) + len(added) + 1}"
            added[source_id] = dict(document)
            by_key[key] = source_id
        ids.append(source_id)
    return added, ids


def _source_ids_for(sources: dict[str, dict], article_id: str) -> list[str]:
    """Source ids of chunks in `제N조` (and the same 항, when both sides have one)."""
    match = re.match(r"(제\d+조)(제\d+항)?", article_id)
    if not match:
        return []
    article, paragraph = match.group(1), match.group(2)
    ids = []
    for source_id, document in sources.items():
        if re.sub(r"\s+", "", str(document.get("article") or "")) != article:
            continue
        doc_paragraph = str(document.get("paragraph") or "")
        if paragraph and doc_paragraph and _paragraph_number(doc_paragraph) != _paragraph_number(paragraph):
            continue
        ids.append(source_id)
    return ids


def _paragraph_number(text: str) -> int | None:
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    for index, char in enumerate(circled, start=1):
        if char in text:
            return index
    digits = re.search(r"\d+", text)
    return int(digits.group()) if digits else None


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "가": ("에너지", "전력", "발전", "송전", "가스 공급"),
    "나": ("먹는물", "정수", "수처리", "상수도"),
    "다": ("보건의료", "응급", "진료", "환자", "병원"),
    "라": ("의료기기", "디지털의료", "영상 판독", "진단 보조"),
    "마": ("원자력", "핵물질", "원전"),
    "바": ("생체인식", "얼굴 인식", "얼굴을 인식", "지문", "홍채", "수배", "용의자"),
    "사": ("채용", "면접", "지원자", "대출", "신용", "보험 심사"),
    "아": ("자율주행", "교통", "철도", "항공 관제", "신호 제어"),
    "자": ("지방자치단체", "공공기관", "수급 자격", "국가기관", "행정 처분"),
    "차": ("초등", "중학교", "고등학교", "유아", "학생 평가", "채점"),
}


def rule_based_assessment(profile: ServiceProfile, sources: dict[str, dict], description: str = "") -> ComplianceAssessment:
    """Deterministic assessment from the profile and keywords.

    Used when the LLM assessment fails, and as a baseline in evaluation.
    """
    text = " ".join([description, profile.summary, " ".join(profile.domains)])
    categories = [
        category for category, words in CATEGORY_KEYWORDS.items() if any(w in text for w in words)
    ]
    if categories:
        high_impact = "yes"
    elif profile.decides_about_individuals:
        high_impact = "uncertain"
    else:
        high_impact = "no"
    generative = bool(profile.is_generative)

    applies: dict[str, str] = {article: "해당 없음" for article in OBLIGATIONS}
    applies["제33조제1항"] = "해당"
    if high_impact == "yes":
        for article in ("제31조제1항", "제34조제1항", "제35조제1항"):
            applies[article] = "해당"
    if generative:
        applies["제31조제1항"] = "해당"
        applies["제31조제2항"] = "해당"
    if profile.generates_realistic_media:
        applies["제31조제3항"] = "해당"
    if profile.large_training_compute:
        applies["제32조제1항"] = applies["제32조제2항"] = "해당"
    elif profile.large_training_compute is None:
        applies["제32조제1항"] = applies["제32조제2항"] = "판단 정보 부족"
    if profile.has_domestic_presence is False:
        applies["제36조제1항"] = "해당 가능"

    obligations = [
        Obligation(
            article=article,
            title=OBLIGATIONS[article],
            applies=status,
            reason="규칙 기반 판단",
            source_ids=_source_ids_for(sources, article) if status in APPLIES else [],
        )
        for article, status in applies.items()
    ]
    return ComplianceAssessment(
        high_impact=high_impact,
        high_impact_categories=categories,
        is_generative=generative,
        obligations=obligations,
        confidence=0.4,
        assumptions=["LLM 판단을 쓰지 못해 키워드와 프로필로 판단함"],
        summary="규칙 기반 자동 판단 결과",
    )


def _profile_text(profile: dict[str, Any]) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)


def build_compliance_graph(
    pipeline: Any,
    llm: Any | None = None,
    *,
    checkpointer: Any | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
):
    llm = llm if llm is not None else getattr(pipeline, "llm", None)
    tool_models = [REGISTRY[name].args_model for name in AGENT_TOOLS]

    async def ingest(state: ComplianceState) -> dict[str, Any]:
        description = re.sub(r"[ \t]+", " ", str(state.get("description") or "")).strip()
        if len(description) < 10:
            raise ValueError("서비스 설명이 너무 짧습니다(10자 이상).")
        return {
            "description": description[:MAX_DESCRIPTION_CHARS],
            "tool_call_count": 0,
            "sources": {},
        }

    async def profile(state: ComplianceState) -> dict[str, Any]:
        extracted = ServiceProfile()
        structured = getattr(llm, "with_structured_output", None)
        if callable(structured):
            try:
                result = await structured(ServiceProfile).ainvoke(
                    [("system", PROFILE_PROMPT), ("human", state["description"])]
                )
                extracted = ServiceProfile.model_validate(result)
            except Exception as error:
                logger.warning("서비스 프로필 추출 실패, 빈 프로필로 진행: %s", error)
        data = extracted.model_dump()
        return {
            "profile": data,
            "messages": [
                SystemMessage(AGENT_PROMPT.format(limit=max_tool_calls)),
                HumanMessage(
                    f"서비스 설명:\n{state['description']}\n\n서비스 프로필:\n{_profile_text(data)}"
                ),
            ],
        }

    async def agent(state: ComplianceState) -> dict[str, Any]:
        if int(state.get("tool_call_count", 0)) >= max_tool_calls:
            return {}
        bind_tools = getattr(llm, "bind_tools", None)
        if not callable(bind_tools):
            return {"messages": [AIMessage("도구 호출을 지원하지 않는 모델이라 조사를 건너뜀")]}
        try:
            response = await bind_tools(tool_models).ainvoke(state["messages"])
        except Exception as error:
            logger.warning("컴플라이언스 에이전트 LLM 호출 실패: %s", error)
            return {"messages": [AIMessage(f"조사 중단: {type(error).__name__}")]}
        if not isinstance(response, AIMessage):
            response = AIMessage(
                content=str(getattr(response, "content", "")),
                tool_calls=list(getattr(response, "tool_calls", None) or []),
            )
        return {"messages": [response]}

    def route_agent(state: ComplianceState) -> Literal["tools", "assess"]:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None) or []
        if calls and int(state.get("tool_call_count", 0)) < max_tool_calls:
            return "tools"
        return "assess"

    async def tools(state: ComplianceState) -> dict[str, Any]:
        last = state["messages"][-1]
        count = int(state.get("tool_call_count", 0))
        known = dict(state.get("sources") or {})
        replies: list[ToolMessage] = []
        trace: list[dict[str, Any]] = []
        for call in last.tool_calls:
            call_id = call.get("id") or f"call_{count}"
            name = str(call.get("name", ""))
            if count >= max_tool_calls:
                # 응답 없는 tool_call이 남으면 다음 LLM 호출이 거부되므로 모두 답한다.
                replies.append(ToolMessage(f"도구 호출 상한({max_tool_calls}회)에 도달해 실행하지 않음", tool_call_id=call_id))
                trace.append({"name": name, "status": "skipped"})
                continue
            count += 1
            if name not in AGENT_TOOLS:
                replies.append(ToolMessage(f"사용할 수 없는 도구: {name}", tool_call_id=call_id))
                trace.append({"name": name, "status": "rejected"})
                continue
            try:
                documents = await execute_tool(
                    pipeline, name, dict(call.get("args") or {}), channel="agent"
                )
            except Exception as error:
                replies.append(ToolMessage(f"도구 오류: {error}", tool_call_id=call_id))
                trace.append({"name": name, "status": "error", "error": type(error).__name__})
                continue
            added, ids = register_sources(known, list(documents))
            known.update(added)
            body = "\n".join(format_source(sid, known[sid]) for sid in ids) or "결과 없음"
            replies.append(ToolMessage(body, tool_call_id=call_id))
            trace.append({"name": name, "status": "ok", "source_ids": ids})
        return {
            "messages": replies,
            "sources": {sid: doc for sid, doc in known.items() if sid not in (state.get("sources") or {})},
            "tool_call_count": count,
            "tool_trace": trace,
        }

    async def assess(state: ComplianceState) -> dict[str, Any]:
        sources = state.get("sources") or {}
        profile_model = ServiceProfile.model_validate(state.get("profile") or {})
        evidence = "\n".join(format_source(sid, doc) for sid, doc in sources.items()) or "근거 없음"
        structured = getattr(llm, "with_structured_output", None)
        if callable(structured):
            prompt = ASSESS_PROMPT.format(
                obligations="\n".join(f"- {key}: {value}" for key, value in OBLIGATIONS.items()),
                categories="\n".join(f"- {key}목: {value}" for key, value in HIGH_IMPACT_CATEGORIES.items()),
            )
            feedback = ""
            if state.get("citation_errors"):
                feedback = (
                    "\n\n이전 결과의 근거 인용 오류. 근거 목록의 id만 쓰고, 근거가 없는 의무는 "
                    "'판단 정보 부족'으로 바꿔라:\n- " + "\n- ".join(state["citation_errors"])
                )
            try:
                result = await structured(ComplianceAssessment).ainvoke(
                    [
                        ("system", prompt),
                        (
                            "human",
                            f"서비스 설명:\n{state['description']}\n\n"
                            f"서비스 프로필:\n{_profile_text(state.get('profile') or {})}\n\n근거:\n{evidence}"
                            + feedback,
                        ),
                    ]
                )
                assessment = ComplianceAssessment.model_validate(result)
                return {"assessment": assessment.model_dump(), "assessment_method": "llm"}
            except Exception as error:
                logger.warning("LLM 판정 실패, 규칙 기반 판정으로 대체: %s", error)
        fallback = rule_based_assessment(profile_model, sources, state.get("description", ""))
        return {"assessment": fallback.model_dump(), "assessment_method": "rule"}

    async def validate(state: ComplianceState) -> dict[str, Any]:
        sources = state.get("sources") or {}
        assessment = ComplianceAssessment.model_validate(state["assessment"])
        errors = validate_citations(assessment, sources)
        retries = int(state.get("citation_retries", 0))
        if errors and retries < MAX_CITATION_RETRIES:
            return {"citation_errors": errors, "citation_retries": retries + 1, "next_step": "retry"}
        if errors:
            # 재시도 후에도 남은 오류: 없는 id는 지우고 사람 검토로 넘긴다.
            assessment = drop_unknown_sources(assessment, sources)
        next_step = "review" if review_reasons(assessment, errors) else "done"
        return {"assessment": assessment.model_dump(), "citation_errors": errors, "next_step": next_step}

    def route_validation(state: ComplianceState) -> Literal["retry", "review", "done"]:
        return state.get("next_step", "done")  # type: ignore[return-value]

    async def human_review(state: ComplianceState) -> dict[str, Any]:
        assessment = ComplianceAssessment.model_validate(state["assessment"])
        reasons = review_reasons(assessment, state.get("citation_errors") or [])
        decision = interrupt(
            {
                "reasons": reasons,
                "high_impact": assessment.high_impact,
                "high_impact_categories": assessment.high_impact_categories,
                "confidence": assessment.confidence,
                "citation_errors": state.get("citation_errors") or [],
            }
        )
        decision = decision if isinstance(decision, dict) else {"approved": bool(decision)}
        return {
            "review": {
                "status": "approved" if decision.get("approved") else "rejected",
                "reasons": reasons,
                "reviewer": str(decision.get("reviewer") or "")[:100],
                "comment": str(decision.get("comment") or "")[:2000],
            }
        }

    async def finalize(state: ComplianceState) -> dict[str, Any]:
        return {"review": {"status": "not_required", "reasons": []}}

    builder = StateGraph(ComplianceState)
    builder.add_node("ingest", ingest)
    builder.add_node("profile", profile)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools)
    builder.add_node("assess", assess)
    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "profile")
    builder.add_edge("profile", "agent")
    builder.add_conditional_edges("agent", route_agent, {"tools": "tools", "assess": "assess"})
    builder.add_edge("tools", "agent")
    builder.add_node("validate", validate)
    builder.add_node("human_review", human_review)
    builder.add_node("finalize", finalize)
    builder.add_edge("assess", "validate")
    builder.add_conditional_edges(
        "validate", route_validation, {"retry": "assess", "review": "human_review", "done": "finalize"}
    )
    builder.add_edge("human_review", END)
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def summarize_update(node: str, update: dict[str, Any] | None) -> dict[str, Any]:
    """Small, JSON-safe progress event for one graph step (no law text, no messages)."""
    update = update or {}
    event: dict[str, Any] = {"step": node}
    if node == "profile":
        profile = update.get("profile") or {}
        event["profile"] = {key: profile.get(key) for key in ("name", "domains", "is_generative")}
    elif node == "agent":
        messages = update.get("messages") or []
        calls = getattr(messages[-1], "tool_calls", None) if messages else None
        event["tool_calls"] = [call.get("name") for call in calls or []]
    elif node == "tools":
        event["calls"] = [
            {"name": item.get("name"), "status": item.get("status")} for item in update.get("tool_trace") or []
        ]
        event["tool_call_count"] = update.get("tool_call_count")
    elif node == "assess":
        event["method"] = update.get("assessment_method")
    elif node == "validate":
        event["citation_errors"] = len(update.get("citation_errors") or [])
        event["next"] = update.get("next_step")
    elif node in {"human_review", "finalize"}:
        event["review"] = (update.get("review") or {}).get("status")
    return event


async def _emit(callback: EventCallback | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    pending = callback(event)
    if pending is not None:
        await pending


class ComplianceAgent:
    """Run the compliance graph and resume it after a human decision.

    Without a checkpointer an in-memory one is used, so approval works inside one
    process; the API passes the PostgreSQL checkpointer instead.
    """

    def __init__(self, pipeline: Any, llm: Any | None = None, *, checkpointer: Any | None = None):
        if checkpointer is None:
            from langgraph.checkpoint.memory import InMemorySaver

            from rag.graph import checkpoint_serde

            checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.graph = build_compliance_graph(pipeline, llm, checkpointer=checkpointer)

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        # ReAct 루프(최대 8회 도구 호출 = agent/tools 왕복)와 재시도에 여유를 둔다.
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 4 * MAX_TOOL_CALLS + 20}

    async def _drive(self, graph_input: Any, thread_id: str, on_event: EventCallback | None) -> None:
        async for chunk in self.graph.astream(
            graph_input, config=self._config(thread_id), stream_mode="updates"
        ):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    await _emit(on_event, {"step": "awaiting_approval"})
                else:
                    await _emit(on_event, summarize_update(node, update))

    async def start(
        self,
        description: str,
        *,
        thread_id: str | None = None,
        on_event: EventCallback | None = None,
    ) -> dict[str, Any]:
        thread_id = thread_id or f"compliance-{uuid.uuid4()}"
        await self._drive({"description": description}, thread_id, on_event)
        return await self.result(thread_id)

    async def resume(
        self,
        thread_id: str,
        *,
        approved: bool,
        reviewer: str = "",
        comment: str = "",
        on_event: EventCallback | None = None,
    ) -> dict[str, Any]:
        current = await self.result(thread_id)
        if current["status"] != "awaiting_approval":
            raise ValueError(f"승인 대기 상태가 아닙니다: {current['status']}")
        decision = {"approved": approved, "reviewer": reviewer, "comment": comment}
        await self._drive(Command(resume=decision), thread_id, on_event)
        return await self.result(thread_id)

    async def result(self, thread_id: str) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        state = snapshot.values or {}
        pending = [item.value for task in snapshot.tasks for item in task.interrupts]
        if not state:
            status = "not_found"
        elif pending:
            status = "awaiting_approval"
        elif (state.get("review") or {}).get("status") == "rejected":
            status = "rejected"
        elif state.get("review"):
            status = "completed"
        else:
            status = "running"
        assessment = state.get("assessment")
        return {
            "thread_id": thread_id,
            "status": status,
            "review_request": pending[0] if pending else None,
            "review": state.get("review"),
            "assessment": ComplianceAssessment.model_validate(assessment) if assessment else None,
            "profile": ServiceProfile.model_validate(state.get("profile") or {}),
            "sources": state.get("sources") or {},
            "tool_trace": state.get("tool_trace") or [],
            "citation_errors": state.get("citation_errors") or [],
            "method": state.get("assessment_method", ""),
        }

    # 평가 스크립트용: 승인 단계와 무관하게 판정 결과만 필요할 때
    assess = start
