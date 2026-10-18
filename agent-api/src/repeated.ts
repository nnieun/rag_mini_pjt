export async function repeatedRun<T>(fn: (iteration: number) => Promise<T>, times: number): Promise<T[]> {
  const results: T[] = [];
  for (let i = 0; i < times; i++) {
    results.push(await fn(i));
  }
  return results;
}

export type BinarySummary = {
  n: number;
  passCount: number;
  passRate: number;
  wilsonCi95: [number, number];
};

function wilsonInterval(successes: number, n: number, z = 1.96): [number, number] {
  if (n === 0) return [0, 0];
  const p = successes / n;
  const denominator = 1 + (z * z) / n;
  const center = p + (z * z) / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [(center - margin) / denominator, (center + margin) / denominator];
}

export function summarizeBinary(results: boolean[]): BinarySummary {
  const n = results.length;
  const passCount = results.filter(Boolean).length;
  return {
    n,
    passCount,
    passRate: n > 0 ? passCount / n : 0,
    wilsonCi95: wilsonInterval(passCount, n),
  };
}

function normalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const absX = Math.abs(x);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const t = 1 / (1 + p * absX);
  const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX);
  return sign * y;
}

export type TwoProportionComparison = {
  before: BinarySummary;
  after: BinarySummary;
  diff: number;
  zStat: number;
  pValue: number;
  significantAt05: boolean;
};

export function compareBinaryRates(before: boolean[], after: boolean[]): TwoProportionComparison {
  const beforeSummary = summarizeBinary(before);
  const afterSummary = summarizeBinary(after);
  const n1 = beforeSummary.n;
  const n2 = afterSummary.n;
  const p1 = beforeSummary.passRate;
  const p2 = afterSummary.passRate;
  const pooled = (beforeSummary.passCount + afterSummary.passCount) / (n1 + n2 || 1);
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2)) || Number.EPSILON;
  const zStat = (p2 - p1) / se;
  const pValue = 2 * (1 - normalCdf(Math.abs(zStat)));

  return {
    before: beforeSummary,
    after: afterSummary,
    diff: p2 - p1,
    zStat,
    pValue,
    significantAt05: pValue < 0.05,
  };
}
