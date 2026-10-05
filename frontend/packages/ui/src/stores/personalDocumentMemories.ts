/** Transient owner-scoped discovery for legacy encrypted account Memories. */
import {get, writable} from 'svelte/store';
import {authStore} from './authState';
import {userProfile} from './userProfile';
export interface PersonalDocumentMemoryEntry {
  id: string; app_id: string; item_key: string; settings_group: string;
  item_value: Record<string, unknown>; created_at: number; updated_at: number; item_version: number;
}
interface Snapshot {owner: string; revision: string | null; entries: PersonalDocumentMemoryEntry[]}
export const personalDocumentMemories = writable<Snapshot | null>(null);

export function currentPersonalDocumentMemories(): PersonalDocumentMemoryEntry[] {
  const profile = get(userProfile), snapshot = get(personalDocumentMemories);
  return get(authStore).isAuthenticated && snapshot?.owner === profile.user_id
    && snapshot.revision === (profile.encrypted_settings ?? null) ? snapshot.entries : [];
}
export function publishPersonalDocumentMemories(owner: string, revision: string | null, entries: PersonalDocumentMemoryEntry[]) {
  const profile = get(userProfile);
  if (get(authStore).isAuthenticated && profile.user_id === owner && (profile.encrypted_settings ?? null) === revision) {
    personalDocumentMemories.set({owner, revision, entries});
  }
}
let pending: {owner: string; revision: string | null; promise: Promise<void>} | null = null;
export async function loadPersonalDocumentMemories(): Promise<void> {
  const profile = get(userProfile), owner = profile.user_id, revision = profile.encrypted_settings ?? null;
  if (!owner || !get(authStore).isAuthenticated) return;
  const snapshot = get(personalDocumentMemories);
  if (snapshot?.owner === owner && snapshot.revision === revision) return;
  if (pending?.owner === owner && pending.revision === revision) return pending.promise;
  const promise = import('../services/ruleDocumentService').then(module => module.personalDocumentMemoryEntries()).then(() => {});
  pending = {owner, revision, promise};
  try {await promise;} finally {if (pending?.promise === promise) pending = null;}
}
function invalidate() {
  const profile = get(userProfile), snapshot = get(personalDocumentMemories);
  if (snapshot && (!get(authStore).isAuthenticated || snapshot.owner !== profile.user_id || snapshot.revision !== (profile.encrypted_settings ?? null))) {
    personalDocumentMemories.set(null);
  }
}
userProfile.subscribe(invalidate);
authStore.subscribe(invalidate);
