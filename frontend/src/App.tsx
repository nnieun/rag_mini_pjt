import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { askLaw } from "./api";
import type { AskResponse, LawSource } from "./api";

type IconName = "archive" | "arrow" | "book" | "check" | "chevron" | "clock" | "close" | "collapse" | "copy" | "external" | "file" | "menu" | "message" | "plus" | "search" | "send" | "sparkle";

const iconPaths: Record<IconName, ReactNode> = {
  archive: <><path d="M3 6h18" /><path d="M5 6v14h14V6" /><path d="M9 10h6" /></>, arrow: <path d="m9 18 6-6-6-6" />,
  book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></>, check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />, clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>, close: <><path d="m6 6 12 12" /><path d="m18 6-12 12" /></>, collapse: <path d="m15 18-6-6 6-6" />,
  copy: <><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>, external: <><path d="M15 4h5v5" /><path d="m20 4-9 9" /><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /></>, menu: <path d="M4 7h16M4 12h16M4 17h16" />, message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /></>, plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>, send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>, sparkle: <><path d="m12 3 1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3Z" /></>,
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" fill="none" height={size} viewBox="0 0 24 24" width={size} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8">{iconPaths[name]}</svg>;
}

function Citation({ sourceId, active, onClick }: { sourceId: string; active: boolean; onClick: () => void }) {
  return <button className={`citation ${active ? "citation-active" : ""}`} onClick={onClick}><Icon name="file" size={13} />{sourceId}</button>;
}

function AnswerBody({ text, selected, onCitation }: { text: string; selected: string; onCitation: (id: string) => void }) {
  return <>{text.split(/\n+/).filter(Boolean).map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph.split(/(\[S\d+\])/g).map((part, partIndex) => {
    const match = part.match(/^\[(S\d+)\]$/);
    return match ? <Citation key={`${part}-${partIndex}`} sourceId={match[1]} active={selected === match[1]} onClick={() => onCitation(match[1])} /> : <span key={partIndex}>{part}</span>;
  })}</p>)}</>;
}

function sourceLocation(source: LawSource) {
  return [source.article, source.paragraph, source.item, source.subitem, source.title].filter(Boolean).join(" · ");
}

const exampleQuestions = ["고영향 인공지능이란 무엇인가요?", "인공지능사업자의 의무 관련 조문을 정리해줘", "투명성 관련 조문을 찾아줘"];

