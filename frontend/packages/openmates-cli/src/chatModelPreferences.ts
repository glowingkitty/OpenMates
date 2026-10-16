/** Encrypted, local-first per-chat AI model selection for the CLI/TUI. */
import { createHmac } from "node:crypto";
import { chmodSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import { loadSession, resolveStateDir, type OpenMatesSession } from "./storage.js";
import { createTuiWorkspaceCache } from "./tuiWorkspaceCache.js";
import providerDisplayData from "../../ui/src/data/aiProviderDisplay.json" with { type: "json" };

export type ChatModelSelection = "auto" | (string & {});
export interface ChatModelCatalogEntry {
  /** Canonical provider/model route, identical to web composer values. */
  id: string;
  name: string;
  providerId: string;
  providerName: string;
  providerBrandName?: string;
  providerOrder?: number;
  description: string;
  capability?: "low" | "medium" | "high" | "max";
  releaseDate?: string;
  available: boolean;
}
/** Fresh availability can reset exact choices; cached availability cannot. */
export type ChatModelCatalog = ChatModelCatalogEntry[] & { authoritative: boolean };
export interface ChatModelPreferenceState {
  selection: ChatModelSelection;
  pending: boolean;
  restored: boolean;
}
export type ChatModelValidation = ChatModelPreferenceState & { reset: boolean };
export interface EncryptedModelPreference { ciphertext: string; version: number }
export interface ChatModelPreferenceClient {
  apiUrl?: string;
  hasSession(): boolean;
  getSession(): OpenMatesSession;
  resolveTeamContext(): string | null;
  getChatModelCatalogSources(): Promise<{ all: unknown; available: unknown; routes: unknown; health: unknown }>;
  getChatModelPreference(chatId: string, teamId?: string | null): Promise<EncryptedModelPreference | null>;
  compareAndSetChatModelPreference(
    chatId: string, ciphertext: string, expectedVersion: number, teamId?: string | null,
  ): Promise<EncryptedModelPreference | null>;
}
interface LocalRecord extends EncryptedModelPreference { pending: boolean }
interface LocalEnvelope { version: 2; owners: Record<string, Record<string, LocalRecord>> }
const FILE = "chat_model_preferences.json";
const CATALOG_KEY = "ai-model-catalog-v1";
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_CHATS = 2000;

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function string(value: unknown): string { return typeof value === "string" ? value : ""; }
function ownerToken(session: OpenMatesSession, teamId: string | null): string {
  return createHmac("sha256", Buffer.from(session.masterKeyExportedB64, "base64"))
    .update(JSON.stringify([session.apiUrl, session.hashedEmail, teamId, session.createdAt]))
    .digest("hex");
}
function keyFor(owner: string, chatId: string): string {
  return createHmac("sha256", Buffer.from(owner, "hex")).update(chatId).digest("hex");
}
function isRecord(value: unknown): value is LocalRecord {
  const v = object(value);
  return typeof v.ciphertext === "string" && v.ciphertext.length > 0 &&
    Number.isSafeInteger(v.version) && (v.version as number) >= 0 && typeof v.pending === "boolean";
}
function readLocal(owner: string, chatId: string): LocalRecord | null {
  try {
    const path = join(resolveStateDir(), FILE);
    const raw = readFileSync(path, "utf8");
    if (Buffer.byteLength(raw) > MAX_FILE_BYTES) return null;
    const envelope = object(JSON.parse(raw));
    if (envelope.version !== 2) return null;
    const record = object(object(envelope.owners)[owner])[keyFor(owner, chatId)];
    return isRecord(record) ? record : null;
  } catch { return null; }
}
function sameRecord(left: LocalRecord | null, right: LocalRecord | null): boolean {
  return left === right || (!!left && !!right && left.ciphertext === right.ciphertext &&
    left.version === right.version && left.pending === right.pending);
}
async function writeLocal(
  owner: string, chatId: string, record: LocalRecord, current: () => boolean,
  expected?: LocalRecord | null,
): Promise<LocalRecord | null> {
  if (!current()) throw new Error("Chat model preference owner changed.");
  const dir = resolveStateDir();
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  chmodSync(dir, 0o700);
  const path = join(dir, FILE);
  const release = await lockfile.lock(`${path}.write`, {
    realpath: false, stale: 30_000, retries: { retries: 15, factor: 1, minTimeout: 20, maxTimeout: 20 },
  });
  try {
    if (!current()) throw new Error("Chat model preference owner changed.");
    let owners: Record<string, Record<string, LocalRecord>> = {};
    try {
      const raw = readFileSync(path, "utf8");
      if (Buffer.byteLength(raw) <= MAX_FILE_BYTES) {
        const parsed = object(JSON.parse(raw));
        if (parsed.version === 2) {
          const entries = Object.entries(object(parsed.owners)).map(([ownerKey, values]) =>
            [ownerKey, Object.fromEntries(Object.entries(object(values)).filter(([, value]) => isRecord(value)))]);
          owners = Object.fromEntries(entries) as Record<string, Record<string, LocalRecord>>;
        }
      }
    } catch { /* New local store. */ }
    const chats = owners[owner] ?? {};
    const existing = chats[keyFor(owner, chatId)] ?? null;
    if (expected !== undefined && !sameRecord(existing, expected)) return existing;
    chats[keyFor(owner, chatId)] = record;
    owners[owner] = chats;
    if (Object.values(owners).reduce((sum, values) => sum + Object.keys(values).length, 0) > MAX_CHATS)
      throw new Error("Chat model preference cache is full.");
    const encoded = JSON.stringify({ version: 2, owners } satisfies LocalEnvelope);
    if (Buffer.byteLength(encoded) > MAX_FILE_BYTES) throw new Error("Chat model preference cache is full.");
    const temporary = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
    try {
      writeFileSync(temporary, encoded, { mode: 0o600, flag: "wx" });
      chmodSync(temporary, 0o600);
      if (!current()) throw new Error("Chat model preference owner changed.");
      renameSync(temporary, path);
    } finally { rmSync(temporary, { force: true }); }
    return record;
  } finally { await release(); }
}
function parseSelection(plaintext: string): ChatModelSelection {
  const parsed = object(JSON.parse(plaintext));
  if (parsed.mode === "auto") return "auto";
  if (parsed.mode === "exact" && typeof parsed.model === "string" && /^[^/\s]+\/[^\s]+$/.test(parsed.model))
    return parsed.model;
  throw new Error("Invalid encrypted chat model selection.");
}
function encodeSelection(selection: ChatModelSelection): string {
  if (selection === "auto") return JSON.stringify({ mode: "auto" });
  if (!/^[^/\s]+\/[^\s]+$/.test(selection)) throw new Error("Choose a model from the catalog.");
  return JSON.stringify({ mode: "exact", model: selection });
}
function sourceModels(source: unknown): Record<string, unknown>[] {
  const skills = object(object(object(source).apps).ai).skills;
  const ask = Array.isArray(skills) ? skills.find(value => object(value).id === "ask") : null;
  return Array.isArray(object(ask).models) ? object(ask).models as Record<string, unknown>[] : [];
}
function buildCatalog(
  raw: { all: unknown; available: unknown; routes: unknown; health: unknown },
): ChatModelCatalogEntry[] {
  if (!("apps" in object(raw.all)) || !("apps" in object(raw.available)) ||
      !Array.isArray(object(raw.routes).data))
    throw new Error("Model catalog response has an invalid shape.");
  const availableIds = new Set(sourceModels(raw.available).map(model => `${string(model.provider_id)}/${string(model.id)}`));
  const routeData = object(raw.routes).data;
  const routeEntries = (Array.isArray(routeData) ? routeData : [])
    .map((value: unknown) => object(value)).filter(value => string(value.id));
  const routes = new Map<string, Record<string, unknown>>(
    routeEntries.map(value => [string(value.id), value]),
  );
  const health = object(object(raw.health).providers);
  const brands = object(providerDisplayData);
  return sourceModels(raw.all).flatMap(model => {
    const modelId = string(model.id), providerId = string(model.provider_id);
    if (!modelId || !providerId) return [];
    const id = `${providerId}/${modelId}`;
    const route = routes.get(id);
    const meta = object(route?.openmates);
    const healthValue = object(health[providerId]);
    const capability = string(meta.capability_level);
    const created = route?.created;
    const releaseDate = typeof created === "number" && Number.isFinite(created) && created > 0
      ? new Date(created * 1000).toISOString().slice(0, 10) : undefined;
    return [{
      id, name: string(model.name) || modelId, providerId,
      providerName: string(model.provider_name) || providerId,
      providerBrandName: string(object(brands[providerId]).brandName) || undefined,
      providerOrder: typeof object(brands[providerId]).order === "number"
        ? object(brands[providerId]).order as number : undefined,
      description: string(model.description),
      capability: (["low", "medium", "high", "max"].includes(capability)
        ? capability : undefined) as ChatModelCatalogEntry["capability"],
      releaseDate,
      available: availableIds.has(id) && !!route &&
        (!string(healthValue.status) || healthValue.status === "healthy"),
    }];
  }).sort((a, b) => (a.providerOrder ?? Number.MAX_SAFE_INTEGER) - (b.providerOrder ?? Number.MAX_SAFE_INTEGER)
    || a.providerName.localeCompare(b.providerName) || a.name.localeCompare(b.name));
}

export function createChatModelPreferences(client: ChatModelPreferenceClient) {
  const states = new Map<string, ChatModelPreferenceState>();
  const serial = new Map<string, Promise<unknown>>();
  const listeners = new Map<string, Set<(state: ChatModelPreferenceState) => void>>();
  const capture = () => {
    if (!client.hasSession()) throw new Error("Sign in to choose a chat model.");
    const session = client.getSession();
    const teamId = client.resolveTeamContext();
    const owner = ownerToken(session, teamId);
    const persisted = loadSession();
    if (persisted && ownerToken(persisted, teamId) !== owner)
      throw new Error("Chat model preference owner changed.");
    const current = () => {
      try {
        if (!client.hasSession() || ownerToken(client.getSession(), client.resolveTeamContext()) !== owner) return false;
        if (!persisted) return true;
        const onDisk = loadSession();
        return !!onDisk && ownerToken(onDisk, teamId) === owner;
      } catch { return false; }
    };
    return { owner, teamId, current, masterKey: Buffer.from(session.masterKeyExportedB64, "base64") };
  };
  const checked = (current: () => boolean) => {
    if (!current()) throw new Error("Chat model preference owner changed.");
  };
  const decrypt = async (record: LocalRecord | EncryptedModelPreference, key: Buffer) => {
    const plaintext = await decryptWithAesGcmCombined(record.ciphertext, key);
    if (plaintext === null) throw new Error("Chat model preference could not be decrypted.");
    return parseSelection(plaintext);
  };
  const stateKey = (owner: string, chatId: string) => `${owner}:${chatId}`;
  const publish = (owner: string, chatId: string, state: ChatModelPreferenceState, current: () => boolean) => {
    checked(current);
    const key = stateKey(owner, chatId);
    states.set(key, state);
    for (const listener of listeners.get(key) ?? []) {
      try { listener(state); } catch { /* A UI listener cannot block encrypted persistence. */ }
    }
    return state;
  };
  const withChat = <T>(owner: string, chatId: string, work: () => Promise<T>): Promise<T> => {
    const key = stateKey(owner, chatId);
    const task = (serial.get(key) ?? Promise.resolve()).then(work);
    serial.set(key, task.catch(() => {}));
    return task;
  };
  const flush = async (chatId: string, context = capture()): Promise<ChatModelPreferenceState> => {
    const { owner, teamId, current, masterKey } = context;
    checked(current);
    const local = readLocal(owner, chatId);
    if (!local?.pending) return states.get(stateKey(owner, chatId)) ?? { selection: "auto", pending: false, restored: false };
    const selection = await decrypt(local, masterKey);
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const remote = await client.getChatModelPreference(chatId, teamId);
        checked(current);
        const expected = remote?.version ?? 0;
        const accepted = await client.compareAndSetChatModelPreference(chatId, local.ciphertext, expected, teamId);
        checked(current);
        if (!accepted) continue;
        await writeLocal(owner, chatId, { ...accepted, pending: false }, current);
        const state = { selection, pending: false, restored: true };
        return publish(owner, chatId, state, current);
      }
      throw new Error("Chat model preference conflicted repeatedly.");
    } catch {
      checked(current);
      const state = { selection, pending: true, restored: true };
      return publish(owner, chatId, state, current);
    }
  };
  return {
    async catalog(): Promise<ChatModelCatalog> {
      const context = capture();
      const cache = createTuiWorkspaceCache(client.getSession(), () => context.current() ? client.getSession() : null);
      try {
        const raw = await client.getChatModelCatalogSources();
        checked(context.current);
        const catalog = Object.assign(buildCatalog(raw), { authoritative: true });
        await cache.set(CATALOG_KEY, catalog).catch(() => false);
        checked(context.current);
        return catalog;
      } catch (error) {
        checked(context.current);
        const cached = await cache.get<ChatModelCatalogEntry[]>(CATALOG_KEY);
        if (cached) return Object.assign(cached, { authoritative: false });
        throw error;
      }
    },
    async restore(chatId: string): Promise<ChatModelPreferenceState> {
      const context = capture();
      const { owner, current, masterKey } = context;
      checked(current);
      const local = readLocal(owner, chatId);
      if (local) {
        // Present a verified local choice without waiting for a WS timeout.
        const selection = await decrypt(local, masterKey);
        checked(current);
        const initial = publish(owner, chatId, { selection, pending: local.pending, restored: true }, current);
        void withChat(owner, chatId, async () => {
          if (local.pending) return flush(chatId, context);
          return refreshRemote(chatId, context, local);
        }).catch(() => { /* The local selection remains usable offline. */ });
        return initial;
      }
      return withChat(owner, chatId, () => refreshRemote(chatId, context, null));
    },
    async select(chatId: string, selection: ChatModelSelection): Promise<ChatModelPreferenceState> {
      const context = capture();
      return withChat(context.owner, chatId, async () => {
        const { owner, current, masterKey } = context;
        const serialized = encodeSelection(selection);
        const ciphertext = await encryptWithAesGcmCombined(serialized, masterKey);
        checked(current);
        const previous = readLocal(owner, chatId);
        await writeLocal(owner, chatId, { ciphertext, version: previous?.version ?? 0, pending: true }, current);
        publish(owner, chatId, { selection, pending: true, restored: true }, current);
        return flush(chatId, context);
      });
    },
    subscribe(chatId: string, listener: (state: ChatModelPreferenceState) => void): () => void {
      const context = capture();
      const key = stateKey(context.owner, chatId);
      const group = listeners.get(key) ?? new Set();
      group.add(listener);
      listeners.set(key, group);
      return () => { group.delete(listener); if (group.size === 0) listeners.delete(key); };
    },
    current(chatId: string): ChatModelPreferenceState {
      const context = capture();
      return states.get(stateKey(context.owner, chatId)) ?? { selection: "auto", pending: false, restored: false };
    },
    async flushPending(chatId: string): Promise<ChatModelPreferenceState> {
      const context = capture();
      return withChat(context.owner, chatId, () => flush(chatId, context));
    },
    async validate(chatId: string, catalog: readonly ChatModelCatalogEntry[] & { authoritative?: boolean }): Promise<ChatModelValidation> {
      const current = this.current(chatId);
      if (catalog.authoritative === false) return { ...current, reset: false };
      if (current.selection === "auto" || catalog.some(entry => entry.id === current.selection && entry.available))
        return { ...current, reset: false };
      const reset = await this.select(chatId, "auto");
      return { ...reset, reset: true };
    },
  };
  async function refreshRemote(
    chatId: string,
    context: ReturnType<typeof capture>,
    local: LocalRecord | null,
  ): Promise<ChatModelPreferenceState> {
    const { owner, teamId, current, masterKey } = context;
    checked(current);
    let remote: EncryptedModelPreference | null = null;
    let confirmed = false;
    try {
      remote = await client.getChatModelPreference(chatId, teamId);
      confirmed = true;
    }
    catch {
      checked(current);
      if (!local) {
        const state = { selection: "auto", pending: false, restored: false };
        return publish(owner, chatId, state, current);
      }
    }
    checked(current);
    // A successful null response means the server has no preference. Cache that
    // verified default at revision zero, including when an old exact row vanished.
    if (confirmed && !remote) {
      const ciphertext = await encryptWithAesGcmCombined(encodeSelection("auto"), masterKey);
      checked(current);
      const autoRecord = { ciphertext, version: 0, pending: false };
      const stored = await writeLocal(owner, chatId, autoRecord, current, local);
      checked(current);
      if (!stored) return publish(owner, chatId, { selection: "auto", pending: false, restored: false }, current);
      if (stored !== autoRecord) {
        const selection = await decrypt(stored, masterKey);
        return publish(owner, chatId, { selection, pending: stored.pending, restored: true }, current);
      }
      return publish(owner, chatId, { selection: "auto", pending: false, restored: true }, current);
    }
    const chosen = remote && (!local || remote.version > local.version) ? remote : local;
    const selection = chosen ? await decrypt(chosen, masterKey) : "auto";
    checked(current);
    if (remote && chosen === remote) await writeLocal(owner, chatId, { ...remote, pending: false }, current);
    const state = { selection, pending: false, restored: true };
    return publish(owner, chatId, state, current);
  }
}
export type ChatModelPreferences = ReturnType<typeof createChatModelPreferences>;
