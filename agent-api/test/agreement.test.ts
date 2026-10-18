import { describe, expect, it } from "vitest";
import { computeAgreement, type JudgeHumanPair } from "../src/agreement.js";

function pair(exampleId: string, judgeScore: 0 | 1, humanScore: 0 | 1): JudgeHumanPair {
  return {
    exampleId,
    judge: {
      criteria: [{ criterion_id: "groundedness", score: judgeScore, rationale: "x" }],
      overall_pass: judgeScore === 1,
      summary: "s",
    },
    human: { example_id: exampleId, scores: { groundedness: humanScore } },
  };
}

describe("computeAgreement", () => {
  it("reports 100% agreement and kappa 1 when judge and human always match", () => {
    const pairs = [pair("a", 1, 1), pair("b", 0, 0), pair("c", 1, 1)];
    const [result] = computeAgreement(pairs);
    expect(result.agreementRate).toBe(1);
    expect(result.cohenKappa).toBeCloseTo(1, 5);
    expect(result.n).toBe(3);
  });

  it("reports 0% agreement when judge and human always disagree", () => {
    const pairs = [pair("a", 1, 0), pair("b", 0, 1)];
    const [result] = computeAgreement(pairs);
    expect(result.agreementRate).toBe(0);
  });

  it("ignores criteria missing from the human score", () => {
    const pairs: JudgeHumanPair[] = [
      {
        exampleId: "a",
        judge: {
          criteria: [{ criterion_id: "unscored_by_human", score: 1, rationale: "x" }],
          overall_pass: true,
          summary: "s",
        },
        human: { example_id: "a", scores: {} },
      },
    ];
    const [result] = computeAgreement(pairs);
    expect(result.n).toBe(0);
    expect(result.agreementRate).toBe(0);
  });
});
