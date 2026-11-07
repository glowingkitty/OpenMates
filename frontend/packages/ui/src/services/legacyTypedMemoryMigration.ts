/**
 * Automatic client-side migration of legacy app-specific typed memory entries
 * (`user_app_settings_and_memories`) to Memory documents and saved flags.
 *
 * Contract (specification app-memories: migration.client-auto, typed.removed):
 * - Memory entries become personal Memory documents: title "Type: entry", fields as
 *   Markdown, when_to_use from the type description, load mode Ask first.
 * - The document id derives deterministically from the entry id, so concurrent devices
 *   converge on one document.
 * - A legacy entry is deleted only after its document and a recovery export were written
 *   to the encrypted account settings and the server acknowledged that sync.
 * - Saved-item entries (events, stays, connections, listings, appointments) map to the
 *   embed saved flag without reminders when the embed still resolves, otherwise they are dropped.
 *   Reminder defaults are dropped.
 * - Every run recomputes its work from stored state, so it is crash-safe and resumable.
 *
 * TRANSITIONAL: remove together with the legacy read+delete route once clients migrated.
 */
import { get } from 'svelte/store';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { MAX_RULE_DOCUMENTS, parseRuleDocument, serializeRuleDocument } from '../utils/ruleDocuments';
import { updateAccountSettings } from './ruleDocumentService';

export const LEGACY_EXPORT_SETTINGS_KEY = 'legacy_typed_memory_export';
const MAX_EXPORT_BYTES = 400_000;

/** Legacy item types that describe saved items (saved flag, not Memory documents). */
export const SAVED_ITEM_TYPES = new Set([
  'saved_events', 'saved_connections', 'saved_stays', 'saved_listings', 'appointments',
]);
/** Legacy item types that are settings and are dropped (offsets are constants now). */
export const DROPPED_ITEM_TYPES = new Set(['saved_item_reminder_defaults']);

/** First-party non-memory data sharing the legacy collection (personal data, PII settings): never migrated or deleted. */
export const NON_MEMORY_APP_IDS = new Set(['privacy']);

export interface LegacyTypedEntry {
  id: string;
  appId: string;
  itemType: string;
  itemKey: string;
  value: Record<string, unknown>;
}

export interface LegacyExportRecord {
  id: string;
  app_id: string;
  item_type: string;
  item_key: string;
  value: Record<string, unknown>;
  outcome: 'memory' | 'saved' | 'dropped';
  document_id?: string;
}

export type LegacyEntryClass = 'memory' | 'saved' | 'dropped';

export function classifyLegacyEntry(entry: Pick<LegacyTypedEntry, 'appId' | 'itemType'>): LegacyEntryClass {
  if (DROPPED_ITEM_TYPES.has(entry.itemType) || entry.appId === 'reminder') return 'dropped';
  if (SAVED_ITEM_TYPES.has(entry.itemType)) return 'saved';
  return 'memory';
}

