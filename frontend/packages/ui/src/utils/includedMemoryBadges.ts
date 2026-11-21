// frontend/packages/ui/src/utils/includedMemoryBadges.ts
// Resolves the memories a user included in a chat turn (by id, the synced response
// carries no titles) to what the chat shows: title and app, read from the local memory
// documents like the permission dialog does. Unknown ids (deleted, other device) stay
// visible as an untitled memory so the count never becomes a bare "(1)".
import { parseRuleDocument } from './ruleDocuments';

export interface IncludedMemoryBadge {
  id: string;
  /** Memory title, null when the memory is not stored on this device. */
  title: string | null;
  /** App the memory belongs to, null for a personal memory without an app. */
  appId: string | null;
}

export function resolveIncludedMemories(
  ids: readonly string[],
  documents: readonly { id?: string; document: string }[],
  isKnownApp: (appId: string) => boolean,
): IncludedMemoryBadge[] {
  const byId = new Map(documents.filter((item) => item.id).map((item) => [item.id as string, item.document]));
  return [...new Set(ids)].map((id) => {
    const document = byId.get(id);
    if (!document) return { id, title: null, appId: null };
    const fields = parseRuleDocument(document);
    const appId = fields.app_id && isKnownApp(fields.app_id) ? fields.app_id : null;
    return { id, title: fields.title?.trim() || null, appId };
  });
}

/** Icon classes of the Memories list: the app icon in its colour, else the Memories icon. */
export function includedMemoryIconClass(memory: IncludedMemoryBadge): string {
  return memory.appId ? `app-${memory.appId}` : 'settings_memories';
}
