/** Selected encrypted embed graph only; provenance never grants source access. */
import { AUTHORED_RESULT_KIND_MAP, normalizeEmbedType } from '../../../../../../packages/ui/src/data/embedRegistry.generated';

export interface SharedGraphNode {
  embed_id?: string;
  embed_ids?: unknown;
  parent_embed_id?: string | null;
  hashed_user_id?: string;
  hashed_chat_id?: string;
  hashed_team_id?: string | null;
  status?: string;
}
const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
const text = (value: unknown): string | undefined => typeof value === 'string' && value.trim() ? value : undefined;

/** Authentic decrypted type, then decrypted body's type, then actual legacy metadata. */
export function sharedEmbedType(decryptedType: unknown, decoded: Record<string, unknown> | null, legacyType?: unknown): string | null {
  const type = text(decryptedType) ?? text(decoded?.type) ?? text(legacyType);
  return type ? normalizeEmbedType(type) : null;
}
export function isAuthoredSharedCarrier(decoded: Record<string, unknown> | null): boolean {
  return decoded?.type === 'authored_results';
}
function ids(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some(id => typeof id !== 'string' || !id || id.length > 128)) return null;
  return value as string[];
}
function matchesScope(parent: SharedGraphNode, child: SharedGraphNode, strict: boolean): boolean {
  return !!parent.embed_id && !!parent.hashed_user_id && !!parent.hashed_chat_id
    && child.hashed_user_id === parent.hashed_user_id && child.hashed_chat_id === parent.hashed_chat_id
    && (child.hashed_team_id ?? null) === (parent.hashed_team_id ?? null)
    && (child.parent_embed_id === parent.embed_id || (!strict && !child.parent_embed_id))
    && (!strict || child.status === 'finished');
}

/** Validate both the private typed item manifest and public sidecars, preserving order. */
export function selectedSharedChildren<T extends SharedGraphNode>(parent: SharedGraphNode, decoded: Record<string, unknown> | null, candidates: T[]): T[] {
  const strict = isAuthoredSharedCarrier(decoded);
  let selected = ids(parent.embed_ids) ?? [];
  if (strict) {
    const declared = ids(decoded?.embed_ids);
    const items = decoded?.items;
    if (!declared || declared.length > 50 || new Set(declared).size !== declared.length
      || !Array.isArray(items) || items.length !== declared.length
      || selected.length !== declared.length || selected.some((id, index) => id !== declared[index])) return [];
    for (let index = 0; index < items.length; index++) {
      const item = record(items[index]);
      if (!item || item.embed_id !== declared[index] || typeof item.kind !== 'string' || !AUTHORED_RESULT_KIND_MAP[item.kind]) return [];
    }
    selected = declared;
  }
  const byId = new Map<string, T>();
  const ambiguous = new Set<string>();
  for (const child of candidates) {
    if (!child.embed_id) continue;
    if (byId.has(child.embed_id)) ambiguous.add(child.embed_id);
    else byId.set(child.embed_id, child);
  }
  return [...new Set(selected)].slice(0, strict ? 50 : 1000).flatMap(id => {
    const child = byId.get(id);
    return child && id !== parent.embed_id && !ambiguous.has(id) && matchesScope(parent, child, strict) ? [child] : [];
  });
}

/** Check the real decrypted child against the carrier's corresponding typed item. */
export function authoredSharedChildMatches(parent: Record<string, unknown> | null, childId: string, child: Record<string, unknown> | null, decryptedType?: unknown): boolean {
  if (!isAuthoredSharedCarrier(parent)) return true;
  if (!child || !Array.isArray(parent?.items)) return false;
  const item = parent.items.map(record).find(row => row?.embed_id === childId);
  const authoring = record(child.authoring);
  if (!item || typeof item.kind !== 'string' || authoring?.kind !== item.kind) return false;
  const definition = AUTHORED_RESULT_KIND_MAP[item.kind];
  return !!definition && child.type === definition.backendType && child.app_id === definition.appId
    && (definition.skillId === null || child.skill_id === definition.skillId)
    && sharedEmbedType(decryptedType, child) === definition.frontendType;
}

/** Hashes come from the existing SHA-256 helper; this function adds no key authority. */
export function selectedSharedKeyWrappers<T extends { key_type: string; parent_embed_id?: string | null; hashed_embed_id: string }>(keys: T[], parentHash: string, childHashes: ReadonlySet<string>): T[] {
  return keys.filter(key => key.key_type === 'embed' && key.parent_embed_id === parentHash && childHashes.has(key.hashed_embed_id));
}
