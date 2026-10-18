export class TransientError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "TransientError";
  }
}

export type RetryOptions = {
  maxAttempts?: number;
  baseDelayMs?: number;
  sleep?: (ms: number) => Promise<void>;
};

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function withRetry<T>(
  fn: (attempt: number) => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const maxAttempts = options.maxAttempts ?? 3;
  const baseDelayMs = options.baseDelayMs ?? 200;
  const sleep = options.sleep ?? defaultSleep;

  let lastError: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;
      const isLastAttempt = attempt === maxAttempts;
      const isRetryable = error instanceof TransientError;
      if (!isRetryable || isLastAttempt) {
        throw error;
      }
      const jitter = Math.random() * baseDelayMs;
      await sleep(baseDelayMs * 2 ** (attempt - 1) + jitter);
    }
  }
  throw lastError;
}