export default function App() {
  const [screen, setScreen] = useState<"empty" | "answer">("empty");
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [resultCache, setResultCache] = useState<Record<string, AskResponse>>({});
  const [recentQuestions, setRecentQuestions] = useState<string[]>([]);
  const [selectedCitation, setSelectedCitation] = useState("");
  const [articleOpen, setArticleOpen] = useState("");
  const [processOpen, setProcessOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | "all" | null>(null);

  const runQuestion = async (rawQuestion: string, refresh = false) => {
    const normalized = rawQuestion.trim();
    if (normalized.length < 2 || loading) return;
    const cachedResult = refresh ? undefined : resultCache[normalized];
    setScreen("answer"); setSubmittedQuestion(normalized); setQuestion(""); setError(""); setEvidenceOpen(true); setMobileNavOpen(false);
    if (cachedResult) {
      setResult(cachedResult);
      setSelectedCitation(cachedResult.sources[0]?.source_id ?? "");
      return;
    }
    setResult(null); setLoading(true);
    try {
      const response = await askLaw(normalized, refresh);
      setResult(response); setSelectedCitation(response.sources[0]?.source_id ?? "");
      setResultCache((current) => ({ ...current, [normalized]: response }));
      setRecentQuestions((current) => [normalized, ...current.filter((item) => item !== normalized)].slice(0, 5));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "백엔드 연결에 실패했습니다.");
    } finally { setLoading(false); }
  };

  const submitQuestion = (event: FormEvent) => { event.preventDefault(); void runQuestion(question); };
  const selectCitation = (sourceId: string) => { setSelectedCitation(sourceId); setEvidenceOpen(true); };
  const startNewQuestion = () => { setScreen("empty"); setQuestion(""); setResult(null); setError(""); setMobileNavOpen(false); setEvidenceOpen(false); };
  const deleteRecentQuestion = (item: string) => {
    setRecentQuestions((current) => current.filter((question) => question !== item));
    setResultCache((current) => {
      const next = { ...current };
      delete next[item];
      return next;
    });
    if (submittedQuestion === item) startNewQuestion();
  };
  const clearRecentQuestions = () => {
    setRecentQuestions([]);
    setResultCache({});
    startNewQuestion();
  };
  const confirmDelete = () => {
    if (deleteTarget === "all") clearRecentQuestions();
    else if (deleteTarget) deleteRecentQuestion(deleteTarget);
    setDeleteTarget(null);
  };
  const copyAnswer = async () => { if (!result) return; await navigator.clipboard.writeText(result.answer); setCopied(true); window.setTimeout(() => setCopied(false), 1400); };

  return <main className="app-shell">
    <header className="topbar"><div className="brand-block"><button className="mobile-icon-button" aria-label="메뉴 열기" onClick={() => setMobileNavOpen(true)}><Icon name="menu" size={20} /></button><div className="brand-mark"><Icon name="book" size={19} /></div><strong className="brand-name">법령리서치 AI</strong><span className="beta-label">BETA</span></div><div className="source-meta"><span><b>검색 대상</b> AI 기본법 본문</span><i /><span><b>법령 시행일</b> 2026. 7. 21.</span></div></header>
    <div className={`workspace ${screen === "empty" ? "empty-workspace" : ""}`}>
      <aside className={`sidebar ${mobileNavOpen ? "mobile-nav-open" : ""}`}>
        <div className="mobile-sidebar-head"><strong>법령리서치 AI</strong><button aria-label="메뉴 닫기" onClick={() => setMobileNavOpen(false)}><Icon name="close" /></button></div>
        <button className="new-question" onClick={startNewQuestion}><Icon name="plus" />새 질문</button>
        <nav className="primary-nav"><button className="nav-item active"><Icon name="message" />질문 기록</button></nav>
        <div className="recent-section"><div className="recent-section-head"><div className="section-label">최근 질문</div>{recentQuestions.length > 0 && <button onClick={() => setDeleteTarget("all")}>전체 삭제</button>}</div>{recentQuestions.length === 0 && <p className="recent-empty">아직 질문 기록이 없습니다.</p>}{recentQuestions.map((item) => <div className={`recent-item-row ${submittedQuestion === item ? "selected" : ""}`} key={item}><button className="recent-item" onClick={() => void runQuestion(item)}><span>{item}</span><small>이 세션</small></button><button className="recent-delete" aria-label={`${item} 삭제`} title="질문 기록 삭제" onClick={() => setDeleteTarget(item)}><Icon name="close" size={14} /></button></div>)}</div>
        <div className="sidebar-status"><div><span className={`status-dot ${error ? "status-error" : ""}`} />{error ? "백엔드 연결 확인 필요" : "법령 데이터 연결"}</div><p>대한민국 국가법령정보센터<br />법령 원문 기준</p></div>
      </aside>
      {mobileNavOpen && <button className="scrim" aria-label="메뉴 닫기" onClick={() => setMobileNavOpen(false)} />}
      <section className={`conversation ${screen === "empty" ? "empty-conversation" : ""}`}>
        {screen === "empty" ? <div className="empty-state">
          <div className="empty-hero"><div className="empty-icon"><Icon name="book" size={25} /></div><span className="empty-eyebrow">AI 기본법 법령 리서치</span><h1>AI 기본법, 조문 근거와<br />함께 확인하세요.</h1><p>궁금한 의무나 서비스 상황을 입력하면 관련 조문을 찾아<br className="desktop-break" /> 원문과 함께 답변해 드립니다.</p></div>
          <form className="empty-search" onSubmit={submitQuestion}><div className="empty-input-wrap"><Icon name="search" size={19} /><input aria-label="새 질문" autoFocus onChange={(event) => setQuestion(event.target.value)} placeholder="궁금한 의무나 서비스 상황을 입력하세요" value={question} /><button aria-label="질문 보내기" disabled={loading} type="submit"><Icon name="send" size={17} /></button></div><div className="empty-input-meta"><span><Icon name="check" size={13} />AI 기본법 본문에서만 검색합니다</span><span>Enter로 질문하기</span></div></form>
          <div className="example-section"><div className="example-label">이런 질문을 해보세요</div><div className="example-list">{exampleQuestions.map((example, index) => <button key={example} onClick={() => void runQuestion(example)}><span>{String(index + 1).padStart(2, "0")}</span><strong>{example}</strong><Icon name="arrow" size={16} /></button>)}</div></div>
          <div className="empty-source-card"><div className="empty-source-title"><Icon name="archive" size={17} /><div><strong>현재 검색 범위</strong><span>답변 생성에 사용하는 법령 데이터</span></div></div><div className="empty-source-grid"><div><span>검색 대상</span><strong>AI 기본법 본문</strong></div><div><span>법령 시행일</span><strong>2026. 7. 21.</strong></div><div><span>검색 방식</span><strong>Hybrid RAG</strong></div></div><p><Icon name="file" size={13} />검색된 법령 원문만 근거로 답변합니다.</p></div>
        </div> : <div className="conversation-inner">
          <div className="question-header"><div><span className="eyebrow">질문</span><h1>{submittedQuestion}</h1></div></div>
          <article className="answer-card"><div className="answer-heading"><div className="ai-mark"><Icon name="sparkle" size={18} /></div><div><span>AI 답변</span><small>{loading ? "관련 법령을 검색하고 있습니다" : result ? `조문 근거 ${result.sources.length}개를 확인했습니다` : "답변을 생성하지 못했습니다"}</small></div></div><div className="answer-content">
            {loading && <div className="loading-state"><span className="loading-spinner" />근거를 검색하고 답변을 작성하는 중입니다…</div>}
            {error && <div className="error-state"><strong>연결 오류</strong><p>{error}</p><button onClick={() => void runQuestion(submittedQuestion)}>다시 시도</button></div>}
            {result && <><h2>근거 기반 답변</h2><AnswerBody text={result.answer} selected={selectedCitation} onCitation={selectCitation} /><div className="answer-note"><strong>안내</strong><p>검색된 AI 기본법 원문 기반 답변이며 법률 자문을 대신하지 않습니다.</p></div></>}
          </div>{result && <div className="answer-footer"><div><button onClick={() => void copyAnswer()}><Icon name={copied ? "check" : "copy"} size={16} />{copied ? "복사됨" : "답변 복사"}</button><button onClick={() => void runQuestion(submittedQuestion, true)}><Icon name="search" size={15} />다시 검색</button></div><span>{result.method}{result.cache_hit ? " · PostgreSQL Cache" : ""}</span></div>}</article>
          {result && <div className="process-panel"><button className="process-trigger" onClick={() => setProcessOpen(!processOpen)}><span><Icon name="check" size={16} />검색 과정 보기</span><span className="process-summary">검색 조문 {result.retrieved_articles.length}개 · 근거 {result.sources.length}개 · {result.cache_hit ? `기존 검색 ${(result.processing_ms / 1000).toFixed(1)}초 · 캐시 조회 ${(result.elapsed_ms / 1000).toFixed(1)}초` : `${(result.elapsed_ms / 1000).toFixed(1)}초`}</span><Icon name="chevron" size={16} /></button>{processOpen && <div className="process-detail"><div><span>1</span><p><b>Hybrid 검색</b><small>Dense와 BM25 결과를 RRF로 결합</small></p></div>{result.method.includes("Reranking") && <div><span>2</span><p><b>정의형 조건부 리랭킹</b><small>정의 질문의 후보 조문을 Qwen으로 재정렬</small></p></div>}<div><span>{result.method.includes("Reranking") ? 3 : 2}</span><p><b>부모 조문 확장</b><small>검색 청크를 전체 조문 근거로 연결</small></p></div><div><span>{result.method.includes("Reranking") ? 4 : 3}</span><p><b>근거 기반 답변</b><small>근거에 없는 내용은 추측하지 않음</small></p></div></div>}</div>}
        </div>}
        {screen === "answer" && <form className="composer-wrap" onSubmit={submitQuestion}><div className="composer"><input aria-label="후속 질문" disabled={loading} onChange={(event) => setQuestion(event.target.value)} placeholder="후속 질문을 입력하세요" value={question} /><button aria-label="질문 보내기" className="send-button" disabled={loading} type="submit"><Icon name="send" size={17} /></button><span>AI 기본법 본문에서 근거를 찾아 답합니다</span></div></form>}
      </section>
      {screen === "answer" && result && !evidenceOpen && <button className="evidence-restore" onClick={() => setEvidenceOpen(true)}><Icon name="file" size={17} />근거 조문 <span>{result.sources.length}</span></button>}
      {screen === "answer" && result && <aside className={`evidence-panel ${evidenceOpen ? "evidence-open" : ""}`}><div className="evidence-header"><div><h2>근거 조문</h2><span>답변에 사용된 근거 {result.sources.length}개</span></div><button aria-label="근거 패널 닫기" onClick={() => setEvidenceOpen(false)}><Icon name="collapse" /></button></div><div className="evidence-tabs"><button className="active">인용 근거 <span>{result.sources.length}</span></button></div><div className="evidence-scroll">{result.sources.map((source, index) => <article className={`evidence-card ${selectedCitation === source.source_id ? "selected" : ""}`} key={source.source_id} onClick={() => setSelectedCitation(source.source_id)}><div className="evidence-card-top"><span className="source-number">{index + 1}</span><span className="used-badge"><Icon name="check" size={11} />{source.source_id}</span></div><div className="law-name">인공지능 발전과 신뢰 기반 조성 등에 관한 기본법</div><div className="law-path">{sourceLocation(source)}</div><h3>{source.article}{source.title ? `(${source.title})` : ""}</h3><blockquote>{articleOpen === source.source_id ? source.content : `${source.content.slice(0, 420)}${source.content.length > 420 ? "…" : ""}`}</blockquote>{source.content.length > 420 && <button className="full-article-button" onClick={(event) => { event.stopPropagation(); setArticleOpen(articleOpen === source.source_id ? "" : source.source_id); }}><Icon name="book" size={16} />{articleOpen === source.source_id ? "원문 접기" : "원문 전체 보기"}<Icon name="chevron" size={15} /></button>}<a href="https://www.law.go.kr/법령/인공지능발전과신뢰기반조성등에관한기본법" target="_blank" rel="noreferrer">국가법령정보센터에서 보기 <Icon name="external" size={14} /></a></article>)}<div className="source-notice"><Icon name="clock" size={16} /><p><b>원문 확인 안내</b><span>최신 개정 여부는 국가법령정보센터에서 다시 확인하세요.</span></p></div></div></aside>}
    </div>
    {deleteTarget && (
      <div
        className="confirm-overlay"
        role="presentation"
        onMouseDown={() => setDeleteTarget(null)}
      >
        <div
          className="confirm-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="delete-confirm-title"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="confirm-icon">
            <Icon name="archive" size={20} />
          </div>

          <h2 id="delete-confirm-title">
            {deleteTarget === "all"
              ? "전체 질문을 삭제할까요?"
              : "이 질문을 삭제할까요?"}
          </h2>

          <p>
            {deleteTarget === "all" ? (
              <>
                기존 질문들이 모두 삭제됩니다.
                <br />
                삭제하시겠습니까?
              </>
            ) : (
              <>
                선택한 질문과 저장된 화면 결과가 삭제됩니다.
                <br />
                삭제하시겠습니까?
              </>
            )}
          </p>

          <div className="confirm-actions">
            <button
              className="confirm-cancel"
              onClick={() => setDeleteTarget(null)}
            >
              아니오
            </button>
            <button
              className="confirm-delete"
              autoFocus
              onClick={confirmDelete}
            >
              예
            </button>
          </div>
        </div>
      </div>
    )}
  </main>;
}
