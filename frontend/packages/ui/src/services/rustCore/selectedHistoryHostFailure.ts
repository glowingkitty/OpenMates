import { RetiredSelectedHistoryHost } from './protocol';
export { RetiredSelectedHistoryHost } from './protocol';

/** These failures permit one independently server-authorized foreground read. */
export function isRecoverableSelectedHistoryFailure(error: unknown): boolean {
  return error instanceof RetiredSelectedHistoryHost ||
    error instanceof Error && error.message === 'unavailable';
}

/** Transfers a readonly online-cache request to local storage on link loss.
 * Genuine authority failures never select the offline reader. */
export async function readSelectedCacheAcrossDisconnect<T>(
  connectivity: { isOnline(): boolean; listenOffline(abort: () => void): () => void },
  online: (signal: AbortSignal) => Promise<T>,
  offline: () => Promise<T>,
): Promise<T> {
  if (!connectivity.isOnline()) return offline();
  const link = new AbortController();
  const stop = connectivity.listenOffline(() => link.abort());
  try {
    if (!connectivity.isOnline()) return offline();
    let result: T;
    try { result = await online(link.signal); }
    catch (error) {
      const wasInterrupted = error instanceof Error && error.message === 'cancelled' ||
        isRecoverableSelectedHistoryFailure(error);
      if (link.signal.aborted && wasInterrupted) return offline();
      throw error;
    }
    return link.signal.aborted ? offline() : result;
  } finally {
    stop();
  }
}
