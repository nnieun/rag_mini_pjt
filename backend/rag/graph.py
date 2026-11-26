"""LangGraph orchestration for extraction, tool selection, RAG and validation."""

import asyncio
import operator
import os
import re
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from rag.models import AnswerResult
from rag.pipeline import RAGPipeline, is_list_query
from rag.retriever import is_definition_query
from rag.schemas import CreatePdf, FollowUpResolution, GetArticle, RequestAnalysis, SearchLaw
from rag.tools import execute_tool
from rag.validators import validate_answer
from documents.pdf_report import create_answer_pdf


class RAGGraphState(TypedDict, total=False):
    question: str
    standalone_question: str
    cache_question: str
    history: list[dict[str, Any]]
    thread_id: str
    rewritten_question: str
    analysis: dict[str, Any]
    use_reranking: bool
    bypass_cache: bool
    tool_name: str
    tool_arguments: dict[str, Any]
    documents: list[dict]
    relevance: float
    retrieval_retries: int
    answer_retries: int
    answer_result: AnswerResult
    validation_errors: list[str]
    artifact_url: str
    # 체크포인터가 있으면 thread_id별로 대화 턴이 누적된다(append reducer).
    turns: Annotated[list[dict[str, Any]], operator.add]


MAX_REMEMBERED_TURNS = 3


