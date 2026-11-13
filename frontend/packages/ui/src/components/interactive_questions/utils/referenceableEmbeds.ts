/**
 * Embeds that a questionnaire option or swipe card may reference.
 *
 * Only result embeds (a generated image, website, sheet, …) can be referenced.
 * An app-skill execution embed (the "Generate", "View" or "Search" call card)
 * is never referenceable. When the model references one that owns result
 * children, the children are shown instead; one without children is dropped.
 */

export interface ReferencedEmbed {
  /** Stored embed type; app-skill executions are `app-skill-use` / `app_skill_use`. */
  type: string;
  /** Result child IDs owned by a composite app-skill embed. */
  childEmbedIds: string[];
}

export function isAppSkillExecutionType(type: string): boolean {
  return type === 'app-skill-use' || type === 'app_skill_use';
}

const EMBED_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True for a stored embed ID; false for an embed_ref slug such as `generated-images-90e9b4752601`. */
export function isEmbedUuid(value: string): boolean {
  return EMBED_UUID_RE.test(value);
}

/**
 * Expand app-skill references to their result children.
 * The model may write an embed_ref slug instead of the embed ID; `resolveRef`
 * maps it to the stored ID first. A slug that cannot be mapped yet is kept
 * unchanged (never looked up by ID) so the preview resolves it once it syncs.
 * Unknown embeds are kept so a result that has not synced yet still renders
 * its normal loading state; order is preserved and duplicates are removed.
 */
export async function resolveReferenceableEmbedIds(
  embedIds: string[],
  lookup: (embedId: string) => Promise<ReferencedEmbed | null>,
  resolveRef: (embedRef: string) => Promise<string | null>,
): Promise<string[]> {
  const result: string[] = [];
  const push = (id: string) => { if (id && !result.includes(id)) result.push(id); };
  for (const requestedId of embedIds) {
    const embedId = isEmbedUuid(requestedId) ? requestedId : await resolveRef(requestedId);
    if (!embedId) { push(requestedId); continue; }
    const embed = await lookup(embedId);
    if (!embed || !isAppSkillExecutionType(embed.type)) { push(embedId); continue; }
    for (const childId of embed.childEmbedIds) push(childId);
  }
  return result;
}
