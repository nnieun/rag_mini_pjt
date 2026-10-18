import { z } from "zod";

const GLOSSARY: Record<string, string> = {
  nda: "비밀유지계약(Non-Disclosure Agreement)",
  po: "구매주문서(Purchase Order)",
  sla: "서비스수준협약(Service Level Agreement)",
  msa: "기본계약(Master Service Agreement)",
};

export const LookupGlossaryArgs = z.object({
  term: z.string().min(1),
});
export type LookupGlossaryArgs = z.infer<typeof LookupGlossaryArgs>;

export const lookupGlossaryTool = {
  name: "lookup_glossary",
  description:
    "문서에 등장하는 약어나 전문 용어의 뜻을 조회한다. 확신이 없는 약어가 있으면 분석 전에 호출한다.",
  inputSchema: {
    type: "object" as const,
    properties: {
      term: { type: "string", description: "조회할 약어 또는 용어" },
    },
    required: ["term"],
  },
};

export function executeLookupGlossary(args: LookupGlossaryArgs): string {
  const parsed = LookupGlossaryArgs.parse(args);
  const key = parsed.term.trim().toLowerCase();
  return GLOSSARY[key] ?? `"${parsed.term}"에 대한 사전 정의를 찾을 수 없습니다.`;
}

export const ALLOWED_TOOLS = new Set(["lookup_glossary"]);
