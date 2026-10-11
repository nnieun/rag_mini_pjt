export type LawSource = {
  source_id: string;
  article: string;
  paragraph: string;
  item: string;
  subitem: string;
  title: string;
  content: string;
};

export type AskResponse = {
  answer: string;
  sources: LawSource[];
  method: string;
  retrieved_articles: string[];
  elapsed_ms: number;
  cache_hit: boolean;
  processing_ms: number;
};

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export async function askLaw(question: string, refresh = false): Promise<AskResponse> {
  const response = await fetch(`${API_BASE_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, refresh }),
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
