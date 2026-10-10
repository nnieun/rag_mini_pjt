import { FormEvent, ReactNode, useState } from "react";

type IconName =
  | "archive"
  | "arrow"
  | "book"
  | "check"
  | "chevron"
  | "clock"
  | "close"
  | "collapse"
  | "copy"
  | "external"
  | "file"
  | "history"
  | "menu"
  | "message"
  | "plus"
  | "search"
  | "send"
  | "sparkle";

const iconPaths: Record<IconName, ReactNode> = {
  archive: <><path d="M3 6h18" /><path d="M5 6v14h14V6" /><path d="M9 10h6" /><path d="M8 3h8l2 3H6l2-3Z" /></>,
  arrow: <><path d="m9 18 6-6-6-6" /></>,
  book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  close: <><path d="m6 6 12 12" /><path d="m18 6-12 12" /></>,
  collapse: <><path d="m15 18-6-6 6-6" /></>,
  copy: <><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
  external: <><path d="M15 4h5v5" /><path d="m20 4-9 9" /><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /><path d="M8 9h8M8 13h5" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>,
  sparkle: <><path d="m12 3 1.3 3.7L17 8l-3.7 1.3L12 13l-1.3-3.7L7 8l3.7-1.3Z" /><path d="m5 14 .8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8Z" /></>,
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {iconPaths[name]}
    </svg>
  );
}

function Citation({
  children,
  active = false,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`citation ${active ? "citation-active" : ""}`} onClick={onClick}>
      <Icon name="file" size={13} />
      {children}
    </button>
  );
}

const recentQuestions = [
  "고영향 인공지능의 정의",
  "인공지능사업자의 투명성 의무",
  "안전성 확보 의무 적용 기준",
];

const exampleQuestions = [
  "고영향 인공지능의 정의를 찾아줘",
  "인공지능사업자의 의무 관련 조문을 정리해줘",
  "투명성 관련 조문을 찾아줘",
];

