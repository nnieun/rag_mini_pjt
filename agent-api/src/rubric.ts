export type Criterion = {
  id: string;
  name: string;
  description: string;
};

export const RUBRIC: Criterion[] = [
  {
    id: "category_correct",
    name: "분류 정확성",
    description: "category가 문서 내용에 비추어 올바른가 (정답 카테고리와 일치하는가).",
  },
  {
    id: "field_completeness",
    name: "필드 완전성",
    description:
      "요청된 fields_to_extract 각각에 대해 문서에 실제로 존재하는 값을 빠짐없이 추출했는가. " +
      "존재하지 않는 값을 missing_fields로 올바르게 표시했는가.",
  },
  {
    id: "groundedness",
    name: "근거 충실성",
    description:
      "추출된 각 필드의 source_quote가 원문에 실제로 존재하는 문구이며, value를 정확히 뒷받침하는가. " +
      "원문에 없는 내용을 지어내지 않았는가 (환각 없음).",
  },
  {
    id: "reason_quality",
    name: "분류 근거 설명",
    description: "classification.reason이 분류 결정을 구체적이고 타당하게 설명하는가.",
  },
];

export function buildRubricText(): string {
  return RUBRIC.map((c, i) => `${i + 1}. ${c.name} (${c.id}): ${c.description}`).join("\n");
}
