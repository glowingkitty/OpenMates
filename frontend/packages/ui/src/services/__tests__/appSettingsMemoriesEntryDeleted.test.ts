/**
 * The server's delete notice removes the entry from the local store, so a
 * device never asks the server to delete an entry another device already deleted.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const deleteEntry = vi.fn();
vi.mock('../db', () => ({ chatDB: { deleteAppSettingsMemoriesEntry: (id: string) => deleteEntry(id) } }));

import { handleAppSettingsMemoriesEntryDeleted } from '../appSettingsMemoriesEntryDeleted';

describe('app_settings_memories_entry_deleted handler', () => {
  beforeEach(() => { deleteEntry.mockReset(); deleteEntry.mockResolvedValue(true); });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('removes the entry locally and asks open screens to refresh', async () => {
    const refreshed = vi.fn();
    window.addEventListener('appSettingsMemoriesEntrySynced', refreshed);
    expect(await handleAppSettingsMemoriesEntryDeleted({ entry_id: 'entry-one', success: true })).toBe(true);
    expect(deleteEntry).toHaveBeenCalledWith('entry-one');
    expect(refreshed).toHaveBeenCalledTimes(1);
    window.removeEventListener('appSettingsMemoriesEntrySynced', refreshed);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('ignores a notice without an entry id or with success false', async () => {
    expect(await handleAppSettingsMemoriesEntryDeleted({})).toBe(false);
    expect(await handleAppSettingsMemoriesEntryDeleted({ entry_id: 'entry-one', success: false })).toBe(false);
    expect(deleteEntry).not.toHaveBeenCalled();
  });
});
