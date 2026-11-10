// Reads the result children of app skill invocations referenced in an answer
// body (bodyEmbedPolicy.ts), so an old message that references only the parent
// still shows its results. Uses the same authorized embed read as the
// generated-image recovery; the caller owns cancellation.
import { generatedMediaChildIds } from "../components/embeds/generatedMediaGroup";

/** Invocation embed id → its result child embed ids. */
export type BodySkillChildren = Record<string, string[]>;

const RUNNING_STATUSES = new Set(["processing", "pending", "streaming", "queued"]);

export async function resolveBodySkillChildren(
  parentIds: string[],
  chatId: string,
): Promise<BodySkillChildren> {
  const { resolveEmbed, decodeToonContent } = await import("../services/embedResolver");
  const found: BodySkillChildren = {};
  await Promise.all(parentIds.map(async (id) => {
    const parent = await resolveEmbed(id, { chatId });
    // An unreadable parent stays hidden; a later embed update retries it.
    if (!parent) return;
    const decoded = await decodeToonContent(parent.content);
    // A running invocation has no final child list yet; keep it hidden.
    if (RUNNING_STATUSES.has(String(parent.status ?? decoded?.status ?? ""))) return;
    const fromContent = generatedMediaChildIds(decoded);
    found[id] = fromContent.length > 0
      ? fromContent
      : generatedMediaChildIds({ embed_ids: parent.embed_ids });
  }));
  return found;
}
