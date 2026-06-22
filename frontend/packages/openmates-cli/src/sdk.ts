/*
 * OpenMates npm SDK facade.
 *
 * Purpose: provide an ergonomic API-key client for Node integrations.
 * Architecture: thin REST facade over public /v1 endpoints; CLI client remains separate.
 * Security: API keys are bearer credentials and are never persisted by this class.
 * Tests: frontend/packages/openmates-cli/tests/sdk.test.ts
 */

import { GeneratedAppSkills } from "./generated/appSkills.js";
import { createHash, randomUUID } from "node:crypto";
import {
  buildEncryptedConnectedAccountImportRow,
  decryptConnectedAccountCliTransferPayload,
} from "./connectedAccountImport.js";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptWithAesGcmCombined,
  hashItemKey,
  unwrapApiKeyMasterKey,
} from "./crypto.js";
import {
  buildChatShareUrl,
  buildEmbedShareUrl,
  deriveWebOrigin,
  generateChatShareBlob,
  generateEmbedShareBlob,
  type ShareDuration,
} from "./shareEncryption.js";

const DEFAULT_API_URL = "https://api.openmates.org";

export interface OpenMatesOptions {
  apiKey?: string;
  apiUrl?: string;
}

export interface ChatCreateOptions {
  saveToAccount?: boolean;
  focusMode?: FocusModeSelection;
}

export interface ChatSendOptions extends ChatCreateOptions {
  history?: Array<Record<string, unknown>> | { messages?: Array<Record<string, unknown>> };
  memoryIds?: string[];
  model?: string;
}

export interface ChatListOptions {
  limit?: number;
  offset?: number;
}

export interface ConfirmedMutationOptions {
  confirmed?: boolean;
}

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
}

export interface EncryptedChatMetadata {
  id: string;
  encrypted_title?: string;
  encrypted_chat_key?: string;
  encrypted_chat_summary?: string;
  encrypted_category?: string;
  title?: string;
  chat_summary?: string;
  category?: string;
  updated_at?: string | number;
  created_at?: string | number;
  [key: string]: unknown;
}

export interface SdkSessionResponse {
  key_wrapper?: {
    encrypted_key?: string;
    salt?: string;
    key_iv?: string;
  };
}

export interface ChatResponse {
  content?: string;
  [key: string]: unknown;
}

export interface EncryptedEmbedRecord {
  id?: string;
  embed_id?: string;
  encrypted_type?: string;
  encrypted_content?: string;
  encrypted_text_preview?: string;
  parent_embed_id?: string;
  created_at?: string | number;
  [key: string]: unknown;
}

export interface EmbedKeyRecord {
  hashed_embed_id?: string;
  key_type?: string;
  hashed_chat_id?: string;
  encrypted_embed_key?: string;
  [key: string]: unknown;
}

export interface FocusModeSelection {
  appId: string;
  focusModeId: string;
}

export class OpenMatesConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OpenMatesConfigError";
  }
}

export class OpenMatesApiError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(status: number, data: unknown) {
    super(`OpenMates API request failed with HTTP ${status}`);
    this.name = "OpenMatesApiError";
    this.status = status;
    this.data = data;
  }
}

export class OpenMates {
  readonly apps: GeneratedAppSkills;
  readonly account: OpenMatesAccount;
  readonly benchmark: OpenMatesBenchmark;
  readonly billing: OpenMatesBilling;
  readonly chats: OpenMatesChats;
  readonly connectedAccounts: OpenMatesConnectedAccounts;
  readonly docs: OpenMatesDocs;
  readonly embeds: OpenMatesEmbeds;
  readonly feedback: OpenMatesFeedback;
  readonly inspirations: OpenMatesInspirations;
  readonly learningMode: OpenMatesLearningMode;
  readonly memories: OpenMatesMemories;
  readonly newChatSuggestions: OpenMatesNewChatSuggestions;
  readonly notifications: OpenMatesNotifications;
  readonly reminders: OpenMatesReminders;
  readonly settings: OpenMatesSettings;
  private readonly apiKey?: string;
  private readonly apiUrl: string;
  private masterKeyPromise?: Promise<Uint8Array>;

