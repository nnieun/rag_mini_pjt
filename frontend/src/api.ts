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
