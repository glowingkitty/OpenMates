/** Resolve a results-view reference locally before treating it as a server ID. */
interface ResultsViewRefStore {
  resolveByRefDeep(ref: string): Promise<string | null>;
  get(contentRef: string): Promise<unknown>;
}

const EMBED_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function resolveResultsViewRefToId(
  ref: string,
  store: ResultsViewRefStore,
): Promise<string | null> {
  const indexed = await store.resolveByRefDeep(ref);
  if (indexed) return indexed;
  // Canonical IDs can recover remotely; short refs must be registered aliases.
  // This keeps copied prompt examples out of the server's embed-ID path while
  // allowing later index/availability updates to retry the same reference.
  if (EMBED_UUID.test(ref)) return ref;
  return await store.get(`embed:${ref}`) ? ref : null;
}