  constructor(options: OpenMatesOptions = {}) {
    this.apiKey = options.apiKey ?? process.env.OPENMATES_API_KEY;
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    this.apps = new GeneratedAppSkills(this.runAppSkill.bind(this));
    this.account = new OpenMatesAccount(this);
    this.benchmark = new OpenMatesBenchmark(this);
    this.billing = new OpenMatesBilling(this);
    this.chats = new OpenMatesChats(this);
    this.connectedAccounts = new OpenMatesConnectedAccounts(this);
    this.docs = new OpenMatesDocs(this);
    this.embeds = new OpenMatesEmbeds(this);
    this.feedback = new OpenMatesFeedback(this);
    this.inspirations = new OpenMatesInspirations(this);
    this.learningMode = new OpenMatesLearningMode(this);
    this.memories = new OpenMatesMemories(this);
    this.newChatSuggestions = new OpenMatesNewChatSuggestions(this);
    this.notifications = new OpenMatesNotifications(this);
    this.reminders = new OpenMatesReminders(this);
    this.settings = new OpenMatesSettings(this);
  }

  async runAppSkill<T = unknown>(appId: string, skillId: string, input: unknown): Promise<T> {
    return this.request<T>(`/v1/apps/${appId}/skills/${skillId}`, {
      input_data: input,
      parameters: {},
    });
  }

  async request<T>(path: string, body?: unknown): Promise<T> {
    return this.requestWithMethod<T>("POST", path, body);
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    return this.requestWithMethod<T>("PATCH", path, body);
  }

  async delete<T>(path: string, body?: unknown): Promise<T> {
    return this.requestWithMethod<T>("DELETE", path, body);
  }

