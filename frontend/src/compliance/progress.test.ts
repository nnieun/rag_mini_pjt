import { describe, expect, it } from "vitest";
import { applyEvent, finishSteps, statusLabel } from "./progress";
import type { ProgressStep } from "./progress";

describe("compliance progress", () => {
  it("turns events into steps and settles the previous step", () => {
    let steps: ProgressStep[] = [];
    steps = applyEvent(steps, { step: "status", status: "running" });
    steps = applyEvent(steps, { step: "ingest" });
    steps = applyEvent(steps, { step: "profile", profile: { domains: ["채용"] } });
    steps = applyEvent(steps, { step: "agent", tool_calls: ["SearchLaw", "GetArticle"] });
    steps = applyEvent(steps, { step: "tools", calls: [{ name: "SearchLaw", status: "ok" }, { name: "GetArticle", status: "skipped" }], tool_call_count: 2 });
    expect(steps.map((step) => step.label)).toEqual(["설명서 읽기", "서비스 특성 추출", "조사 계획", "조문 검색"]);
    expect(steps[1].detail).toBe("영역: 채용");
    expect(steps[2].detail).toBe("도구 2개 호출: SearchLaw, GetArticle");
    expect(steps[3].detail).toBe("2건 (실패·생략 1) · 누적 2회");
    expect(steps.slice(0, 3).every((step) => step.state === "done")).toBe(true);
    expect(steps[3].state).toBe("active");
  });

  it("marks tool errors and ignores keepalive and unknown steps", () => {
    let steps = applyEvent([], { step: "tools", calls: [{ name: "GetArticle", status: "error" }] });
    steps = applyEvent(steps, { step: "keepalive" });
    steps = applyEvent(steps, { step: "something-new" });
    expect(steps).toHaveLength(1);
    expect(steps[0].state).toBe("error");
  });

  it("describes validation retry and finishes active steps", () => {
    const steps = applyEvent([], { step: "validate", citation_errors: 2, next: "retry" });
    expect(steps[0].detail).toBe("오류 2건, 다시 판정");
    expect(finishSteps(steps)[0].state).toBe("done");
    expect(statusLabel("awaiting_approval")).toBe("사람 검토 대기");
  });
});
