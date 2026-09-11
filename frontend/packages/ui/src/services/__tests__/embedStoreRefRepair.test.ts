// frontend/packages/ui/src/services/__tests__/embedStoreRefRepair.test.ts
// Focused regression coverage for bounded cold embed-ref repair ordering.
// Recent chat embeds must remain discoverable when IndexedDB also contains
// more historical embeds than the zero-knowledge repair scan can inspect.
// Spec: docs/specs/billing-processing-reliability/spec.yml

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { EmbedStoreEntry } from '../../message_parsing/types';
import { EmbedStore } from '../embedStore';
import { activeChatStore } from '../../stores/activeChatStore';

describe('EmbedStore cold ref repair', () => {
  afterEach(() => {
    activeChatStore.setWithoutHashUpdate(null);
    vi.restoreAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it('repairs an open historical chat before scanning 200 newer unrelated embeds', async () => {
    const store = new EmbedStore();
    store.clearEmbedRefIndex();
    activeChatStore.setWithoutHashUpdate('historical-chat');
    const olderChild = {
      contentRef: 'embed:historical-event', embed_id: 'historical-event',
      type: 'app-skill-use', status: 'finished', createdAt: 1, updatedAt: 1,
    } as EmbedStoreEntry;
    const newerEntries = Array.from({ length: 200 }, (_, index) => ({
      ...olderChild, contentRef: `embed:newer-${index}`, embed_id: `newer-${index}`,
      createdAt: index + 2, updatedAt: index + 2,
    }));
    const internal = store as unknown as {
      collectAllRefRepairCandidatesFromCache(): string[];
      collectAllRefRepairCandidatesFromIndexedDb(): Promise<string[]>;
      collectAllRefRepairCandidatesFromEntries(entries: EmbedStoreEntry[]): string[];
    };
    const globalCandidates = internal.collectAllRefRepairCandidatesFromEntries([...newerEntries, olderChild]);
    vi.spyOn(internal, 'collectAllRefRepairCandidatesFromCache').mockReturnValue(globalCandidates);
    const globalScan = vi.spyOn(internal, 'collectAllRefRepairCandidatesFromIndexedDb').mockResolvedValue(globalCandidates);
    const chatScan = vi.spyOn(store, 'getEmbedsByHashedChatId').mockResolvedValue([olderChild]);
    const readEmbed = vi.spyOn(store, 'get').mockImplementation(async (contentRef) =>
      contentRef === olderChild.contentRef ? {
        content: 'type: event_result\napp_id: events\nembed_ref: historical-event-ref',
      } : undefined,
    );

    await expect(store.resolveByRefDeep('historical-event-ref')).resolves.toBe('historical-event');
    expect(chatScan).toHaveBeenCalledOnce();
    expect(readEmbed).toHaveBeenCalledTimes(1);
    expect(globalScan).not.toHaveBeenCalled();
    expect(store.resolveAppIdByRef('historical-event-ref')).toBe('events');
  });

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