  async get<T>(path: string): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method: "GET",
      headers: this.headers(false),
    });

    return this.parseResponse<T>(response);
  }

  async getRaw(path: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method: "GET",
      headers: this.headers(false),
    });

    if (!response.ok) {
      await this.parseResponse<never>(response);
    }
    return {
      contentType: response.headers.get("content-type") ?? "application/octet-stream",
      filename: extractFilename(response.headers.get("content-disposition")),
      data: await response.arrayBuffer(),
    };
  }

  webOrigin(): string {
    return deriveWebOrigin(this.apiUrl);
  }

  masterKey(): Promise<Uint8Array> {
    return this.getMasterKey();
  }

  async resolveEmbedKeyForShare(embedKeys: EmbedKeyRecord[], embedId: string): Promise<Uint8Array | null> {
    const masterKey = await this.getMasterKey();
    const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");
    return this.resolveLoadedEmbedKey(embedKeys, hashedEmbedId, masterKey, masterKey);
  }

  async decryptChatMetadata<T extends EncryptedChatMetadata>(chat: T): Promise<T> {
    if (typeof chat.encrypted_chat_key !== "string") {
      return chat;
    }
    const masterKey = await this.getMasterKey();
    const chatKey = await decryptBytesWithAesGcm(chat.encrypted_chat_key, masterKey);
    if (!chatKey) {
      return chat;
    }

    const decrypted: Record<string, unknown> = { ...chat };
    if (typeof chat.encrypted_title === "string") {
      decrypted.title = await decryptWithAesGcmCombined(chat.encrypted_title, chatKey);
    }
    if (typeof chat.encrypted_chat_summary === "string") {
      decrypted.chat_summary = await decryptWithAesGcmCombined(chat.encrypted_chat_summary, chatKey);
    }
    if (typeof chat.encrypted_category === "string") {
      decrypted.category = await decryptWithAesGcmCombined(chat.encrypted_category, chatKey);
    }
    return decrypted as T;
  }

  async decryptLoadedChatPayload<T extends Record<string, unknown>>(payload: T): Promise<T> {
    const chat = payload.chat;
    if (!chat || typeof chat !== "object") {
      return payload;
    }
    const chatMetadata = chat as EncryptedChatMetadata;
    const decryptedChat = await this.decryptChatMetadata(chatMetadata);
    const chatKey = typeof chatMetadata.encrypted_chat_key === "string"
      ? await decryptBytesWithAesGcm(chatMetadata.encrypted_chat_key, await this.getMasterKey())
      : null;
    if (!chatKey || !Array.isArray(payload.messages)) {
      return { ...payload, chat: decryptedChat } as T;
    }

    const messages = await Promise.all(payload.messages.map(async (rawMessage) => {
      const message = typeof rawMessage === "string"
        ? JSON.parse(rawMessage) as Record<string, unknown>
        : { ...(rawMessage as Record<string, unknown>) };
      if (typeof message.encrypted_content === "string") {
        message.content = await decryptWithAesGcmCombined(message.encrypted_content, chatKey);
      }
      if (typeof message.encrypted_sender_name === "string") {
        message.senderName = await decryptWithAesGcmCombined(message.encrypted_sender_name, chatKey);
      }
      if (typeof message.encrypted_category === "string") {
        message.category = await decryptWithAesGcmCombined(message.encrypted_category, chatKey);
      }
      if (typeof message.encrypted_model_name === "string") {
        message.modelName = await decryptWithAesGcmCombined(message.encrypted_model_name, chatKey);
      }
      return message;
    }));
    const embeds = Array.isArray(payload.embeds)
      ? await this.decryptLoadedChatEmbeds(
        payload.embeds as EncryptedEmbedRecord[],
        Array.isArray(payload.embed_keys) ? payload.embed_keys as EmbedKeyRecord[] : [],
        chatKey,
      )
      : payload.embeds;
    return { ...payload, chat: decryptedChat, messages, embeds } as T;
  }

  private async decryptLoadedChatEmbeds(
    embeds: EncryptedEmbedRecord[],
    embedKeys: EmbedKeyRecord[],
    chatKey: Uint8Array,
  ): Promise<Array<Record<string, unknown>>> {
    const masterKey = await this.getMasterKey();
    return Promise.all(embeds.map(async (embed) => {
      const embedId = String(embed.embed_id ?? embed.id ?? "");
      if (!embedId) {
        return { ...embed };
      }
      const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");
      const embedKey = await this.resolveLoadedEmbedKey(embedKeys, hashedEmbedId, masterKey, chatKey);
      if (!embedKey) {
        return { ...embed };
      }

      const decrypted: Record<string, unknown> = { ...embed };
      if (typeof embed.encrypted_type === "string") {
        decrypted.type = await decryptWithAesGcmCombined(embed.encrypted_type, embedKey);
      }
      if (typeof embed.encrypted_text_preview === "string") {
        decrypted.textPreview = await decryptWithAesGcmCombined(embed.encrypted_text_preview, embedKey);
      }
      if (typeof embed.encrypted_content === "string") {
        const content = await decryptWithAesGcmCombined(embed.encrypted_content, embedKey);
        decrypted.content = parseMaybeJson(content);
      }
      return decrypted;
    }));
  }

  private async resolveLoadedEmbedKey(
    embedKeys: EmbedKeyRecord[],
    hashedEmbedId: string,
    masterKey: Uint8Array,
    chatKey: Uint8Array,
  ): Promise<Uint8Array | null> {
    const matchingKeys = embedKeys.filter((key) => key.hashed_embed_id === hashedEmbedId);
    const masterKeyEntry = matchingKeys.find((key) => key.key_type === "master");
    if (typeof masterKeyEntry?.encrypted_embed_key === "string") {
      const embedKey = await decryptBytesWithAesGcm(masterKeyEntry.encrypted_embed_key, masterKey);
      if (embedKey) return embedKey;
    }
    const chatKeyEntry = matchingKeys.find((key) => key.key_type === "chat");
    if (typeof chatKeyEntry?.encrypted_embed_key === "string") {
      return decryptBytesWithAesGcm(chatKeyEntry.encrypted_embed_key, chatKey);
    }
    return null;
  }

  private async requestWithMethod<T>(method: string, path: string, body?: unknown): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    return this.parseResponse<T>(response);
  }

  private getMasterKey(): Promise<Uint8Array> {
    this.masterKeyPromise ??= this.loadMasterKey();
    return this.masterKeyPromise;
  }

  private async loadMasterKey(): Promise<Uint8Array> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }
    const session = await this.request<SdkSessionResponse>("/v1/sdk/session", {
      sdk_name: "npm",
      device_identity: `${process.platform}:${process.arch}`,
    });
    const wrapper = session.key_wrapper;
    if (!wrapper?.encrypted_key || !wrapper.salt || !wrapper.key_iv) {
      throw new OpenMatesConfigError("SDK session did not include API-key-wrapped master key material");
    }
    const masterKey = await unwrapApiKeyMasterKey({
      apiKey: this.apiKey,
      encryptedMasterKeyB64: wrapper.encrypted_key,
      saltB64: wrapper.salt,
      keyIvB64: wrapper.key_iv,
    });
    if (!masterKey) {
      throw new OpenMatesConfigError("Unable to decrypt SDK session master key with API key");
    }
    return masterKey;
  }

  private headers(hasBody = true): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
      "X-OpenMates-SDK": "npm",
      "X-OpenMates-Device-Identity": `${process.platform}:${process.arch}`,
    };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    let data: unknown = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      throw new OpenMatesApiError(response.status, data);
    }

    return data as T;
  }
}