def checkpoint_serde():
    """체크포인트에 들어가는 우리 dataclass만 역직렬화를 허용하는 직렬화기."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(
        allowed_msgpack_modules=[("rag.models", "AnswerResult"), ("rag.models", "Source")]
    )

# 매 질문마다 초기화해야 하는 필드. 체크포인터는 이전 턴의 최종 상태를 이어받으므로
# 여기서 비우지 않으면 이전 턴의 artifact_url·documents 등이 다음 턴 라우팅에 섞인다.
TURN_RESET: dict[str, Any] = {
    "standalone_question": "",
    "cache_question": "",
    "rewritten_question": "",
    "analysis": {},
    "use_reranking": False,
    "tool_name": "",
    "tool_arguments": {},
    "documents": [],
    "relevance": 0.0,
    "retrieval_retries": 0,
    "answer_retries": 0,
    "validation_errors": [],
    "artifact_url": "",
}


def _rule_analysis(question: str) -> RequestAnalysis:
    article_match = re.search(r"제\s*(\d+)\s*조", question)
    if article_match:
        intent = "article_lookup"
    elif is_list_query(question):
        intent = "obligation"
    elif is_definition_query(question):
        intent = "definition"
    elif any(term in question for term in ("비교", "차이")):
        intent = "comparison"
    elif any(term in question for term in ("요약", "정리")):
        intent = "summary"
    else:
        intent = "general"
    return RequestAnalysis(
        intent=intent,
        article_number=int(article_match.group(1)) if article_match else None,
        keywords=list(dict.fromkeys(re.findall(r"[가-힣]{2,}", question)))[:8],
    )


def classify_question(state: RAGGraphState) -> dict[str, Any]:
    analysis = _rule_analysis(state["question"])
    return {
        "analysis": analysis.model_dump(),
        "question_type": analysis.intent,
        "use_reranking": analysis.intent == "definition",
        "rewritten_question": rewrite_query(state["question"], analysis),
    }


def rewrite_query(question: str, analysis: RequestAnalysis, retry: int = 0) -> str:
    rewritten = re.sub(r"\s+", " ", question.strip())
    rewritten = re.sub(
        r"(알려\s*주세요|설명해\s*주세요|말해\s*주세요)[.!?]*$", "", rewritten
    ).strip()
    if analysis.intent == "definition" and "정의" not in rewritten:
        rewritten = f"{rewritten} 정의"
    if retry:
        rewritten = f"{rewritten} 관련 조문 법령 근거"
    return rewritten or question


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}|\d+", text.lower()))


def grade_documents(question: str, documents: list[dict]) -> float:
    question_terms = _terms(question)
    if not question_terms or not documents:
        return 0.0
    scores = []
    for document in documents:
        content = " ".join(
            str(document.get(field) or "")
            for field in ("article", "title", "content", "law_name")
        )
        scores.append(len(question_terms & _terms(content)) / len(question_terms))
    return max(scores, default=0.0)


def grade_answer(answer: str, source_count: int) -> bool:
    if "확인할 수 없습니다" in answer:
        return True
    return source_count > 0 and bool(re.search(r"\[S\d+\]", answer))


def build_rag_graph(pipeline: RAGPipeline, checkpointer: Any | None = None):
    async def resolve_follow_up(state: RAGGraphState) -> dict[str, Any]:
        # 클라이언트가 보낸 history가 우선이고, 없으면 체크포인트에 남은 이전 턴을 쓴다.
        history = (state.get("history") or state.get("turns") or [])[-MAX_REMEMBERED_TURNS:]
        question = state["question"].strip()
        if not history:
            return {"standalone_question": question, "cache_question": question}

        last = history[-1]
        fallback = (
            f"{last.get('question', '')}에 대해 후속 질문 '{question}'을 반영하여 "
            "이전 답변에서 누락된 관련 조문과 내용을 확인"
        )
        standalone = fallback
        structured = getattr(pipeline.llm, "with_structured_output", None)
        if callable(structured):
            try:
                resolved = await structured(FollowUpResolution).ainvoke(
                    [
                        (
                            "system",
                            "후속 질문을 법령 검색기가 이전 대화 없이도 이해할 수 있는 "
                            "완전한 한국어 검색 질의로 바꾸세요. 이전 답변에서 더 있는지 "
                            "묻는 경우 누락된 관련 조문·적용 범위·의무를 확인하도록 쓰세요. "
                            "답변하지 말고 검색 질의만 구조화해서 반환하세요.",
                        ),
                        (
                            "human",
                            "\n\n".join(
                                [
                                    f"이전 질문: {item.get('question', '')}\n"
                                    f"이전 답변: {str(item.get('answer', ''))[:2000]}\n"
                                    f"이전 출처: {', '.join(item.get('source_articles', []))}"
                                    for item in history
                                ]
                            )
                            + f"\n\n현재 후속 질문: {question}",
                        ),
                    ]
                )
                standalone = FollowUpResolution.model_validate(resolved).standalone_query
            except Exception:
                pass
        cache_material = f"{standalone}\n후속 질문:{question}"
        return {"standalone_question": standalone, "cache_question": cache_material}

    async def analyze(state: RAGGraphState) -> dict[str, Any]:
        search_question = state.get("standalone_question") or state["question"]
        base = classify_question({**state, "question": search_question})
        analysis = RequestAnalysis.model_validate(base["analysis"])
        if os.getenv("RAG_LLM_ANALYSIS_ENABLED", "true").lower() in {
            "1", "true", "yes", "on"
        }:
            structured = getattr(pipeline.llm, "with_structured_output", None)
            if callable(structured):
                try:
                    extracted = await structured(RequestAnalysis).ainvoke(
                        [
                            (
                                "system",
                                "AI 기본법 질문에서 의도, 조문 번호, 키워드, "
                                "대상과 누락 필드를 추출하세요. 없는 값은 추측하지 마세요.",
                            ),
                            ("human", search_question),
                        ]
                    )
                    analysis = RequestAnalysis.model_validate(extracted)
                    base = {
                        **base,
                        "analysis": analysis.model_dump(),
                        "question_type": analysis.intent,
                        "use_reranking": analysis.intent == "definition",
                        "rewritten_question": rewrite_query(search_question, analysis),
                    }
                except Exception:
                    pass
        tool_name = "GetArticle" if analysis.article_number else "SearchLaw"
        arguments: dict[str, Any] = (
            {"article_number": analysis.article_number}
            if analysis.article_number
            else {
                "query": base["rewritten_question"],
                "top_k": 20 if is_list_query(search_question) else 5,
            }
        )
        if any(term in state["question"].lower() for term in ("pdf", "피디에프")):
            tool_name = "CreatePdf"
            arguments = {"title": "AI 기본법 답변 보고서", "include_sources": True}

        if os.getenv("RAG_LLM_TOOL_ROUTING_ENABLED", "true").lower() in {
            "1", "true", "yes", "on"
        }:
            bind_tools = getattr(pipeline.llm, "bind_tools", None)
            if callable(bind_tools):
                try:
                    response = await bind_tools([SearchLaw, GetArticle, CreatePdf]).ainvoke(
                        [
                            (
                                "system",
                                "AI 기본법 질문에 필요한 도구 하나를 선택하세요. "
                                "특정 조문 번호가 있으면 GetArticle을 사용하세요. "
                                "이전 답변을 PDF로 만들어 달라는 요청은 CreatePdf를 사용하세요.",
                            ),
                            ("human", search_question),
                        ]
                    )
                    calls = getattr(response, "tool_calls", [])
                    if calls:
                        tool_name = str(calls[0]["name"])
                        arguments = dict(calls[0]["args"])
                except Exception:
                    pass

        if any(term in state["question"].lower() for term in ("pdf", "피디에프")):
            tool_name = "CreatePdf"
            arguments = {"title": "AI 기본법 답변 보고서", "include_sources": True}
        if tool_name == "SearchLaw":
            arguments["query"] = base["rewritten_question"]
        return {**base, "tool_name": tool_name, "tool_arguments": arguments}

    async def run_tool(state: RAGGraphState) -> dict[str, Any]:
        if state["tool_name"] == "CreatePdf":
            args = CreatePdf.model_validate(state["tool_arguments"])
            history = state.get("history") or state.get("turns") or []
            if not history:
                raise ValueError("PDF로 만들 이전 답변이 없습니다.")
            latest = history[-1]
            _, url = create_answer_pdf(
                title=args.title,
                question=str(latest.get("question", "")),
                answer=str(latest.get("answer", "")),
                source_articles=list(latest.get("source_articles", [])),
                include_sources=args.include_sources,
            )
            return {"artifact_url": url, "documents": [], "relevance": 1.0}
        documents = await execute_tool(
            pipeline,
            state["tool_name"],
            state["tool_arguments"],
            use_reranking=bool(state.get("use_reranking")),
        )
        question = state.get("rewritten_question") or state["question"]
        return {"documents": documents, "relevance": grade_documents(question, documents)}

    async def route_documents(
        state: RAGGraphState,
    ) -> Literal["artifact", "rewrite", "generate"]:
        if state.get("artifact_url"):
            return "artifact"
        retries = int(state.get("retrieval_retries", 0))
        if (not state.get("documents") or state.get("relevance", 0.0) < 0.10) and retries < 1:
            return "rewrite"
        return "generate"

    async def artifact_response(state: RAGGraphState) -> dict[str, Any]:
        url = state["artifact_url"]
        return {
            "answer_result": AnswerResult(
                answer=f"PDF 보고서를 생성했습니다: {url}",
                sources=[],
                method="ToolCalling(CreatePdf)",
                retrieved_articles=[],
                resolved_question=state.get("standalone_question") or state["question"],
            )
        }

    async def rewrite(state: RAGGraphState) -> dict[str, Any]:
        analysis = RequestAnalysis.model_validate(state["analysis"])
        question = rewrite_query(
            state.get("standalone_question") or state["question"], analysis, retry=1
        )
        return {
            "rewritten_question": question,
            "tool_name": "SearchLaw",
            "tool_arguments": {"query": question, "top_k": 10},
            "retrieval_retries": int(state.get("retrieval_retries", 0)) + 1,
        }

    async def generate(state: RAGGraphState) -> dict[str, Any]:
        result = await pipeline.answer(
            state.get("rewritten_question") or state["question"],
            use_reranking=bool(state.get("use_reranking")),
            bypass_cache=bool(state.get("bypass_cache")),
            retrieved_results=state.get("documents"),
            cache_question=state.get("cache_question") or state["question"],
        )
        result.resolved_question = state.get("standalone_question") or state["question"]
        return {"answer_result": result}

    async def validate(state: RAGGraphState) -> dict[str, Any]:
        validation = validate_answer(state["answer_result"])
        return {"validation_errors": validation.errors}

    async def route_validation(state: RAGGraphState) -> Literal["retry", "end"]:
        if state.get("validation_errors") and int(state.get("answer_retries", 0)) < 1:
            return "retry"
        return "end"

    async def prepare_retry(state: RAGGraphState) -> dict[str, Any]:
        return {
            "answer_retries": int(state.get("answer_retries", 0)) + 1,
            "bypass_cache": True,
            "use_reranking": True,
        }

    async def remember(state: RAGGraphState) -> dict[str, Any]:
        result = state.get("answer_result")
        if result is None or state.get("artifact_url"):
            return {}
        return {
            "turns": [
                {
                    "question": state["question"],
                    "answer": result.answer[:8000],
                    "source_articles": [source.article for source in result.sources],
                }
            ]
        }

    builder = StateGraph(RAGGraphState)
    builder.add_node("resolve_follow_up", resolve_follow_up)
    builder.add_node("analyze_and_select_tool", analyze)
    builder.add_node("execute_tool", run_tool)
    builder.add_node("artifact_response", artifact_response)
    builder.add_node("rewrite_query", rewrite)
    builder.add_node("generate", generate)
    builder.add_node("validate", validate)
    builder.add_node("prepare_retry", prepare_retry)
    builder.add_node("remember", remember)
    builder.add_edge(START, "resolve_follow_up")
    builder.add_edge("resolve_follow_up", "analyze_and_select_tool")
    builder.add_edge("analyze_and_select_tool", "execute_tool")
    builder.add_conditional_edges(
        "execute_tool",
        route_documents,
        {
            "artifact": "artifact_response",
            "rewrite": "rewrite_query",
            "generate": "generate",
        },
    )
    builder.add_edge("artifact_response", END)
    builder.add_edge("remember", END)
    builder.add_edge("rewrite_query", "execute_tool")
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges(
        "validate", route_validation, {"retry": "prepare_retry", "end": "remember"}
    )
    builder.add_edge("prepare_retry", "generate")
    return builder.compile(checkpointer=checkpointer)


class LangGraphRAG:
    def __init__(self, pipeline: RAGPipeline, checkpointer: Any | None = None):
        self.pipeline = pipeline
        self.graph = build_rag_graph(pipeline)
        # thread_id가 있는 요청만 체크포인터 그래프를 쓴다. 없는 요청까지 저장하면
        # 일회성 thread가 체크포인트 테이블에 쌓인다.
        self.memory_graph = (
            build_rag_graph(pipeline, checkpointer) if checkpointer is not None else None
        )
        self.timeout_seconds = float(os.getenv("RAG_GRAPH_TIMEOUT_SECONDS", "120"))

    async def answer(
        self,
        question: str,
        *,
        bypass_cache: bool = False,
        history: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
    ) -> AnswerResult:
        turn_input = {
            **TURN_RESET,
            "question": question,
            "bypass_cache": bypass_cache,
            "history": history or [],
            "thread_id": thread_id or "",
        }
        if thread_id and self.memory_graph is not None:
            run = self.memory_graph.ainvoke(
                turn_input, config={"configurable": {"thread_id": thread_id}}
            )
        else:
            run = self.graph.ainvoke(turn_input)
        state = await asyncio.wait_for(run, timeout=self.timeout_seconds)
        return state["answer_result"]
