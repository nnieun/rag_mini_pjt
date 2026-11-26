import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  complianceEventsUrl,
  decideComplianceRun,
  getComplianceRun,
  reportUrl,
  startComplianceRun,
  uploadComplianceFile,
} from "../api";
import type { ComplianceRun } from "../api";
import { applyEvent, CATEGORY_LABELS, finishSteps, statusLabel, STOP_STATUSES } from "./progress";
import type { ComplianceEvent, ProgressStep } from "./progress";

const APPLIES = new Set(["해당", "해당 가능"]);
const HIGH_IMPACT_TEXT: Record<string, string> = { yes: "해당", no: "해당 없음", uncertain: "판단 보류" };

const EXAMPLE = "이력서와 자기소개서를 읽고 지원자별 직무 적합도 점수를 매겨 서류 합격 여부를 추천하는 채용 보조 AI. 국내 HR 기업이 개발해 기업 인사팀에 제공한다.";

export default function CompliancePanel() {
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [run, setRun] = useState<ComplianceRun | null>(null);
  const [steps, setSteps] = useState<ProgressStep[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const source = useRef<EventSource | null>(null);

  useEffect(() => () => source.current?.close(), []);

  const follow = (runId: string) => {
    source.current?.close();
    const events = new EventSource(complianceEventsUrl(runId));
    source.current = events;
    const handle = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as ComplianceEvent;
      setSteps((current) => applyEvent(current, event));
      if (event.step === "status" && event.status && STOP_STATUSES.has(event.status)) {
        events.close();
        setSteps((current) => finishSteps(current));
        void getComplianceRun(runId).then(setRun).catch((reason: Error) => setError(reason.message));
      }
    };
    for (const name of ["status", "ingest", "profile", "agent", "tools", "assess", "validate", "awaiting_approval", "human_review", "finalize"]) {
      events.addEventListener(name, handle as EventListener);
    }
    events.onerror = () => {
      // 연결이 끊기면 상태를 한 번 조회해 화면을 맞춘다.
      events.close();
      void getComplianceRun(runId).then(setRun).catch(() => undefined);
    };
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setSteps([]);
    setChecked({});
    try {
      const started = file ? await uploadComplianceFile(file) : await startComplianceRun(description.trim());
      setRun(started);
      follow(started.run_id);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approved: boolean) => {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      setRun(await decideComplianceRun(run.run_id, approved, reviewer.trim(), comment.trim()));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const assessment = run?.assessment ?? null;
  const running = run !== null && !STOP_STATUSES.has(run.status);
  const canSubmit = !busy && !running && (file !== null || description.trim().length >= 10);
  const selected = new Set(assessment?.high_impact_categories ?? []);

  return (
    <div className="compliance-panel">
      <div className="question-header"><div><span className="eyebrow">준수 점검</span><h1>AI 서비스의 AI 기본법 의무 점검</h1></div></div>

      <form className="compliance-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="service-description">서비스 설명</label>
        <textarea
          id="service-description"
          disabled={file !== null}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="무엇을 하는 AI인지, 어느 영역에서 누구에게 제공하는지, 생성형인지 적어 주세요."
          rows={6}
          value={description}
        />
        <div className="compliance-form-row">
          <label className="compliance-file">
            <input accept=".txt,.xml,.pdf,.png,.jpg,.jpeg" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file" />
            {file ? `파일: ${file.name}` : "또는 설명서 파일 올리기 (TXT, PDF, 이미지)"}
          </label>
          {file && <button className="compliance-link" onClick={() => setFile(null)} type="button">파일 빼기</button>}
          {!file && !description && <button className="compliance-link" onClick={() => setDescription(EXAMPLE)} type="button">예시 넣기</button>}
          <button className="compliance-submit" disabled={!canSubmit} type="submit">{running ? "점검 중…" : "점검 시작"}</button>
        </div>
      </form>

      {error && <div className="error-state"><strong>오류</strong><p>{error}</p></div>}

      {run && (
        <section className="compliance-progress" aria-live="polite">
          <div className="compliance-status"><span className={`compliance-badge status-${run.status}`}>{statusLabel(run.status)}</span><small>run {run.run_id.slice(0, 8)}</small></div>
          <ol>
            {steps.map((step) => (
              <li className={`step-${step.state}`} key={step.key}><strong>{step.label}</strong>{step.detail && <span>{step.detail}</span>}</li>
            ))}
            {running && steps.length === 0 && <li className="step-active"><strong>시작하는 중</strong></li>}
          </ol>
          {run.status === "failed" && <p className="compliance-error">점검이 실패했습니다 ({run.error_code ?? "알 수 없음"}). 잠시 뒤 다시 시도해 주세요.</p>}
        </section>
      )}

      {assessment && (
        <>
          <section className="compliance-summary">
            <div><span>고영향 인공지능</span><strong>{HIGH_IMPACT_TEXT[assessment.high_impact] ?? "-"}</strong></div>
            <div><span>생성형 인공지능</span><strong>{assessment.is_generative ? "예" : "아니오"}</strong></div>
            <div><span>판단 신뢰도</span><strong>{assessment.confidence.toFixed(2)}</strong></div>
            {assessment.summary && <p>{assessment.summary}</p>}
          </section>

          {run?.status === "awaiting_approval" && (
            <section className="compliance-review">
              <h2>사람 검토 필요</h2>
              <p>{run.review_request?.reasons.join(", ")}</p>
              <div className="compliance-review-fields">
                <input aria-label="검토자" maxLength={100} onChange={(event) => setReviewer(event.target.value)} placeholder="검토자 이름" value={reviewer} />
                <input aria-label="검토 의견" maxLength={2000} onChange={(event) => setComment(event.target.value)} placeholder="의견 (선택)" value={comment} />
              </div>
              <div className="compliance-review-actions">
                <button className="approve" disabled={busy} onClick={() => void decide(true)} type="button">승인</button>
                <button className="reject" disabled={busy} onClick={() => void decide(false)} type="button">반려</button>
              </div>
            </section>
          )}

          <section className="compliance-table-section">
            <h2>고영향 인공지능 영역 판단 (제2조제4호)</h2>
            <table className="compliance-table">
              <thead><tr><th>목</th><th>영역</th><th>판단</th></tr></thead>
              <tbody>
                {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                  <tr className={selected.has(key) ? "hit" : ""} key={key}><td>{key}목</td><td>{label}</td><td>{selected.has(key) ? "해당" : "-"}</td></tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="compliance-table-section">
            <h2>의무 체크리스트</h2>
            <ul className="obligation-list">
              {assessment.obligations.map((item) => {
                const applies = APPLIES.has(item.applies);
                return (
                  <li className={applies ? "applies" : "not-applies"} key={item.article}>
                    <label>
                      <input checked={Boolean(checked[item.article])} disabled={!applies} onChange={(event) => setChecked({ ...checked, [item.article]: event.target.checked })} type="checkbox" />
                      <span className="obligation-article">{item.article}</span>
                      <span className="obligation-title">{item.title}</span>
                      <span className={`obligation-applies applies-${item.applies.replace(/\s/g, "-")}`}>{item.applies}</span>
                    </label>
                    {(item.actions.length > 0 || item.reason) && <p>{item.actions.length > 0 ? item.actions.join(" · ") : item.reason}</p>}
                    {item.source_ids.length > 0 && <small>근거 {item.source_ids.join(", ")}</small>}
                  </li>
                );
              })}
            </ul>
          </section>

          {assessment.assumptions.length > 0 && <section className="compliance-table-section"><h2>판단에 쓴 가정</h2><ul className="assumption-list">{assessment.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></section>}

          <div className="compliance-footer">
            {run?.report_url ? <a className="compliance-submit" href={reportUrl(run.report_url)} rel="noreferrer" target="_blank">PDF 보고서 다운로드</a> : run?.status === "awaiting_approval" ? <span>승인 후 PDF 보고서가 만들어집니다.</span> : null}
            <p>{assessment.disclaimer}</p>
          </div>
        </>
      )}
    </div>
  );
}
