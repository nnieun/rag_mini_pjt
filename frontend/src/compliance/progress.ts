// 컴플라이언스 실행의 SSE 이벤트를 화면용 단계 목록으로 바꾼다. DOM과 무관해 단위 테스트한다.

export type ComplianceEvent = {
  step: string;
  status?: string;
  tool_calls?: string[];
  calls?: { name: string; status: string }[];
  tool_call_count?: number;
  method?: string;
  citation_errors?: number;
  next?: string;
  review?: string;
  profile?: { name?: string; domains?: string[]; is_generative?: boolean | null };
};

export type ProgressStep = { key: string; label: string; detail: string; state: "done" | "active" | "error" };

export const STOP_STATUSES = new Set(["awaiting_approval", "completed", "rejected", "failed"]);

const STATUS_LABELS: Record<string, string> = {
  queued: "대기 중",
  running: "실행 중",
  awaiting_approval: "사람 검토 대기",
  completed: "완료",
  rejected: "반려됨",
  failed: "실패",
};

export function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

export function describeEvent(event: ComplianceEvent): Omit<ProgressStep, "key" | "state"> | null {
  switch (event.step) {
    case "ingest":
      return { label: "설명서 읽기", detail: "" };
    case "profile": {
      const domains = event.profile?.domains?.join(", ");
      return { label: "서비스 특성 추출", detail: domains ? `영역: ${domains}` : "" };
    }
    case "agent":
      return event.tool_calls && event.tool_calls.length > 0
        ? { label: "조사 계획", detail: `도구 ${event.tool_calls.length}개 호출: ${event.tool_calls.join(", ")}` }
        : { label: "조사 완료", detail: "" };
    case "tools": {
      const calls = event.calls ?? [];
      const failed = calls.filter((call) => call.status !== "ok").length;
      return { label: "조문 검색", detail: `${calls.length}건${failed ? ` (실패·생략 ${failed})` : ""} · 누적 ${event.tool_call_count ?? calls.length}회` };
    }
    case "assess":
      return { label: "의무 판정", detail: event.method === "rule" ? "규칙 기반 판정으로 대체" : "" };
    case "validate":
      return {
        label: "근거 인용 검증",
        detail: event.citation_errors ? `오류 ${event.citation_errors}건${event.next === "retry" ? ", 다시 판정" : ""}` : "통과",
      };
    case "awaiting_approval":
      return { label: "사람 검토 요청", detail: "" };
    case "human_review":
      return { label: "사람 검토", detail: event.review === "approved" ? "승인됨" : "반려됨" };
    case "finalize":
      return { label: "검토 불필요", detail: "" };
    default:
      return null;
  }
}

export function applyEvent(steps: ProgressStep[], event: ComplianceEvent): ProgressStep[] {
  if (event.step === "keepalive" || event.step === "status") return steps;
  const described = describeEvent(event);
  if (!described) return steps;
  const settled = steps.map((step) => (step.state === "active" ? { ...step, state: "done" as const } : step));
  const isError = event.step === "tools" && (event.calls ?? []).some((call) => call.status === "error");
  return [...settled, { key: `${steps.length}-${event.step}`, ...described, state: isError ? "error" : "active" }];
}

export function finishSteps(steps: ProgressStep[]): ProgressStep[] {
  return steps.map((step) => (step.state === "active" ? { ...step, state: "done" } : step));
}

export const CATEGORY_LABELS: Record<string, string> = {
  가: "에너지의 공급",
  나: "먹는물의 생산 공정",
  다: "보건의료의 제공 및 이용체계",
  라: "의료기기·디지털의료기기",
  마: "핵물질·원자력시설의 관리·운영",
  바: "범죄 수사·체포를 위한 생체인식정보 분석",
  사: "채용, 대출 심사 등 권리·의무에 중대한 영향을 주는 판단·평가",
  아: "교통수단·시설·체계의 주요 작동",
  자: "국가기관등의 공공서비스 자격·결정",
  차: "유아·초등·중등교육 학생 평가",
  카: "그 밖에 대통령령으로 정하는 영역",
};
