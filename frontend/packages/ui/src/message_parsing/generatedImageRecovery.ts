/**
 * Restores previews in saved image-generation answers with erased inline refs.
 * Uses only children from an already authorized, terminal generation parent.
 * The original message stays unchanged and existing previews are deduplicated.
 * The caller owns account, Team and view cancellation for asynchronous reads.
 */
import { assistantActivityItems, type AssistantDocument } from './assistantActivityRuns';
import { generatedMediaChildIds } from '../components/embeds/generatedMediaGroup';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function isLostImagePlaceholder(node: Record<string, unknown>): boolean {
  if (node.type !== 'paragraph' || !Array.isArray(node.content) || !node.content.length) return false;
  return node.content.every((part: Record<string, unknown>) => part.type === 'text' && typeof part.text === 'string' && /^[!\s]+$/.test(part.text));
}

/** Only the historical corruption signature triggers additional parent reads. */
export function lostImageParents(value: unknown): string[] {
  const doc = value as AssistantDocument | undefined;
  if (doc?.type !== 'doc' || !Array.isArray(doc.content) || !doc.content.some(isLostImagePlaceholder)) return [];
  return [...new Set(assistantActivityItems(doc).flatMap(item => {
    if (item.app_id !== 'images' || !['generate', 'generate_draft'].includes(String(item.skill_id))) return [];
    const id = typeof item.id === 'string' ? item.id : String(item.contentRef || '').replace(/^embed:/, '');
    return UUID.test(id) ? [id] : [];
  }))];
}

/** Recover display from the retained authorized graph without rewriting history. */
export async function recoverGeneratedImageDocument(
  source: AssistantDocument,
  resolveParent: (id: string) => Promise<Record<string, unknown> | null>,
): Promise<AssistantDocument | null> {
  const parents = lostImageParents(source);
  if (!parents.length) return null;
  const seen = new Set<string>();
  function visit(node: Record<string, unknown>): void {
    const attrs = node.attrs as Record<string, unknown> | undefined;
    if (attrs) for (const key of ['embedId', 'embedRef', 'id', 'contentRef']) {
      if (typeof attrs[key] === 'string') seen.add(attrs[key].replace(/^embed:/, ''));
    }
    if (Array.isArray(node.content)) node.content.forEach(visit);
  }
  visit(source);
  const additions: Array<Record<string, unknown>> = [];
  for (const parent of await Promise.all(parents.map(id => resolveParent(id)))) {
    if (!parent || parent.app_id !== 'images' || !['generate', 'generate_draft'].includes(String(parent.skill_id)) || parent.status !== 'finished') continue;
    for (const id of generatedMediaChildIds(parent)) {
      const ref = `generated-images-${id.replace(/-/g, '').slice(0, 12)}`;
      if (!UUID.test(id) || seen.has(id) || seen.has(ref)) continue;
      seen.add(id); seen.add(ref);
      additions.push({ type: 'embedPreviewLarge', attrs: { embedId: id, embedRef: ref, appId: 'images' } });
    }
  }
  if (!additions.length) return null;
  const runRef = (additions[0].attrs as Record<string, unknown>).embedRef;
  additions.forEach((node, index) => Object.assign(node.attrs as Record<string, unknown>, {
    carouselIndex: index, carouselTotal: additions.length, runRef,
  }));
  return { ...source, content: [...source.content.filter(node => !isLostImagePlaceholder(node)), ...additions] };
}
