/** One bounded retry after reclaiming only safe, server-confirmed cache data. */
function isQuotaExceeded(error: unknown): boolean {
  return Boolean(error && typeof error === "object" &&
    "name" in error && error.name === "QuotaExceededError");
}

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
    if (!isQuotaExceeded(error)) throw error;
    let quotaError = error;
    if (canRetry) {
      try { await trim(); } catch (trimError) {
        console.warn("[ChatDatabase] Safe quota trim failed:", trimError);
      }
      try {
        return await retryWrite();
      } catch (retryError) {
        if (!isQuotaExceeded(retryError)) throw retryError;
        quotaError = retryError;
      }
    }
    try { await notifyUnavailable(); } catch (notifyError) {
      console.warn("[ChatDatabase] Could not show offline save failure:", notifyError);
    }
    throw quotaError;
  }
}
