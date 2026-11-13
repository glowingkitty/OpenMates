/**
 * Legacy typed memory migration: deterministic ids, delete only after the synced
 * write, saved-item mapping without reminders, resumability.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const state = vi.hoisted(() => ({
  settings: {} as Record<string, unknown>, documents: [] as Array<{ id: string; source: 'personal'; document: string }>,
  log: [] as string[], failWrite: false,
}));
vi.mock('../ruleDocumentService', () => ({
  updateAccountSettings: async (mutate: (s: Record<string, unknown>, d: typeof state.documents) => boolean | Promise<boolean>) => {
    const settings = structuredClone(state.settings);
    const documents = structuredClone(state.documents);
    if (!(await mutate(settings, documents))) return false;
    if (state.failWrite) throw new Error('rule_save_failed');
    state.log.push('synced-write');
    state.settings = settings; state.documents = documents;
    return true;
  },
}));
// Browser boundaries of the default deps; `text` keeps its real shape: a store of the translate function.
vi.mock('../../i18n/translations', async () => ({
  text: (await import('svelte/store')).readable((key: string) => (key === 'travel.preferred_airlines.description' ? 'Airlines the user prefers.' : `[T:${key}]`)),
}));
vi.mock('../db', () => ({ chatDB: {
  getAllAppSettingsMemoriesEntries: async () => [{ id: 'entry-1', app_id: 'travel', item_type: 'preferred_airlines', item_key: 'preferred airlines', encrypted_item_json: 'enc' }],
  deleteAppSettingsMemoriesEntry: async () => true,
} }));
vi.mock('../cryptoService', () => ({ decryptWithMasterKey: async () => JSON.stringify({ airline: 'Lufthansa' }) }));
vi.mock('../savedEmbedService', () => ({ setEmbedSaved: async () => undefined }));
vi.mock('../chatSyncService', () => ({ chatSyncService: { sendDeleteAppSettingsMemoriesEntry: async () => true } }));
vi.mock('../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'u', encrypted_settings: 'x' }) }));

import {
  applyLegacyAppIdBackfill, buildMemoryDocumentFromLegacy, classifyLegacyEntry, createDefaultMigrationDeps, describeLegacyType, deriveMemoryDocumentId, migrateLegacyTypedMemories,
  LEGACY_EXPORT_SETTINGS_KEY, type LegacyTypedEntry, type MigrationDeps,
} from '../legacyTypedMemoryMigration';
import { parseRuleDocument } from '../../utils/ruleDocuments';

const travel: LegacyTypedEntry = { id: 'entry-1', appId: 'travel', itemType: 'preferred_airlines', itemKey: 'preferred airlines', value: { airline: 'Lufthansa', _original_item_key: 'x' } };
const event: LegacyTypedEntry = { id: 'entry-2', appId: 'events', itemType: 'saved_events', itemKey: 'Concert', value: { embed_id: 'emb-1', title: 'Concert' } };
const stale: LegacyTypedEntry = { id: 'entry-3', appId: 'events', itemType: 'saved_events', itemKey: 'Gone', value: { embed_id: 'emb-gone' } };
const defaults: LegacyTypedEntry = { id: 'entry-4', appId: 'reminder', itemType: 'saved_item_reminder_defaults', itemKey: 'd', value: { offsets: '10080,1440' } };

function deps(entries: LegacyTypedEntry[], over: Partial<MigrationDeps> = {}): MigrationDeps {
  return {
    listEntries: async () => entries,
    describeType: () => 'Airlines the user prefers when booking travel.',
    saveEmbed: vi.fn(async (id: string) => { state.log.push(`save:${id}`); return id === 'emb-1'; }),
    deleteEntry: vi.fn(async (id: string) => { state.log.push(`delete:${id}`); return true; }),
    ...over,
  };
}

beforeEach(() => {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  state.settings = {}; state.documents = []; state.log = []; state.failWrite = false;
});

describe('legacy typed memory migration', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto,app-memories.typed.removed
  it('derives the same document id on every device and builds an Ask first document', async () => {
    expect(await deriveMemoryDocumentId('entry-1')).toBe(await deriveMemoryDocumentId('entry-1'));
    expect(await deriveMemoryDocumentId('entry-1')).not.toBe(await deriveMemoryDocumentId('entry-2'));
    const fields = parseRuleDocument(buildMemoryDocumentFromLegacy(travel, 'Airlines the user prefers.'));
    expect(fields.title).toBe('Preferred airlines: preferred airlines');
    expect(fields.load_mode).toBe('ask_first');
    expect(fields.when_to_use).toBe('Airlines the user prefers.');
    expect(fields.body).toContain('Lufthansa');
    expect(fields.body).not.toContain('_original');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('creates one document when two devices migrate the same entry', async () => {
    await migrateLegacyTypedMemories(deps([travel]));
    await migrateLegacyTypedMemories(deps([travel]));
    expect(state.documents).toHaveLength(1);
    expect(state.documents[0].id).toBe(await deriveMemoryDocumentId('entry-1'));
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto,app-memories.typed.removed
  it('deletes the legacy entry only after the synced write', async () => {
    const result = await migrateLegacyTypedMemories(deps([travel]));
    expect(result).toMatchObject({ migrated: 1, deleted: 1 });
    expect(state.log.indexOf('synced-write')).toBeLessThan(state.log.indexOf('delete:entry-1'));
    expect((state.settings[LEGACY_EXPORT_SETTINGS_KEY] as Array<{ id: string }>)[0].id).toBe('entry-1');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('keeps the entry when the sync write fails and resumes afterwards', async () => {
    state.failWrite = true;
    const d = deps([travel]);
    await expect(migrateLegacyTypedMemories(d)).rejects.toThrow('rule_save_failed');
    expect(d.deleteEntry).not.toHaveBeenCalled();
    state.failWrite = false;
    expect(await migrateLegacyTypedMemories(d)).toMatchObject({ migrated: 1, deleted: 1 });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('resumes after a crash between the write and the delete without duplicating', async () => {
    await migrateLegacyTypedMemories(deps([travel], { deleteEntry: async () => false }));
    expect(state.documents).toHaveLength(1);
    const retry = deps([travel]);
    expect(await migrateLegacyTypedMemories(retry)).toMatchObject({ migrated: 0, deleted: 1 });
    expect(state.documents).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto,app-memories.saved-items.not-memories
  it('maps saved items to the saved flag, drops stale ones and reminder defaults, never to memories', async () => {
    expect(classifyLegacyEntry(event)).toBe('saved');
    expect(classifyLegacyEntry(defaults)).toBe('dropped');
    const d = deps([event, stale, defaults]);
    const result = await migrateLegacyTypedMemories(d);
    expect(state.documents).toHaveLength(0);
    expect(d.saveEmbed).toHaveBeenCalledWith('emb-1');
    expect(result).toMatchObject({ migrated: 0, saved: 1, dropped: 2, deleted: 3 });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('never migrates or deletes first-party privacy data stored in the same collection', async () => {
    const pii: LegacyTypedEntry = { id: 'entry-9', appId: 'privacy', itemType: 'personal_data_entry', itemKey: 'name', value: { name: 'A' } };
    const d = deps([pii]);
    expect(await migrateLegacyTypedMemories(d)).toMatchObject({ migrated: 0, deleted: 0 });
    expect(d.deleteEntry).not.toHaveBeenCalled();
    expect(state.documents).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('runs with the default browser deps, reading the description through the translate store', async () => {
    const result = await migrateLegacyTypedMemories(await createDefaultMigrationDeps());
    expect(result).toMatchObject({ migrated: 1, deleted: 1 });
    expect(parseRuleDocument(state.documents[0].document).when_to_use).toBe('Airlines the user prefers.');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('treats a missing type description as empty instead of a placeholder', () => {
    const translate = (key: string) => `[T:${key}]`;
    expect(describeLegacyType(translate, 'travel', 'unknown_type')).toBe('');
    expect(describeLegacyType((key) => key, 'travel', 'unknown_type')).toBe('');
  });
});

describe('legacy memory app_id', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('keeps the legacy app as app_id on newly migrated documents', async () => {
    await migrateLegacyTypedMemories(deps([travel]));
    expect(parseRuleDocument(state.documents[0].document).app_id).toBe('travel');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.migration.client-auto
  it('backfills app_id once from the recovery export without touching the body', async () => {
    const id = await deriveMemoryDocumentId('entry-1');
    const old = '---\ntitle: "Preferred airlines: x"\nwhen_to_use: Airlines.\nload_mode: ask_first\n---\n- **Airline**: Lufthansa\n';
    const edited = '---\ntitle: Own\napp_id: maps\n---\nBody\n';
    const documents = [
      { id, source: 'personal' as const, document: old },
      { id: 'personal:edited', source: 'personal' as const, document: edited },
    ];
    const settings: Record<string, unknown> = { [LEGACY_EXPORT_SETTINGS_KEY]: [
      { id: 'entry-1', app_id: 'travel', item_type: 't', item_key: 'k', value: {}, outcome: 'memory', document_id: id },
      { id: 'entry-5', app_id: 'travel', item_type: 't', item_key: 'k', value: {}, outcome: 'memory', document_id: 'personal:edited' },
      { id: 'entry-6', app_id: 'events', item_type: 'saved_events', item_key: 'k', value: {}, outcome: 'saved' },
    ] };
    expect(applyLegacyAppIdBackfill(settings, documents)).toBe(true);
    const fields = parseRuleDocument(documents[0].document);
    expect(fields.app_id).toBe('travel');
    expect(fields.body).toBe(parseRuleDocument(old).body);
    expect(documents[0].document.endsWith('---\n- **Airline**: Lufthansa\n')).toBe(true);
    expect(documents[1].document).toBe(edited);
    expect(applyLegacyAppIdBackfill(settings, documents)).toBe(false);
  });
});
