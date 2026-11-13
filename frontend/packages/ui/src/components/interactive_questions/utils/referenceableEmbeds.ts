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

/**
 * Expand app-skill references to their result children.
 * Unknown embeds are kept so a result that has not synced yet still renders
 * its normal loading state; order is preserved and duplicates are removed.
 */
export async function resolveReferenceableEmbedIds(
  embedIds: string[],
  lookup: (embedId: string) => Promise<ReferencedEmbed | null>,
): Promise<string[]> {
  const result: string[] = [];
  const push = (id: string) => { if (id && !result.includes(id)) result.push(id); };
  for (const embedId of embedIds) {
    const embed = await lookup(embedId);
    if (!embed || !isAppSkillExecutionType(embed.type)) { push(embedId); continue; }
    for (const childId of embed.childEmbedIds) push(childId);
  }
  return result;
}
