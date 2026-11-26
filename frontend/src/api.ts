export type LawSource = {
  source_id: string;
  article: string;
  paragraph: string;
  item: string;
  subitem: string;
  title: string;
  content: string;
  highlight_text: string;
};

export type AskResponse = {
  answer: string;
  sources: LawSource[];
  method: string;
  retrieved_articles: string[];
  elapsed_ms: number;
  cache_hit: boolean;
  processing_ms: number;
  total_relevant: number;
  displayed_count: number;
  has_more: boolean;
  status: string;
  missing_fields: string[];
  request_id: string;
  model_usage: Record<string, number | null>;
  resolved_question: string;
};

export type ConversationHistoryItem = {
  question: string;
  answer: string;
  source_articles: string[];
};

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export function reportUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

export async function askLaw(
  question: string,
  refresh = false,
  history: ConversationHistoryItem[] = [],
  threadId?: string,
): Promise<AskResponse> {
  const response = await fetch(`${API_BASE_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, refresh, history, thread_id: threadId }),
  });

  if (!response.ok) {
    let message = `요청에 실패했습니다. (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // JSON이 아닌 오류 응답에는 기본 메시지를 사용합니다.
    }
    throw new Error(message);
  }

  return (await response.json()) as AskResponse;
}

export type ComplianceObligation = {
  article: string;
  title: string;
  applies: "해당" | "해당 가능" | "해당 없음" | "판단 정보 부족";
  reason: string;
  actions: string[];
  source_ids: string[];
};

export type ComplianceAssessment = {
  high_impact: "yes" | "no" | "uncertain";
  high_impact_categories: string[];
  is_generative: boolean;
  obligations: ComplianceObligation[];
  confidence: number;
  assumptions: string[];
  summary: string;
  disclaimer: string;
};

export type ComplianceRunStatus = "queued" | "running" | "awaiting_approval" | "completed" | "rejected" | "failed";

export type ComplianceRun = {
  run_id: string;
  status: ComplianceRunStatus;
  source_type: string;
  filename: string | null;
  high_impact: string | null;
  confidence: number | null;
  assessment: ComplianceAssessment | null;
  review: { status: string; reviewer?: string; comment?: string; reasons?: string[] } | null;
  review_request: { reasons: string[]; confidence: number; citation_errors: string[] } | null;
  report_url: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  events_url: string;
};

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `요청에 실패했습니다. (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // JSON이 아닌 오류 응답에는 기본 메시지를 사용합니다.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function startComplianceRun(description: string): Promise<ComplianceRun> {
  const response = await fetch(`${API_BASE_URL}/agents/compliance/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
  return parseJson<ComplianceRun>(response);
}

export async function uploadComplianceFile(file: File): Promise<ComplianceRun> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE_URL}/agents/compliance/runs/upload`, { method: "POST", body: form });
  return parseJson<ComplianceRun>(response);
}

export async function getComplianceRun(runId: string): Promise<ComplianceRun> {
  return parseJson<ComplianceRun>(await fetch(`${API_BASE_URL}/agents/compliance/runs/${runId}`));
}

export async function decideComplianceRun(runId: string, approved: boolean, reviewer: string, comment: string): Promise<ComplianceRun> {
  const response = await fetch(`${API_BASE_URL}/agents/compliance/runs/${runId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, reviewer, comment }),
  });
  return parseJson<ComplianceRun>(response);
}

export function complianceEventsUrl(runId: string) {
  return `${API_BASE_URL}/agents/compliance/runs/${runId}/events`;
}
