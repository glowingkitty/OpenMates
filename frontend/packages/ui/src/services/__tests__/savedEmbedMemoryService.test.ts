/**
 * Saved-preview actions use the existing memory state and forgetting path.
 * Isolates storage and outbound synchronization while retaining the real store.
 * Exact identities protect neighboring entries and generic content memories.
 * A false storage result must leave cache state intact and suppress success.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const effects = vi.hoisted(() => ({ deleteLocal: vi.fn(), sendDelete: vi.fn(), success: vi.fn() }));
vi.mock('../db', () => ({ chatDB: { deleteAppSettingsMemoriesEntry: effects.deleteLocal } }));
vi.mock('../chatSyncService', () => ({ chatSyncService: { sendDeleteAppSettingsMemoriesEntry: effects.sendDelete } }));
vi.mock('../cryptoService', () => ({ decryptWithMasterKey: vi.fn(), encryptWithMasterKey: vi.fn(), getKeyFromStorage: vi.fn() }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { success: effects.success } }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({}) }));
vi.mock('../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: false }) }));
vi.mock('../../stores/teamStore', async () => ({ activeTeamId: (await import('svelte/store')).writable(null) }));
vi.mock('../../config/api', () => ({ getApiEndpoint: vi.fn(), getApiUrl: vi.fn() }));

import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';
import { findSavedEmbedMemoryEntry, findSavedEmbedMemoryReference, forgetEmbedMemory } from '../savedEmbedMemoryService';

function seed(id: string, embedId: string, appId = 'documents', itemKey = `saved_items.${id}`) {
  const entry = { id, app_id: appId, item_key: itemKey, settings_group: 'saved_items',
    item_value: { embed_id: embedId, title: 'Saved document' }, created_at: 1, updated_at: 1, item_version: 1 };
  const state = get(appSettingsMemoriesStore);
  state.decryptedEntries.set(id, entry);
  const groups = state.entriesByApp.get(appId) ?? {};
  state.entriesByApp.set(appId, { ...groups, saved_items: [...(groups.saved_items ?? []), entry] });
  return entry;
}

beforeEach(() => {
  vi.clearAllMocks();
  const state = get(appSettingsMemoriesStore);
  state.decryptedEntries.clear();
  state.entriesByApp.clear();
  effects.deleteLocal.mockResolvedValue(true);
  effects.sendDelete.mockResolvedValue(true);
});

describe('saved embed memory references', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('matches only an exact embed ID and retains the real app, category and key', () => {
    const entry = seed('unrelated', 'embed-target-other');
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), '')).toBeUndefined();
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target')).toBeUndefined();
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target-other')).toEqual({
      appId: 'documents', itemType: 'saved_items', itemKey: entry.item_key, title: 'Saved document', itemValue: entry.item_value, entryId: entry.id,
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it.each([true, false])('forgets only result B when unrelated A has the same key and comes first (entry reference: %s)', async (withEntryId) => {
    seed('entry-A', 'embed-A', 'documents', 'saved_items.shared-title');
    seed('entry-B', 'embed-B', 'documents', 'saved_items.shared-title');
    const reference = findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-B')!;
    expect(reference.entryId).toBe('entry-B');
    // Fullscreen save configurations predate entryId and must remain safe too.
    if (!withEntryId) delete reference.entryId;
    await forgetEmbedMemory(reference);
    expect(effects.deleteLocal).toHaveBeenCalledExactlyOnceWith('entry-B');
    expect(effects.sendDelete).toHaveBeenCalledExactlyOnceWith('entry-B');
    expect(appSettingsMemoriesStore.getEntry('entry-A')?.item_value.embed_id).toBe('embed-A');
    expect(appSettingsMemoriesStore.getEntry('entry-B')).toBeUndefined();
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-A')).toBeDefined();
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-B')).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('does not fall back from a missing or conflicting exact identity to a colliding key', async () => {
    seed('entry-A', 'embed-A', 'documents', 'saved_items.shared-title');
    const reference = findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-A')!;
    const missingEmbed = { ...reference, itemValue: { embed_id: 'embed-B' } };
    expect(findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), missingEmbed)).toBeUndefined();
    await forgetEmbedMemory(missingEmbed);
    delete missingEmbed.entryId;
    expect(findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), missingEmbed)).toBeUndefined();
    await forgetEmbedMemory(missingEmbed);
    expect(findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), { ...reference, entryId: 'missing-entry' })).toBeUndefined();
    expect(effects.deleteLocal).not.toHaveBeenCalled();
    expect(effects.success).not.toHaveBeenCalled();
    expect(appSettingsMemoriesStore.getEntry('entry-A')).toBeDefined();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('retains key-only lookup for legacy configurations without an embed identity', () => {
    seed('legacy-entry', 'embed-A');
    const reference = findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-A')!;
    const legacy = { ...reference, itemValue: {} };
    delete legacy.entryId;
    expect(findSavedEmbedMemoryEntry(get(appSettingsMemoriesStore), legacy)?.id).toBe('legacy-entry');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('uses existing forgetting, notification and event behavior without touching another saved entry', async () => {
    seed('matching-entry', 'embed-target');
    seed('unrelated-entry', 'embed-target-other');
    const reference = findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target')!;
    const onForgotten = vi.fn();
    window.addEventListener('savedEmbedMemoryForgotten', onForgotten);
    try {
      await forgetEmbedMemory(reference);
      expect(effects.deleteLocal).toHaveBeenCalledExactlyOnceWith('matching-entry');
      expect(effects.sendDelete).toHaveBeenCalledExactlyOnceWith('matching-entry');
      expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target')).toBeUndefined();
      expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target-other')).toBeDefined();
      expect(effects.success).toHaveBeenCalledExactlyOnceWith('Forgot "Saved document".');
      expect(onForgotten).toHaveBeenCalledOnce();
      expect((onForgotten.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ appId: 'documents', embedId: 'embed-target' });
    } finally {
      window.removeEventListener('savedEmbedMemoryForgotten', onForgotten);
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('rejects false local deletion before mutating saved state, synchronizing or reporting success', async () => {
    seed('matching-entry', 'embed-target');
    seed('unrelated-entry', 'embed-target-other');
    effects.deleteLocal.mockResolvedValue(false);
    const reference = findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target')!;
    await expect(forgetEmbedMemory(reference)).rejects.toThrow('Failed to delete saved memory from browser storage.');
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target')).toBeDefined();
    expect(findSavedEmbedMemoryReference(get(appSettingsMemoriesStore), 'embed-target-other')).toBeDefined();
    expect(effects.sendDelete).not.toHaveBeenCalled();
    expect(effects.success).not.toHaveBeenCalled();
  });
});