function withQuery(path: string, query: Record<string, string | number | boolean | undefined | null> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const serialized = params.toString();
  return serialized ? `${path}?${serialized}` : path;
}

function requireConfirmed(options: ConfirmedMutationOptions | undefined, action: string): void {
  if (options?.confirmed !== true) {
    throw new OpenMatesConfigError(`${action} requires confirmed: true`);
  }
}

function unsupportedSdkFeature(feature: string): never {
  throw new OpenMatesConfigError(`${feature} is not available through the API-key SDK yet`);
}

function extractFilename(contentDisposition: string | null): string | undefined {
  if (!contentDisposition) return undefined;
  const encoded = contentDisposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
  if (encoded) return decodeURIComponent(encoded);
  return contentDisposition.match(/filename="?([^";]+)"?/)?.[1];
}

function normalizeHistory(history: ChatSendOptions["history"]): Array<Record<string, unknown>> {
  if (!history) return [];
  if (Array.isArray(history)) return history;
  return Array.isArray(history.messages) ? history.messages : [];
}

function parseMaybeJson(value: string | null): unknown {
  if (value === null) return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

export class OpenMatesChats {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(options: ChatListOptions = {}): Promise<EncryptedChatMetadata[]> {
    const result = await this.client.get<{ chats: EncryptedChatMetadata[] }>(
      withQuery("/v1/sdk/chats", { limit: options.limit ?? 10, offset: options.offset }),
    );
    const chats = Array.isArray(result.chats) ? result.chats : [];
    return Promise.all(chats.map((chat) => this.client.decryptChatMetadata(chat)));
  }

  async search(query: string, options: ChatListOptions = {}): Promise<EncryptedChatMetadata[]> {
    const normalized = query.trim().toLowerCase();
    const chats = await this.list({ limit: 0 });
    const offset = options.offset ?? 0;
    const limit = options.limit ?? 10;
    const matches = chats.filter((chat) => {
      const haystack = [chat.title, chat.chat_summary, chat.category, chat.id]
        .filter((value): value is string => typeof value === "string")
        .join("\n")
        .toLowerCase();
      return haystack.includes(normalized);
    });
    return matches.slice(offset, limit === 0 ? undefined : offset + limit);
  }

  async load(chatId: string): Promise<Record<string, unknown>> {
    const payload = await this.client.get<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(chatId)}`);
    return this.client.decryptLoadedChatPayload(payload);
  }

  async send(message: string, options: ChatSendOptions = {}): Promise<ChatResponse> {
    const result = await this.client.request<{ response?: ChatResponse }>("/v1/sdk/chats", {
      message,
      history: normalizeHistory(options.history),
      save_to_account: options.saveToAccount === true,
      memory_ids: options.memoryIds ?? [],
      model: options.model,
      focus_mode: options.focusMode
        ? { app_id: options.focusMode.appId, focus_mode_id: options.focusMode.focusModeId }
        : undefined,
    });
    return result.response ?? result;
  }

  async export(chatId: string, options: { format?: "json" | "markdown" | "yaml" } = {}): Promise<Record<string, unknown>> {
    const payload = await this.load(chatId);
    return this.client.request<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(chatId)}/export`, {
      format: options.format ?? "json",
      payload,
    });
  }

  async delete(chatId: string, options: ConfirmedMutationOptions): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Deleting a chat");
    return this.client.delete<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(chatId)}`);
  }

  async share(chatId: string, options: { expires?: number; password?: string } = {}): Promise<Record<string, unknown>> {
    const loaded = await this.load(chatId);
    const chat = loaded.chat as EncryptedChatMetadata | undefined;
    if (!chat?.encrypted_chat_key) {
      throw new OpenMatesConfigError("Chat does not include an encrypted chat key");
    }
    const chatKey = await decryptBytesWithAesGcm(chat.encrypted_chat_key, await this.client.masterKey());
    if (!chatKey) {
      throw new OpenMatesConfigError("Unable to decrypt chat key for share link");
    }
    const blob = await generateChatShareBlob(chatId, chatKey, (options.expires ?? 0) as ShareDuration, options.password);
    return { url: buildChatShareUrl(this.client.webOrigin(), chatId, blob) };
  }

  async followUps(chatId: string): Promise<string[]> {
    const payload = await this.load(chatId);
    const chat = payload.chat as Record<string, unknown> | undefined;
    const encrypted = chat?.encrypted_follow_up_request_suggestions;
    if (typeof encrypted !== "string") return [];
    const raw = await decryptWithAesGcmCombined(encrypted, await this.client.masterKey());
    const parsed = raw ? parseMaybeJson(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  }

  async incognito(message: string): Promise<ChatResponse> {
    return this.send(message, { saveToAccount: false });
  }
}

export class OpenMatesAccount {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async info(): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>("/v1/sdk/account");
  }

  async setTimezone(timezone: string): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/account/timezone", { timezone });
  }

  async listInterests(): Promise<Record<string, unknown>> {
    const data = await this.client.get<Record<string, unknown>>("/v1/sdk/account/topic-preferences");
    const encrypted = data.encrypted_settings;
    if (typeof encrypted !== "string") return { selectedTagIds: [] };
    const raw = await decryptWithAesGcmCombined(encrypted, await this.client.masterKey());
    const parsed = raw ? parseMaybeJson(raw) : {};
    return {
      selectedTagIds: typeof parsed === "object" && parsed !== null && Array.isArray((parsed as Record<string, unknown>).selected_tag_ids)
        ? (parsed as Record<string, unknown>).selected_tag_ids
        : [],
    };
  }

  async setInterests(selectedTagIds: string[]): Promise<Record<string, unknown>> {
    const encrypted_settings = await encryptWithAesGcmCombined(
      JSON.stringify({ selected_tag_ids: selectedTagIds }),
      await this.client.masterKey(),
    );
    return this.client.request<Record<string, unknown>>("/v1/sdk/account/topic-preferences", { encrypted_settings });
  }

  async clearInterests(): Promise<Record<string, unknown>> {
    return this.setInterests([]);
  }

  async exportManifest(): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>("/v1/sdk/account/export/manifest");
  }

  async exportData(): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>("/v1/sdk/account/export/data");
  }

  async setUsername(username: string): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/account/username", { username });
  }

  async storageOverview(): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>("/v1/sdk/account/storage");
  }

  async storageFiles(options: RequestOptions = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/account/storage/files", options.query));
  }

  async deleteStorage(options: ConfirmedMutationOptions & { fileId?: string; category?: string; all?: boolean }): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Deleting stored account files");
    return this.client.delete<Record<string, unknown>>("/v1/sdk/account/storage/files", {
      file_id: options.fileId,
      category: options.category,
      all: options.all === true,
    });
  }
}

export class OpenMatesSettings {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async setLanguage(language: string): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/settings/language", { language });
  }

  async setDarkMode(enabled: boolean): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/settings/dark-mode", { enabled });
  }

  async setFont(font: string): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/settings/font", { font });
  }

  async setModelDefaults(defaults: Record<string, string | null>): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/settings/ai-model-defaults", defaults);
  }

  async setChatAutoDelete(period: string): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/settings/auto-delete/chats", { period });
  }

  async shareDebugLogs(options: { duration?: string; confirmed: true }): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Sharing debug logs");
    return unsupportedSdkFeature("Debug-log sharing");
  }
}

export class OpenMatesMemories {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(options: RequestOptions = {}): Promise<Record<string, unknown>> {
    const data = await this.client.get<{ memories?: Array<Record<string, unknown>> }>(withQuery("/v1/sdk/memories", options.query));
    const memories = await Promise.all((data.memories ?? []).map(async (memory) => {
      const decrypted = { ...memory };
      if (typeof memory.encrypted_item_json === "string") {
        const raw = await decryptWithAesGcmCombined(memory.encrypted_item_json, await this.client.masterKey());
        decrypted.data = raw ? parseMaybeJson(raw) : null;
      }
      return decrypted;
    }));
    return { memories };
  }

  async types(options: RequestOptions = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/memories/types", options.query));
  }

  async create(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.storeMemory(input);
  }

  async update(id: string, input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.storeMemory({ ...input, id });
  }

  async delete(id: string, options: ConfirmedMutationOptions): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Deleting a memory");
    return this.client.delete<Record<string, unknown>>(`/v1/sdk/memories/${encodeURIComponent(id)}`);
  }

  private async storeMemory(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const appId = String(input.appId ?? input.app_id ?? "");
    const itemType = String(input.itemType ?? input.item_type ?? "");
    const rawItemValue = input.itemValue ?? input.item_value ?? input.data ?? {};
    const itemValue = rawItemValue && typeof rawItemValue === "object" && !Array.isArray(rawItemValue)
      ? rawItemValue as Record<string, unknown>
      : { value: rawItemValue };
    if (!appId || !itemType) {
      throw new OpenMatesConfigError("Memory create/update requires appId and itemType");
    }
    const now = Math.floor(Date.now() / 1000);
    const entry = {
      id: String(input.id ?? randomUUID()),
      app_id: appId,
      item_key: hashItemKey(appId, itemType),
      item_type: itemType,
      encrypted_item_json: await encryptWithAesGcmCombined(
        JSON.stringify({ ...itemValue, settings_group: appId, _original_item_key: itemType, added_date: now }),
        await this.client.masterKey(),
      ),
      encrypted_app_key: "",
      created_at: Number(input.created_at ?? now),
      updated_at: now,
      item_version: Number(input.itemVersion ?? input.item_version ?? 1),
    };
    return this.client.request<Record<string, unknown>>("/v1/sdk/memories", { entry });
  }
}

export class OpenMatesBilling {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async overview(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing"); }
  async usage(options: RequestOptions = {}): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/billing/usage", options.query)); }
  async usageSummaries(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/usage/summaries"); }
  async usageDaily(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/usage/daily"); }
  async usageExport(options: { months?: number } = {}): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(withQuery("/v1/sdk/billing/usage/export", { months: options.months })); }
  async createBankTransferOrder(credits: number): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/bank-transfer-orders", { credits_amount: credits, currency: "eur" }); }
  async bankTransferStatus(orderId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/billing/bank-transfer-orders/${encodeURIComponent(orderId)}`); }
  async listBankTransferOrders(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/bank-transfer-orders"); }
  async listInvoices(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/invoices"); }
  async downloadInvoice(invoiceId: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(`/v1/sdk/billing/invoices/${encodeURIComponent(invoiceId)}/download`); }
  async downloadCreditNote(invoiceId: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(`/v1/sdk/billing/invoices/${encodeURIComponent(invoiceId)}/credit-note/download`); }
  async requestRefund(invoiceId: string, options: ConfirmedMutationOptions & { emailEncryptionKey?: string }): Promise<Record<string, unknown>> { requireConfirmed(options, "Requesting an invoice refund"); return this.client.request<Record<string, unknown>>("/v1/sdk/billing/refund", { invoice_id: invoiceId, email_encryption_key: options.emailEncryptionKey }); }
  async redeemGiftCard(code: string): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/gift-cards/redeem", { code }); }
  async listRedeemedGiftCards(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/gift-cards/redeemed"); }
  async createGiftCardBankTransferOrder(credits: number): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/gift-cards/bank-transfer-orders", { credits_amount: credits, currency: "eur" }); }
  async giftCardPurchaseStatus(orderId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/billing/gift-cards/purchases/${encodeURIComponent(orderId)}`); }
  async listPurchasedGiftCards(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/gift-cards/purchased"); }
  async setLowBalanceAutoTopup(input: Record<string, unknown>): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/auto-topup/low-balance", input); }
}

export class OpenMatesNotifications {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async status(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/notifications/status"); }
  async list(options: { limit?: number } = {}): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/notifications", { limit: options.limit })); }
}

export class OpenMatesReminders {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/reminders"); }
  async update(id: string, input: Record<string, unknown>): Promise<Record<string, unknown>> { return this.client.patch<Record<string, unknown>>(`/v1/sdk/reminders/${encodeURIComponent(id)}`, input); }
  async delete(id: string, options: ConfirmedMutationOptions): Promise<Record<string, unknown>> { requireConfirmed(options, "Deleting a reminder"); return this.client.delete<Record<string, unknown>>(`/v1/sdk/reminders/${encodeURIComponent(id)}`); }
}

export class OpenMatesDocs {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/docs"); }
  async search(query: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/docs/search", { q: query })); }
  async show(slug: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/docs/${encodeURIComponent(slug)}`); }
  async download(slug: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/docs/${encodeURIComponent(slug)}/download`); }
}

export class OpenMatesEmbeds {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async show(embedId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/embeds/${encodeURIComponent(embedId)}`); }
  async share(embedId: string, options: { expires?: number; password?: string } = {}): Promise<Record<string, unknown>> {
    const shown = await this.show(embedId);
    const keys = Array.isArray(shown.embed_keys) ? shown.embed_keys as EmbedKeyRecord[] : [];
    const embedKey = await this.client.resolveEmbedKeyForShare(keys, embedId);
    if (!embedKey) throw new OpenMatesConfigError("Unable to resolve embed key for share link");
    const blob = await generateEmbedShareBlob(embedId, embedKey, (options.expires ?? 0) as ShareDuration, options.password);
    return { url: buildEmbedShareUrl(this.client.webOrigin(), embedId, blob) };
  }
  async versions(embedId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/embeds/${encodeURIComponent(embedId)}/versions`); }
  async version(embedId: string, version: number): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/embeds/${encodeURIComponent(embedId)}/versions/${version}`); }
  async restoreVersion(embedId: string, version: number, options: ConfirmedMutationOptions): Promise<Record<string, unknown>> { requireConfirmed(options, "Restoring an embed version"); return this.client.request<Record<string, unknown>>(`/v1/sdk/embeds/${encodeURIComponent(embedId)}/versions/${version}/restore`); }
}

