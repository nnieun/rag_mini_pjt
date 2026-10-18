import { DocumentCategory } from "./schema.js";

const KEYWORDS: Record<DocumentCategory, string[]> = {
  contract: ["계약", "nda", "msa", "조항", "당사자"],
  invoice: ["청구서", "세금계산서", "결제", "금액", "원"],
  support_request: ["문의", "오류", "요청", "불편", "처리해"],
  report: ["보고서", "분석", "요약", "결과"],
  other: [],
};

export function classifyByKeyword(text: string): DocumentCategory {
  const lower = text.toLowerCase();
  let best: DocumentCategory = "other";
  let bestScore = 0;
  for (const category of Object.keys(KEYWORDS) as DocumentCategory[]) {
    const score = KEYWORDS[category].filter((keyword) => lower.includes(keyword)).length;
    if (score > bestScore) {
      bestScore = score;
      best = category;
    }
  }
  return best;
}
