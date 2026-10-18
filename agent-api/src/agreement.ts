import { HumanScore, JudgeVerdict } from "./schema.js";

export type JudgeHumanPair = {
  exampleId: string;
  judge: JudgeVerdict;
  human: HumanScore;
};

export type CriterionAgreement = {
  criterionId: string;
  n: number;
  agreementRate: number;
  cohenKappa: number;
};

function cohenKappa(judgeLabels: number[], humanLabels: number[]): number {
  const n = judgeLabels.length;
  if (n === 0) return 0;
  let observedAgreement = 0;
  let judgePositive = 0;
  let humanPositive = 0;
  for (let i = 0; i < n; i++) {
    if (judgeLabels[i] === humanLabels[i]) observedAgreement += 1;
    judgePositive += judgeLabels[i];
    humanPositive += humanLabels[i];
  }
  const pObserved = observedAgreement / n;
  const pJudgePos = judgePositive / n;
  const pHumanPos = humanPositive / n;
  const pExpected = pJudgePos * pHumanPos + (1 - pJudgePos) * (1 - pHumanPos);
  if (pExpected === 1) return 1;
  return (pObserved - pExpected) / (1 - pExpected);
}

export function computeAgreement(pairs: JudgeHumanPair[]): CriterionAgreement[] {
  const criterionIds = new Set<string>();
  for (const pair of pairs) {
    for (const c of pair.judge.criteria) criterionIds.add(c.criterion_id);
  }

  const results: CriterionAgreement[] = [];
  for (const criterionId of criterionIds) {
    const judgeLabels: number[] = [];
    const humanLabels: number[] = [];
    for (const pair of pairs) {
      const judgeScore = pair.judge.criteria.find((c) => c.criterion_id === criterionId)?.score;
      const humanScore = pair.human.scores[criterionId];
      if (judgeScore === undefined || humanScore === undefined) continue;
      judgeLabels.push(judgeScore);
      humanLabels.push(humanScore);
    }
    const matches = judgeLabels.filter((v, i) => v === humanLabels[i]).length;
    results.push({
      criterionId,
      n: judgeLabels.length,
      agreementRate: judgeLabels.length > 0 ? matches / judgeLabels.length : 0,
      cohenKappa: cohenKappa(judgeLabels, humanLabels),
    });
  }
  return results.sort((a, b) => a.criterionId.localeCompare(b.criterionId));
}