export class OpenMatesConnectedAccounts {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async import(input: { payload: string; passcode: string }): Promise<Record<string, unknown>> {
    const payload = await decryptConnectedAccountCliTransferPayload(input.payload, input.passcode);
    const account = await this.client.get<Record<string, unknown>>("/v1/sdk/account");
    const userId = typeof account.id === "string" ? account.id : "";
    if (!userId) {
      throw new OpenMatesConfigError("Could not resolve current user id for connected account import");
    }
    const row = await buildEncryptedConnectedAccountImportRow({
      payload,
      userId,
      masterKey: await this.client.masterKey(),
    });
    return this.client.request<Record<string, unknown>>("/v1/sdk/connected-accounts/import", { row });
  }
}

export class OpenMatesLearningMode {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async status(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/learning-mode"); }
  async enable(input: { ageGroup: string; passcode: string }): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/learning-mode/enable", { age_group: input.ageGroup, passcode: input.passcode }); }
  async disable(passcode: string): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/learning-mode/disable", { passcode }); }
}

export class OpenMatesInspirations {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(options: { language?: string } = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/inspirations", { lang: options.language }));
  }
}

export class OpenMatesNewChatSuggestions {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(options: { limit?: number } = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/new-chat-suggestions", { limit: options.limit ?? 10 }));
  }
}

export class OpenMatesFeedback {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async assistantResponse(input: { rating: number }): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/feedback/assistant-response", input);
  }
}

export class OpenMatesBenchmark {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async run(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/benchmark/run", input);
  }

  async estimate(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/sdk/benchmark/estimate", input);
  }
}