/** Deterministic personal Memory document id derived from the legacy entry id. */
export async function deriveMemoryDocumentId(entryId: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`legacy-typed-memory:${entryId}`)));
  const b = digest.slice(0, 16);
  b[6] = (b[6] & 0x0f) | 0x50;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `personal:${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function humanize(id: string): string {
  const words = id.replace(/[_-]+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : id;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.trim();
  if (Array.isArray(value)) return value.map(renderValue).filter(Boolean).join(', ');
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !key.startsWith('_'))
      .map(([key, v]) => `${humanize(key)}: ${renderValue(v)}`).join('; ');
  }
  return String(value);
}

/** Entry fields (no internal `_` keys) as readable Markdown. */
export function renderEntryBody(value: Record<string, unknown>): string {
  const lines = Object.entries(value)
    .filter(([key]) => !key.startsWith('_'))
    .map(([key, v]) => [key, renderValue(v)] as const)
    .filter(([, rendered]) => rendered !== '')
    .map(([key, rendered]) => `- **${humanize(key)}**: ${rendered.replace(/\r?\n/g, ' ')}`);
  return lines.join('\n');
}

function firstField(value: Record<string, unknown>): string {
  for (const [key, v] of Object.entries(value)) {
    if (key.startsWith('_')) continue;
    const rendered = renderValue(v);
    if (rendered) return rendered;
  }
  return '';
}

/** Builds the serialized Memory document for one legacy entry (Ask first). */
export function buildMemoryDocumentFromLegacy(entry: LegacyTypedEntry, typeDescription: string): string {
  const typeName = humanize(entry.itemType);
  const entryTitle = (entry.itemKey && entry.itemKey !== entry.id ? entry.itemKey : '') || firstField(entry.value) || humanize(entry.appId);
  const title = `${typeName}: ${entryTitle.replace(/\s+/g, ' ')}`.slice(0, 180).trim();
  const body = renderEntryBody(entry.value) || `- ${entryTitle}`;
  const when = (typeDescription || `Relevant ${humanize(entry.appId)} ${typeName.toLowerCase()} preferences.`).trim().slice(0, 1200);
  return serializeRuleDocument({ title, when_to_use: when, body: body.slice(0, 19_000), load_mode: 'ask_first' });
}

/** Injectable boundaries so the migration is testable without browser storage. */
export interface MigrationDeps {
  listEntries: () => Promise<LegacyTypedEntry[]>;
  describeType: (appId: string, itemType: string) => string;
  /** Marks the embed saved without scheduling reminders; false when the embed does not resolve. */
  saveEmbed: (embedId: string) => Promise<boolean>;
  /** Deletes the entry on the server and locally; false when it could not be sent. */
  deleteEntry: (entryId: string) => Promise<boolean>;
}

export interface MigrationResult {
  migrated: number;
  saved: number;
  dropped: number;
  deleted: number;
  pending: number;
}

function embedIdOf(entry: LegacyTypedEntry): string {
  const raw = entry.value.embed_id;
  return typeof raw === 'string' ? raw : '';
}

function readExport(settings: Record<string, unknown>): LegacyExportRecord[] {
  const raw = settings[LEGACY_EXPORT_SETTINGS_KEY];
  return Array.isArray(raw) ? raw as LegacyExportRecord[] : [];
}

let inFlight: Promise<MigrationResult> | null = null;

/** Single-flight migration run; safe to call repeatedly. */
export function migrateLegacyTypedMemories(deps: MigrationDeps): Promise<MigrationResult> {
  inFlight ??= runMigration(deps).finally(() => { inFlight = null; });
  return inFlight;
}

async function runMigration(deps: MigrationDeps): Promise<MigrationResult> {
  const result: MigrationResult = { migrated: 0, saved: 0, dropped: 0, deleted: 0, pending: 0 };
  const entries = (await deps.listEntries()).filter((entry) => entry.id && !NON_MEMORY_APP_IDS.has(entry.appId));
  if (!entries.length) return result;

  // Saved items: idempotent flag write, no reminders. Only after it may the entry be exported/deleted.
  const handled = new Map<string, LegacyEntryClass>();
  for (const entry of entries) {
    const kind = classifyLegacyEntry(entry);
    if (kind === 'saved') {
      const embedId = embedIdOf(entry);
      if (embedId && await deps.saveEmbed(embedId)) result.saved += 1;
      else result.dropped += 1;
    } else if (kind === 'dropped') {
      result.dropped += 1;
    }
    handled.set(entry.id, kind);
  }

  // One atomic synced write: documents + recovery export (acknowledged by the server before any delete).
  const documentIds = new Map<string, string>();
  const readyForDelete = new Set<string>();
  const memoryEntries = entries.filter((entry) => handled.get(entry.id) === 'memory');
  const derived = new Map<string, string>();
  for (const entry of memoryEntries) derived.set(entry.id, await deriveMemoryDocumentId(entry.id));

  await updateAccountSettings((settings, documents) => {
    const existingIds = new Set(documents.map((doc) => doc.id));
    const exported = readExport(settings);
    const exportedIds = new Set(exported.map((record) => record.id));
    let changed = false;
    let exportBytes = JSON.stringify(exported).length;

    for (const entry of entries) {
      const kind = handled.get(entry.id)!;
      const documentId = derived.get(entry.id);
      if (kind === 'memory' && documentId) {
        if (!existingIds.has(documentId)) {
          if (documents.length >= MAX_RULE_DOCUMENTS) { result.pending += 1; continue; }
          const document = buildMemoryDocumentFromLegacy(entry, deps.describeType(entry.appId, entry.itemType));
          parseRuleDocument(document);
          documents.push({ id: documentId, source: 'personal', document });
          existingIds.add(documentId);
          result.migrated += 1;
          changed = true;
        }
        documentIds.set(entry.id, documentId);
      }
      if (!exportedIds.has(entry.id)) {
        const record: LegacyExportRecord = {
          id: entry.id, app_id: entry.appId, item_type: entry.itemType, item_key: entry.itemKey,
          value: entry.value, outcome: kind, ...(documentId ? { document_id: documentId } : {}),
        };
        const size = JSON.stringify(record).length;
        if (exportBytes + size > MAX_EXPORT_BYTES) { result.pending += 1; continue; }
        exported.push(record);
        exportedIds.add(entry.id);
        exportBytes += size;
        changed = true;
      }
      readyForDelete.add(entry.id);
    }
    if (changed) settings[LEGACY_EXPORT_SETTINGS_KEY] = exported;
    return changed;
  });

  // Reaching here means the write above was acknowledged (or nothing needed writing).
  for (const entry of entries) {
    if (!readyForDelete.has(entry.id)) continue;
    if (await deps.deleteEntry(entry.id)) result.deleted += 1;
    else result.pending += 1;
  }
  return result;
}

/** Recovery export of migrated entries, for download. */
export async function getLegacyTypedMemoryExport(): Promise<LegacyExportRecord[]> {
  let records: LegacyExportRecord[] = [];
  await updateAccountSettings((settings) => { records = readExport(settings); return false; });
  return records;
}

/** Clears the recovery export. */
export async function clearLegacyTypedMemoryExport(): Promise<void> {
  await updateAccountSettings((settings) => {
    if (!(LEGACY_EXPORT_SETTINGS_KEY in settings)) return false;
    delete settings[LEGACY_EXPORT_SETTINGS_KEY];
    return true;
  });
}

async function defaultDeps(): Promise<MigrationDeps> {
  const [{ chatDB }, { decryptWithMasterKey }, { text }, saved, { chatSyncService }] = await Promise.all([
    import('./db'), import('./cryptoService'), import('../i18n/translations'),
    import('./savedEmbedService'), import('./chatSyncService'),
  ]);
  return {
    listEntries: async () => {
      const rows = await chatDB.getAllAppSettingsMemoriesEntries();
      const entries: LegacyTypedEntry[] = [];
      for (const row of rows) {
        let value: Record<string, unknown> | null = null;
        try {
          const json = await decryptWithMasterKey(row.encrypted_item_json);
          const parsed: unknown = json ? JSON.parse(json) : null;
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) value = parsed as Record<string, unknown>;
        } catch (error) {
          console.warn('[legacyTypedMemoryMigration] Entry not decryptable yet; retrying later', row.id, error);
        }
        if (!value) continue; // never migrate or delete what could not be read
        const original = typeof value._original_item_key === 'string' ? value._original_item_key : row.item_key;
        entries.push({ id: row.id, appId: row.app_id, itemType: row.item_type, itemKey: original, value });
      }
      return entries;
    },
    describeType: (appId, itemType) => {
      const key = `${appId}.${itemType}.description`;
      const resolved = text(key);
      return resolved && resolved !== key ? resolved : '';
    },
    saveEmbed: async (embedId) => {
      try { await saved.setEmbedSaved(embedId, true, { scheduleReminders: false }); return true; }
      catch { return false; } // embed no longer resolves on this device: the legacy item is dropped
    },
    deleteEntry: async (entryId) => {
      if (!(await chatSyncService.sendDeleteAppSettingsMemoriesEntry(entryId))) return false;
      return chatDB.deleteAppSettingsMemoriesEntry(entryId);
    },
  };
}

let started = false;
/**
 * Starts the background migration for authenticated sessions only (never public/demo
 * sessions). Reruns when legacy entries arrive from sync or the tab returns to foreground.
 */
export function startLegacyTypedMemoryMigration(depsFactory: () => Promise<MigrationDeps> = defaultDeps): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  const run = async () => {
    if (!get(authStore).isAuthenticated || !get(userProfile).user_id || !get(userProfile).encrypted_settings) return;
    try { await migrateLegacyTypedMemories(await depsFactory()); }
    catch (error) { console.warn('[legacyTypedMemoryMigration] Run skipped; will retry', error); }
  };
  userProfile.subscribe(() => { void run(); });
  window.addEventListener('appSettingsMemoriesSyncReady', () => { void run(); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void run(); });
}
