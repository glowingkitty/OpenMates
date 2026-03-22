export type ShareChatEmbedLike = {
  embed_id?: string;
  embed_ids?: unknown;
};

export function deriveParentByChildEmbeds(embeds: ShareChatEmbedLike[]): Map<string, string> {
  const derivedParentByChild = new Map<string, string>();

  for (const embed of embeds) {
    const parentId = embed?.embed_id;
    const childIds = embed?.embed_ids;
    if (!parentId || !Array.isArray(childIds)) continue;

    for (const childId of childIds) {
      if (typeof childId !== 'string' || childId.length === 0) continue;
      if (!derivedParentByChild.has(childId)) {
        derivedParentByChild.set(childId, parentId);
      }
    }
  }

  return derivedParentByChild;
}

