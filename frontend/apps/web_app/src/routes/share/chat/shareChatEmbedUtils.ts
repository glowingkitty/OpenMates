export type ShareChatEmbedLike = {
  embed_id?: string;
  embed_ids?: unknown;
  encrypted_content?: string;
  encrypted_type?: string;
  embed_type?: string;
  status?: string;
  hashed_chat_id?: string;
  hashed_user_id?: string;
  parent_embed_id?: string;
};

export function normalizeEmbedIds(rawIds: unknown): string[] {
  const ids = typeof rawIds === 'string' ? rawIds.split('|') : rawIds;
  if (!Array.isArray(ids)) return [];

  return ids
    .filter((id): id is string => typeof id === 'string')
    .map((id) => id.trim())
    .filter((id) => id.length > 0);
}

export function deriveParentByChildEmbeds(embeds: ShareChatEmbedLike[]): Map<string, string> {
  const derivedParentByChild = new Map<string, string>();

  for (const embed of embeds) {
    const parentId = embed?.embed_id;
    const childIds = normalizeEmbedIds(embed?.embed_ids);
    if (!parentId || childIds.length === 0) continue;

    for (const childId of childIds) {
      if (!derivedParentByChild.has(childId)) {
        derivedParentByChild.set(childId, parentId);
      }
    }
  }

  return derivedParentByChild;
}
