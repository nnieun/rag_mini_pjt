import { describe, expect, it, vi } from "vitest";
import { TransientError, withRetry } from "../src/retry.js";

describe("withRetry", () => {
  it("returns the result on first success without sleeping", async () => {
    const sleep = vi.fn().mockResolvedValue(undefined);
    const fn = vi.fn().mockResolvedValue("ok");

    const result = await withRetry(fn, { sleep });

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("retries on TransientError and eventually succeeds", async () => {
    const sleep = vi.fn().mockResolvedValue(undefined);
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new TransientError("429", 429))
      .mockResolvedValueOnce("ok");

    const result = await withRetry(fn, { sleep, maxAttempts: 3 });

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledTimes(1);
  });

  it("throws immediately on a non-transient error", async () => {
    const sleep = vi.fn().mockResolvedValue(undefined);
    const fn = vi.fn().mockRejectedValue(new Error("bad input"));

    await expect(withRetry(fn, { sleep })).rejects.toThrow("bad input");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("throws the last error after exhausting all attempts", async () => {
    const sleep = vi.fn().mockResolvedValue(undefined);
    const fn = vi.fn().mockRejectedValue(new TransientError("still failing", 503));

    await expect(withRetry(fn, { sleep, maxAttempts: 3 })).rejects.toThrow("still failing");
    expect(fn).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });
});
