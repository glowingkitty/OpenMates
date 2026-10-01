interface ChildRetryOptions<T> {
  ids: string[];
  concurrency: number;
  retryLimit: number;
  load: (id: string) => Promise<T | null>;
  isCurrent: () => boolean;
  wait: () => Promise<void>;
  onProgress: (children: T[]) => void;
}

/** Retain successful children while retrying only missing references for a bounded time. */
export async function loadChildrenWithRetry<T>({
  ids, concurrency, retryLimit, load, isCurrent, wait, onProgress,
}: ChildRetryOptions<T>): Promise<T[] | null> {
  const byId = new Map<string, T>();
  let children: T[] = [];
  for (let attempt = 0; attempt <= retryLimit; attempt++) {
    if (!isCurrent()) return null;
    const pending = ids.filter((id) => !byId.has(id));
    if (pending.length === 0) break;
    for (let start = 0; start < pending.length; start += concurrency) {
      if (!isCurrent()) return null;
      const chunk = pending.slice(start, start + concurrency);
      const loaded = await Promise.all(chunk.map(load));
      if (!isCurrent()) return null;
      loaded.forEach((child, index) => { if (child !== null) byId.set(chunk[index], child); });
      children = ids.filter((id) => byId.has(id)).map((id) => byId.get(id)!);
      onProgress(children);
    }
    if (byId.size === ids.length || attempt === retryLimit) break;
    await wait();
  }
  return children;
}
