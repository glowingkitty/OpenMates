/** Canonical, encrypted-in-message references consumed by the shared parser. */
export interface VoiceArtifactReference extends Record<string, unknown> {
  embed_id: string;
  type: string;
}
const idPattern = /^[A-Za-z0-9_-]{1,240}$/;
const metadataKeys = ['app_id', 'skill_id', 'focus_id', 'focus_mode_name', 'query', 'provider',
  'title', 'filename', 'language', 'file_path', 'status'] as const;

export function parseVoiceArtifactReference(value: unknown, expectedId?: string): VoiceArtifactReference | undefined {
  try {
    const raw = typeof value === 'string' ? JSON.parse(value) : value;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return;
    const reference = raw as Record<string, unknown>;
    if (typeof reference.embed_id !== 'string' || !idPattern.test(reference.embed_id) ||
      expectedId !== undefined && reference.embed_id !== expectedId ||
      typeof reference.type !== 'string' || !/^[A-Za-z0-9_-]{1,96}$/.test(reference.type) ||
      reference.type === 'unknown' || JSON.stringify(reference).length > 16_000) return;
    return { ...reference } as VoiceArtifactReference;
  } catch { return; }
}

export function voiceArtifactReferenceFromPayload(payload: Record<string, unknown>): VoiceArtifactReference | undefined {
  if (typeof payload.embed_id !== 'string' || payload.parent_embed_id) return;
  if (typeof payload.embed_reference === 'string') return parseVoiceArtifactReference(payload.embed_reference, payload.embed_id);
  const reference: Record<string, unknown> = { embed_id: payload.embed_id, type: payload.type };
  for (const key of metadataKeys) if (typeof payload[key] === 'string') reference[key] = payload[key];
  return parseVoiceArtifactReference(reference);
}

export function callArtifactReferencesInText(text: string): VoiceArtifactReference[] {
  return [...text.matchAll(/```json\s*\n([\s\S]*?)\n```/g)]
    .map((match) => parseVoiceArtifactReference(match[1])).filter((reference): reference is VoiceArtifactReference => !!reference);
}

export function formatVoiceArtifactReference(reference: VoiceArtifactReference): string {
  return `\`\`\`json\n${JSON.stringify(reference)}\n\`\`\``;
}

/** Cold action receipts carry IDs; metadata comes from the existing embed journal. */
export async function loadVoiceArtifactReference(id: string): Promise<VoiceArtifactReference | null> {
  const { embedStore } = await import('./embedStore');
  const embed = await embedStore.get(`embed:${id}`);
  if (!embed || typeof embed !== 'object' || embed._decryptionFailed || embed._decryptionPending) {
    throw new Error('Call artifact is awaiting encrypted embed delivery');
  }
  if (embed.embed_id !== undefined && embed.embed_id !== id) throw new Error('Call artifact journal identity mismatch');
  if (embed.parent_embed_id) return null; // Parent cards already render their children.
  let decoded: Record<string, unknown> = {};
  if (typeof embed.content === 'string') {
    const { decode } = await import('@toon-format/toon');
    try { decoded = decode(embed.content, { strict: false }) as Record<string, unknown>; }
    catch { try { decoded = JSON.parse(embed.content); } catch { /* Metadata remains unavailable. */ } }
  }
  const reference: Record<string, unknown> = { embed_id: id, type: embed.type ?? embed.embed_type };
  for (const key of metadataKeys) {
    const value = decoded?.[key] ?? embed[key];
    if (typeof value === 'string') reference[key] = value;
  }
  const canonical = parseVoiceArtifactReference(reference, id);
  if (!canonical || ['app_skill_use', 'app-skill-use'].includes(canonical.type) &&
      (!canonical.app_id || !canonical.skill_id)) throw new Error('Call artifact metadata is not decrypted yet');
  return canonical;
}
