/**
 * Handler for the server's `app_settings_memories_entry_deleted` message.
 *
 * The server sends it to the device that asked for the delete and to every
 * other logged-in device of the account. Without it, other devices kept the
 * deleted entry in IndexedDB and later asked the server to delete it again.
 * The entry is removed locally and the same refresh event as for a synced
 * entry is dispatched, so open settings screens reload.
 */
import { chatDB } from './db';

/** Payload of `app_settings_memories_entry_deleted`. */
export interface AppSettingsMemoriesEntryDeletedPayload {
  entry_id?: string;
  app_id?: string | null;
  item_type?: string | null;
  success?: boolean;
}

/** Remove the deleted entry from the local store; returns true when it was removed. */
export async function handleAppSettingsMemoriesEntryDeleted(
  payload: AppSettingsMemoriesEntryDeletedPayload,
): Promise<boolean> {
  const entryId = payload?.entry_id;
  if (!entryId || typeof entryId !== 'string' || payload.success === false) return false;
  const removed = await chatDB.deleteAppSettingsMemoriesEntry(entryId);
  if (removed && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced', {
      detail: { entries: [], entry_count: 0, deleted_entry_id: entryId, synced_at: Date.now() },
    }));
  }
  return removed;
}
