/** Compare a stored reference fingerprint with a freshly opened original file. */
export function referenceRevisionStatus(
  referencedHash: string | undefined,
  currentHash: string | null | undefined,
): 'same' | 'changed' | 'unknown' {
  if (!referencedHash || !/^[a-f0-9]{64}$/.test(referencedHash)
      || !currentHash || !/^[a-f0-9]{64}$/.test(currentHash)) return 'unknown';
  return referencedHash === currentHash ? 'same' : 'changed';
}

export async function hostedReferenceContentHash(content: Record<string, unknown>): Promise<string | null> {
  const value = content.code ?? content.content;
  if (typeof value !== 'string' || value.includes('\0') || new TextEncoder().encode(value).length > 200 * 1024) return null;
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Recheck live source status for every open, including after an earlier read. */
export async function connectedReferenceSource<Source extends { source_id: string; status: string }>(
  sourceId: string,
  listSources: () => Promise<Source[]>,
): Promise<Source | null> {
  return (await listSources()).find((source) => source.source_id === sourceId && source.status === 'connected') ?? null;
}
