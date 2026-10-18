import { z } from "zod";

export const DocumentCategory = z.enum([
  "contract",
  "invoice",
  "support_request",
  "report",
  "other",
]);
export type DocumentCategory = z.infer<typeof DocumentCategory>;

export const ClassificationResult = z.object({
  category: DocumentCategory,
  confidence: z.number().min(0).max(1),
  reason: z.string().min(1),
});
export type ClassificationResult = z.infer<typeof ClassificationResult>;

export const ExtractedField = z.object({
  name: z.string().min(1),
  value: z.string().nullable(),
  source_quote: z.string().nullable(),
});
export type ExtractedField = z.infer<typeof ExtractedField>;

export const ExtractionResult = z.object({
  fields: z.array(ExtractedField),
  missing_fields: z.array(z.string()),
});
export type ExtractionResult = z.infer<typeof ExtractionResult>;

export const AnalyzeInput = z.object({
  text: z.string().min(1, "text must not be empty"),
  fields_to_extract: z.array(z.string()).min(1),
});
export type AnalyzeInput = z.infer<typeof AnalyzeInput>;

export const AnalyzeResult = z.object({
  classification: ClassificationResult,
  extraction: ExtractionResult,
  status: z.enum(["ok", "needs_review", "failed"]),
  errors: z.array(z.string()),
});
export type AnalyzeResult = z.infer<typeof AnalyzeResult>;

export const CriterionScore = z.object({
  criterion_id: z.string().min(1),
  score: z.union([z.literal(0), z.literal(1)]),
  rationale: z.string().min(1),
});
export type CriterionScore = z.infer<typeof CriterionScore>;

export const JudgeVerdict = z.object({
  criteria: z.array(CriterionScore).min(1),
  overall_pass: z.boolean(),
  summary: z.string().min(1),
});
export type JudgeVerdict = z.infer<typeof JudgeVerdict>;

export const HumanScore = z.object({
  example_id: z.string().min(1),
  scores: z.record(z.union([z.literal(0), z.literal(1)])),
});
export type HumanScore = z.infer<typeof HumanScore>;
