import { cacheDecisions } from "./cacheDecisions";

/** `error.name` of an object-shaped error (null otherwise); the policy decides what it means. */
function errorName(error: unknown): string | null {
  return error && typeof error === "object" && "name" in error && typeof error.name === "string"
    ? error.name
    : null;
}

/** One bounded retry after reclaiming only safe, server-confirmed cache data. */
export async function writeWithQuotaRetry<T>(
  write: () => Promise<T>,
  trim: () => Promise<unknown>,
  notifyUnavailable: () => Promise<unknown> | void,
  canRetry = true,
  retryWrite: () => Promise<T> = write,
): Promise<T> {
  try {
    return await write();
  } catch (error) {
    const decisions = await cacheDecisions();
    const first = await decisions.quotaStep({ stage: "write", canRetry, errorName: errorName(error) });
    if (first === "rethrow") throw error;
    let quotaError = error;
    if (first === "trim_retry") {
      try { await trim(); } catch (trimError) {
        console.warn("[ChatDatabase] Safe quota trim failed:", trimError);
      }
      try {
        return await retryWrite();
      } catch (retryError) {
        const second = await decisions.quotaStep({ stage: "retry", canRetry, errorName: errorName(retryError) });
        if (second === "rethrow") throw retryError;
        quotaError = retryError;
      }
    }
    try { await notifyUnavailable(); } catch (notifyError) {
      console.warn("[ChatDatabase] Could not show offline save failure:", notifyError);
    }
    throw quotaError;
  }
}
