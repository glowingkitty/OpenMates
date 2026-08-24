// frontend/packages/ui/src/services/__tests__/embedStoreRefRepair.test.ts
// Focused regression coverage for bounded cold embed-ref repair ordering.
// Recent chat embeds must remain discoverable when IndexedDB also contains
// more historical embeds than the zero-knowledge repair scan can inspect.
// Spec: docs/specs/billing-processing-reliability/spec.yml

import { describe, expect, it } from 'vitest';
import type { EmbedStoreEntry } from '../../message_parsing/types';
import { EmbedStore } from '../embedStore';

describe('EmbedStore cold ref repair', () => {
  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('prioritizes recent embeds in bounded cold ref repair candidates', () => {
    const store = new EmbedStore();
    const staleEntries = Array.from({ length: 200 }, (_, index) => ({
      contentRef: `embed:stale-${index}`,
      type: 'app-skill-use',
      status: 'finished',
      embed_id: `stale-${index}`,
      createdAt: index,
      updatedAt: index,
    })) as EmbedStoreEntry[];
    const recentEntry = {
      contentRef: 'embed:recent-source',
      type: 'app-skill-use',
      status: 'finished',
      embed_id: 'recent-source',
      createdAt: 1_000,
      updatedAt: 1_000,
    } as EmbedStoreEntry;

    const candidates = (store as unknown as {
      collectAllRefRepairCandidatesFromEntries(entries: EmbedStoreEntry[]): string[];
    }).collectAllRefRepairCandidatesFromEntries([...staleEntries, recentEntry]);

    expect(candidates).toHaveLength(200);
    expect(candidates[0]).toBe('recent-source');
    expect(candidates).not.toContain('stale-0');
  });
});
