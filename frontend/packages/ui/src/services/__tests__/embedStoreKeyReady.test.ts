// Tests transient encrypted embed recovery after chat-key readiness.
// Missing keys are expected during phased reload and must not become permanent
// decryption failures. Matching readiness retries once, while deep ref repair
// remains deduplicated across concurrent components.
// The singleton listener and logout cleanup are covered as separate boundaries.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  EmbedStore,
  embedRefIndexVersion,
  embedStore,
  retryPendingEmbedsForReadyChat,
} from '../embedStore';
import type { EmbedStoreEntry } from '../../message_parsing/types';

type RecoverableEmbedStore = {
  markEmbedKeyPendingForChat(chatId: string, embedId: string): void;
  retryPendingEmbedKeysForChat(chatId: string): boolean;
  getFromSeparateFields(entry: EmbedStoreEntry, contentRef: string): Promise<Record<string, unknown>>;
  collectAllRefRepairCandidatesFromCache(): string[];
  collectAllRefRepairCandidatesFromIndexedDb(): Promise<string[]>;
  extractRefsFromResolvedEmbed(embed: unknown): Promise<{ embedRefs: string[]; appId: string }>;
};

describe('EmbedStore transient chat-key recovery', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('classifies a missing matching chat key as pending instead of failed', async () => {
    const baseStore = new EmbedStore();
    const store = baseStore as unknown as RecoverableEmbedStore;
    const embedId = 'pending-event-embed';
    store.markEmbedKeyPendingForChat('chat-one', embedId);
    vi.spyOn(baseStore, 'getEmbedKey').mockResolvedValue(null);

    const result = await store.getFromSeparateFields({
      contentRef: `embed:${embedId}`,
      type: 'app-skill-use',
      embed_id: embedId,
      encrypted_content: '<encrypted>',
      status: 'finished',
      createdAt: 1,
      updatedAt: 1,
    }, `embed:${embedId}`);

    expect(result._decryptionPending).toBe(true);
    expect(result._decryptionFailed).toBeUndefined();
    expect(result.status).toBe('finished');
    expect(store.retryPendingEmbedKeysForChat('chat-one')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('retries only once for the matching key-ready chat', () => {
    const store = new EmbedStore() as unknown as RecoverableEmbedStore;
    const versions: number[] = [];
    const unsubscribe = embedRefIndexVersion.subscribe((version) => versions.push(version));
    store.markEmbedKeyPendingForChat('chat-one', 'pending-event-embed');
    const initialVersion = versions[versions.length - 1];

    expect(store.retryPendingEmbedKeysForChat('chat-two')).toBe(false);
    expect(versions[versions.length - 1]).toBe(initialVersion);
    expect(store.retryPendingEmbedKeysForChat('chat-one')).toBe(true);
    expect(versions[versions.length - 1]).toBe((initialVersion ?? 0) + 1);
    expect(store.retryPendingEmbedKeysForChat('chat-one')).toBe(false);
    expect(versions[versions.length - 1]).toBe((initialVersion ?? 0) + 1);
    unsubscribe();
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('routes the singleton key-ready handler to the pending retry boundary', () => {
    const retryPending = vi
      .spyOn(embedStore, 'retryPendingEmbedKeysForChat')
      .mockReturnValue(true);

    expect(retryPendingEmbedsForReadyChat('chat-one')).toBe(true);
    expect(retryPending).toHaveBeenCalledOnce();
    expect(retryPending).toHaveBeenCalledWith('chat-one');
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('clears pending retries with the key cache on logout', () => {
    const store = new EmbedStore() as unknown as RecoverableEmbedStore;
    store.markEmbedKeyPendingForChat('chat-one', 'pending-event-embed');

    (store as unknown as EmbedStore).clearEmbedKeyCache();

    expect(store.retryPendingEmbedKeysForChat('chat-one')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it('shares one candidate scan across concurrent repairs for the same ref', async () => {
    const baseStore = new EmbedStore();
    const store = baseStore as unknown as RecoverableEmbedStore;
    let releaseCandidate: (() => void) | undefined;
    const candidateReady = new Promise<void>((resolve) => {
      releaseCandidate = resolve;
    });
    vi.spyOn(store, 'collectAllRefRepairCandidatesFromCache').mockReturnValue(['event-embed-id']);
    vi.spyOn(store, 'collectAllRefRepairCandidatesFromIndexedDb').mockResolvedValue([]);
    const getEmbed = vi.spyOn(baseStore, 'get').mockImplementation(async () => {
      await candidateReady;
      return {
        embed_id: 'event-embed-id',
        type: 'events-event',
        content: 'event-content',
      };
    });
    vi.spyOn(store, 'extractRefsFromResolvedEmbed').mockResolvedValue({
      embedRefs: ['berlin-event-ref'],
      appId: 'events',
    });

    const first = baseStore.resolveByRefDeep('berlin-event-ref');
    const second = baseStore.resolveByRefDeep('berlin-event-ref');
    await Promise.resolve();
    releaseCandidate?.();

    await expect(Promise.all([first, second])).resolves.toEqual([
      'event-embed-id',
      'event-embed-id',
    ]);
    expect(getEmbed).toHaveBeenCalledTimes(1);
  });
});
