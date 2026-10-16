import type { AssistantDocument } from './assistantActivityRuns';
import { isTerminalStatus } from '../services/embedStateMachine';

/** Real skill refs, including children hidden behind a synthetic grouped embed. */
export function assistantSkillRefs(document: AssistantDocument | undefined): string[] {
  const refs = new Set<string>();
  for (const node of document?.content ?? []) {
    if (node.type !== 'paragraph' || !Array.isArray(node.content)) continue;
    for (const child of node.content as Array<Record<string, unknown>>) {
      if (child.type !== 'embed' || !child.attrs || typeof child.attrs !== 'object') continue;
      const attrs = child.attrs as Record<string, unknown>;
      const items = attrs.type === 'app-skill-use-group' && Array.isArray(attrs.groupedItems)
        ? attrs.groupedItems as Array<Record<string, unknown>>
        : attrs.type === 'app-skill-use' ? [attrs] : [];
      for (const item of items) {
        const ref = typeof item.contentRef === 'string' && item.contentRef.startsWith('embed:')
          ? item.contentRef
          : typeof item.id === 'string' ? `embed:${item.id}` : null;
        if (ref) refs.add(ref);
      }
    }
  }
  return [...refs];
}

/** Missing or unknown stored status means this active skill is still pending. */
export async function areAssistantSkillsTerminal(
  refs: readonly string[],
  getRawEntry: (ref: string) => Promise<{ status?: string } | null>,
): Promise<boolean> {
  if (!refs.length) return false;
  const entries = await Promise.all(refs.map((ref) => getRawEntry(ref)));
  return entries.every((entry) => typeof entry?.status === 'string' && isTerminalStatus(entry.status));
}
