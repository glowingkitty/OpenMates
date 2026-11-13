/**
 * Pure decisions of the app settings/memories permission RESPONSE path
 * (chatSyncServiceHandlersAppSettings.ts: confirm handler and the persisted
 * response system message), extracted unchanged. Flag-off builds keep this
 * TypeScript behaviour; flag-on builds ask the shared Rust `settings` unit
 * (web_settings_response.rs). TS-generated vectors in
 * packages/openmates-rust/src/web_settings_response_ts_vectors.json pin both.
 *
 * No imports: the module must stay dependency-free so the vector generator can
 * load it directly. The memory app id mirrors MEMORY_RESPONSE_APP_ID.
 */

const MEMORY_APP_ID = 'memory';

export type ResponseKeyRoute = 'memory' | 'personal_memories' | 'entries';
export interface ResponseKeyPlan { key: string; appId: string; itemType: string; route: ResponseKeyRoute }
export interface ResponseCategory { appId: string; itemType: string; entryCount: number }
export type ConfirmOutcome = { kind: 'send' } | { kind: 'empty'; sendEmpty: boolean; saveRejected: boolean };

/** How each selected dialog key is resolved; keys without "-" are skipped. */
export function planSelectedKeys(selectedKeys: string[]): ResponseKeyPlan[] {
  const plan: ResponseKeyPlan[] = [];
  for (const key of selectedKeys) {
    const dashIndex = key.indexOf('-');
    if (dashIndex === -1) continue;
    const appId = key.substring(0, dashIndex);
    const itemType = key.substring(dashIndex + 1);
    const route: ResponseKeyRoute = appId === MEMORY_APP_ID ? 'memory'
      : appId === 'openmates' && itemType === 'memories' ? 'personal_memories' : 'entries';
    plan.push({ key, appId, itemType, route });
  }
  return plan;
}

/** Entry ids released for a category; a null selection means all entries. */
export function selectEntryIds(entryIds: string[], selection: string[] | null): string[] {
  return entryIds.filter((id) => selection === null || selection.includes(id));
}

/** Response categories with the number of released entries per category. */
export function responseCategories(
  categories: Array<{ appId: string; itemType: string }>,
  released: Array<{ app_id: string; item_key: string }>,
): ResponseCategory[] {
  return categories.map((cat) => ({
    appId: cat.appId,
    itemType: cat.itemType,
    entryCount: released.filter((memory) => memory.app_id === cat.appId && memory.item_key === cat.itemType).length,
  }));
}

/** What the confirm handler does once the released entries are collected. */
export function confirmOutcome(releasedCount: number, voice: boolean, hasMessageId: boolean): ConfirmOutcome {
  if (releasedCount > 0) return { kind: 'send' };
  return { kind: 'empty', sendEmpty: voice, saveRejected: voice && hasMessageId };
}

/** Content string of the persisted response system message. */
export function responseContent(userMessageId: string, action: 'included' | 'rejected', categories?: ResponseCategory[]): string {
  return JSON.stringify({
    type: 'app_settings_memories_response',
    user_message_id: userMessageId,
    action,
    categories: action === 'included' ? categories : undefined,
  });
}
