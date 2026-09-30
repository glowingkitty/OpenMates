// Shared lifecycle without store imports: key storage and auth can fence caches
// synchronously before an asynchronous logout or key replacement finishes.
// Register only module-owned caches, never individual mounted components.
// The epoch also invalidates work that has already left an in-flight registry.
// Decrypted projections are recoverable and may be discarded at any time.
let epoch = 0;
const clearers = new Set<() => void>();

export function getWorkspaceCacheEpoch(): number { return epoch; }

export function registerWorkspaceCacheClear(clear: () => void): () => void {
  clearers.add(clear);
  return () => clearers.delete(clear);
}

export function invalidateWorkspaceCaches(): void {
  epoch += 1;
  for (const clear of clearers) clear();
}