export default function App() {
  const [screen, setScreen] = useState<"empty" | "answer">("answer");
  const [selectedCitation, setSelectedCitation] = useState(1);
  const [articleOpen, setArticleOpen] = useState(false);
  const [processOpen, setProcessOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [copied, setCopied] = useState(false);

  const selectCitation = (citation: number) => {
    setSelectedCitation(citation);
    setEvidenceOpen(true);
  };

  const submitQuestion = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    setScreen("answer");
    setQuestion("");
  };

  const startNewQuestion = () => {
    setScreen("empty");
    setQuestion("");
    setMobileNavOpen(false);
    setEvidenceOpen(false);
  };

  const openExample = (example: string) => {
    setQuestion(example);
  };

  const copyAnswer = () => {
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <button className="mobile-icon-button" aria-label="메뉴 열기" onClick={() => setMobileNavOpen(true)}>
            <Icon name="menu" size={20} />
          </button>
          <div className="brand-mark"><Icon name="book" size={19} /></div>
          <strong className="brand-name">법령리서치 AI</strong>
          <span className="beta-label">BETA</span>
        </div>
        <div className="source-meta">
          <span><b>검색 대상</b> AI 기본법 본문</span>
          <i />
          <span><b>법령 시행일</b> 2026. 1. 22.</span>
          <i />
          <span><b>데이터 수집일</b> 2025. 6. 18.</span>
        </div>
        <button className="header-icon-button" aria-label="검색">
          <Icon name="search" />
        </button>
      </header>

      <div className={`workspace ${screen === "empty" ? "empty-workspace" : ""}`}>
        <aside className={`sidebar ${mobileNavOpen ? "mobile-nav-open" : ""}`}>
          <div className="mobile-sidebar-head">
            <strong>법령리서치 AI</strong>
            <button aria-label="메뉴 닫기" onClick={() => setMobileNavOpen(false)}><Icon name="close" /></button>
          </div>
          <button className="new-question" onClick={startNewQuestion}>
            <Icon name="plus" />
            새 질문
          </button>
          <nav className="primary-nav" aria-label="주요 메뉴">
            <button className="nav-item active"><Icon name="message" />질문 기록</button>
            <button className="nav-item"><Icon name="archive" />조문 탐색</button>
          </nav>

          <div className="recent-section">
            <div className="section-label">최근 질문</div>
            {recentQuestions.map((item, index) => (
              <button
                className={`recent-item ${screen === "answer" && index === 0 ? "selected" : ""}`}
                key={item}
                onClick={() => {
                  setScreen("answer");
                  setEvidenceOpen(true);
                  setMobileNavOpen(false);
                }}
              >
                <span>{item}</span>
                <small>{index === 0 ? "방금 전" : index === 1 ? "어제" : "6월 16일"}</small>
              </button>
            ))}
          </div>

          <div className="sidebar-status">
            <div><span className="status-dot" />법령 데이터 연결됨</div>
            <p>대한민국 국가법령정보센터<br />법령 원문 기준</p>
          </div>
        </aside>
        {mobileNavOpen && <button className="scrim" aria-label="메뉴 닫기" onClick={() => setMobileNavOpen(false)} />}

        <section className={`conversation ${screen === "empty" ? "empty-conversation" : ""}`}>
          {screen === "empty" ? (
            <div className="empty-state">
              <div className="empty-hero">
                <div className="empty-icon"><Icon name="book" size={25} /></div>
                <span className="empty-eyebrow">AI 기본법 법령 리서치</span>
                <h1>AI 기본법, 조문 근거와<br />함께 확인하세요.</h1>
                <p>궁금한 의무나 서비스 상황을 입력하면 관련 조문을 찾아<br className="desktop-break" /> 원문과 함께 답변해 드립니다.</p>
              </div>

              <form className="empty-search" onSubmit={submitQuestion}>
                <div className="empty-input-wrap">
                  <Icon name="search" size={19} />
                  <input
                    aria-label="새 질문"
                    autoFocus
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="궁금한 의무나 서비스 상황을 입력하세요"
                    value={question}
                  />
                  <button aria-label="질문 보내기" type="submit"><Icon name="send" size={17} /></button>
                </div>
                <div className="empty-input-meta">
                  <span><Icon name="check" size={13} />AI 기본법 본문에서만 검색합니다</span>
                  <span>Enter로 질문하기</span>
                </div>
              </form>

              <div className="example-section">
                <div className="example-label">이런 질문을 해보세요</div>
                <div className="example-list">
                  {exampleQuestions.map((example, index) => (
                    <button key={example} onClick={() => openExample(example)}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{example}</strong>
                      <Icon name="arrow" size={16} />
                    </button>
                  ))}
                </div>
              </div>

              <div className="empty-source-card">
                <div className="empty-source-title">
                  <Icon name="archive" size={17} />
                  <div><strong>현재 검색 범위</strong><span>답변 생성에 사용하는 법령 데이터</span></div>
                </div>
                <div className="empty-source-grid">
                  <div><span>검색 대상</span><strong>AI 기본법 본문</strong></div>
                  <div><span>법령 시행일</span><strong>2026. 1. 22.</strong></div>
                  <div><span>데이터 수집일</span><strong>2025. 6. 18.</strong></div>
                </div>
                <p><Icon name="file" size={13} />시행령은 현재 검색 범위에 포함되지 않습니다.</p>
              </div>
            </div>
          ) : (
          <div className="conversation-inner">
            <div className="question-header">
              <div>
                <span className="eyebrow">질문</span>
                <h1>고영향 인공지능의 정의를 찾아줘</h1>
              </div>
              <button className="more-button" aria-label="더 보기">•••</button>
            </div>

            <article className="answer-card">
              <div className="answer-heading">
                <div className="ai-mark"><Icon name="sparkle" size={18} /></div>
                <div>
                  <span>AI 답변</span>
                  <small>조문 근거 2개를 확인했습니다</small>
                </div>
              </div>

              <div className="answer-content">
                <h2>핵심 답변</h2>
                <p>
                  <strong>고영향 인공지능</strong>은 사람의 생명·신체의 안전 및 기본권에 중대한 영향을
                  미치거나 위험을 초래할 우려가 있는 인공지능시스템을 말합니다.
                  <Citation active={selectedCitation === 1} onClick={() => selectCitation(1)}>
                    제2조 제4호
                  </Citation>
                </p>

                <h2>어떤 영역이 해당하나요?</h2>
                <p>
                  법률은 에너지, 먹는물, 보건의료, 원자력, 범죄 수사, 채용·대출 심사 등 국민의 권리와
                  안전에 직접 영향을 주는 영역에서 활용되는 인공지능을 고영향 인공지능의 판단 대상으로
                  정하고 있습니다.
                  <Citation active={selectedCitation === 2} onClick={() => selectCitation(2)}>
                    제2조 제4호 가목–차목
                  </Citation>
                </p>

                <div className="interpretation">
                  <div className="interpretation-label"><Icon name="sparkle" size={14} />AI 해석</div>
                  <p>
                    특정 서비스가 고영향 인공지능에 해당하는지는 <strong>사용 분야</strong>와 해당
                    시스템이 <strong>사람의 권리·안전에 미치는 영향</strong>을 함께 검토해야 합니다.
                    단순히 AI 기술을 사용했다는 사실만으로 자동 분류되는 것은 아닙니다.
                  </p>
                </div>

                <div className="answer-note">
                  <strong>확인이 필요한 부분</strong>
                  <p>구체적인 서비스의 해당 여부는 적용 분야와 실제 사용 방식에 따라 달라질 수 있습니다.</p>
                </div>
              </div>

              <div className="answer-footer">
                <button onClick={copyAnswer}><Icon name={copied ? "check" : "copy"} size={16} />{copied ? "복사됨" : "답변 복사"}</button>
                <span>AI 답변은 법률 자문을 대신하지 않습니다.</span>
              </div>
            </article>

            <div className="process-panel">
              <button className="process-trigger" onClick={() => setProcessOpen(!processOpen)}>
                <span><Icon name="check" size={16} />검색 과정 보기</span>
                <span className="process-summary">관련 조문 12개 검색 · 근거 2개 사용 · 4.2초</span>
                <Icon name="chevron" size={16} />
              </button>
              {processOpen && (
                <div className="process-detail">
                  <div><span>1</span><p><b>관련 조문 검색</b><small>키워드·의미 기반 검색으로 12개 청크 탐색</small></p></div>
                  <div><span>2</span><p><b>근거 선별</b><small>질문 관련도를 기준으로 근거 2개 선택</small></p></div>
                  <div><span>3</span><p><b>답변 작성</b><small>사용된 조문의 구조 경로와 원문 연결</small></p></div>
                </div>
              )}
            </div>

            <div className="suggestions">
              <span>이어서 물어보기</span>
              <div>
                <button onClick={() => setQuestion("고영향 인공지능사업자에게 어떤 의무가 있나요?")}>사업자에게 어떤 의무가 있나요?</button>
                <button onClick={() => setQuestion("해당 여부는 누가 확인해주나요?")}>해당 여부는 누가 확인해주나요?</button>
              </div>
            </div>
          </div>
          )}

          {screen === "answer" && <form className="composer-wrap" onSubmit={submitQuestion}>
            <div className="composer">
              <input
                aria-label="후속 질문"
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="후속 질문을 입력하세요"
                value={question}
              />
              <button aria-label="질문 보내기" className="send-button" type="submit"><Icon name="send" size={17} /></button>
              <span>AI 기본법 본문에서 근거를 찾아 답합니다</span>
            </div>
          </form>}
        </section>

        {screen === "answer" && !evidenceOpen && (
          <button className="evidence-restore" onClick={() => setEvidenceOpen(true)}>
            <Icon name="file" size={17} />근거 조문 <span>2</span>
          </button>
        )}

        {screen === "answer" && <aside className={`evidence-panel ${evidenceOpen ? "evidence-open" : ""}`}>
          <div className="evidence-header">
            <div>
              <h2>근거 조문</h2>
              <span>답변에 사용된 근거 2개</span>
            </div>
            <button aria-label="근거 패널 닫기" onClick={() => setEvidenceOpen(false)}>
              <Icon name="collapse" />
            </button>
          </div>

          <div className="evidence-tabs">
            <button className="active">인용 근거 <span>2</span></button>
            <button>관련 조문 <span>10</span></button>
          </div>

          <div className="evidence-scroll">
            <article className={`evidence-card ${selectedCitation === 1 ? "selected" : ""}`} onClick={() => setSelectedCitation(1)}>
              <div className="evidence-card-top">
                <span className="source-number">1</span>
                <span className="used-badge"><Icon name="check" size={11} />답변에 사용됨</span>
              </div>
              <div className="law-name">인공지능 발전과 신뢰 기반 조성 등에 관한 기본법</div>
              <div className="law-path">제1장 총칙 <Icon name="chevron" size={12} /> 제2조 정의 <Icon name="chevron" size={12} /> 제4호</div>
              <h3>제2조(정의)</h3>
              <blockquote>
                4. “고영향 인공지능”이란 <mark>사람의 생명, 신체의 안전 및 기본권에 중대한 영향을 미치거나 위험을 초래할 우려가 있는 인공지능시스템</mark>으로서 다음 각 목의 어느 하나의 영역에서 활용되는 것을 말한다.
              </blockquote>
              <button className="full-article-button" onClick={(event) => { event.stopPropagation(); setArticleOpen(!articleOpen); }}>
                <Icon name="book" size={16} />
                {articleOpen ? "전체 조문 접기" : "조문 전체 보기"}
                <Icon name="chevron" size={15} />
              </button>
              {articleOpen && (
                <div className="full-article">
                  <div className="context-label">전체 조문 · 선택 위치 유지</div>
                  <p><b>제2조(정의)</b> 이 법에서 사용하는 용어의 뜻은 다음과 같다.</p>
                  <p>1. “인공지능”이란 학습, 추론, 지각, 판단, 언어의 이해 등 인간이 가진 지적 능력을 전자적 방법으로 구현한 것을 말한다.</p>
                  <p className="current">4. “고영향 인공지능”이란 사람의 생명, 신체의 안전 및 기본권에 중대한 영향을 미치거나 위험을 초래할 우려가 있는 인공지능시스템으로서 다음 각 목의 어느 하나의 영역에서 활용되는 것을 말한다.</p>
                  <p>가. 에너지의 공급 및 이용</p>
                  <p>나. 먹는물의 생산 및 공급</p>
                  <p>다. 보건의료의 제공 및 이용</p>
                </div>
              )}
              <a href="https://www.law.go.kr/" target="_blank" rel="noreferrer">
                국가법령정보센터에서 보기 <Icon name="external" size={14} />
              </a>
            </article>

            <article className={`evidence-card compact ${selectedCitation === 2 ? "selected" : ""}`} onClick={() => setSelectedCitation(2)}>
              <div className="evidence-card-top">
                <span className="source-number">2</span>
                <span className="used-badge"><Icon name="check" size={11} />답변에 사용됨</span>
              </div>
              <div className="law-name">인공지능 발전과 신뢰 기반 조성 등에 관한 기본법</div>
              <div className="law-path">제1장 총칙 <Icon name="chevron" size={12} /> 제2조 정의 <Icon name="chevron" size={12} /> 제4호 가목–차목</div>
              <h3>고영향 인공지능의 적용 영역</h3>
              <blockquote>
                <mark>에너지, 먹는물, 보건의료, 원자력시설, 범죄 수사, 채용·대출 심사</mark> 등 대통령령으로 정하는 영역
              </blockquote>
              <button className="full-article-button">
                <Icon name="book" size={16} />조문 전체 보기<Icon name="chevron" size={15} />
              </button>
            </article>

            <div className="source-notice">
              <Icon name="clock" size={16} />
              <p><b>원문 확인 안내</b><span>법령 개정 여부와 최신 원문은 국가법령정보센터에서 다시 확인하세요.</span></p>
            </div>
          </div>
        </aside>}
      </div>
    </main>
  );
}
