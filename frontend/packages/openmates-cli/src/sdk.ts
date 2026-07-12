/*
 * OpenMates npm SDK facade.
 *
 * Purpose: provide an ergonomic API-key client for Node integrations.
 * Architecture: thin REST facade over public /v1 endpoints; CLI client remains separate.
 * Security: API keys are bearer credentials and are never persisted by this class.
 * Tests: frontend/packages/openmates-cli/tests/sdk.test.ts
 */

import { GeneratedAppSkills } from "./generated/appSkills.js";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import {
  buildEncryptedConnectedAccountImportRow,
  decryptConnectedAccountCliTransferPayload,
} from "./connectedAccountImport.js";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  deriveChatCompletionRecoveryKeypair,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  hashItemKey,
  openChatCompletionRecoveryEnvelope,
  type ChatCompletionRecoveryEnvelope,
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
import type {
  WorkflowCapability,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowInputEvent,
  WorkflowInputSessionDetail,
  WorkflowInputSessionResult,
  WorkflowInputStartParams,
  WorkflowRunContentRetention,
  WorkflowRunDetail,
  WorkflowSummary,
  ProjectSourceCreateInput,
  ProjectSourceRecord,
  UserPlanCreateInput,
  UserPlanCriterionRecord,
  UserPlanRecord,
  UserPlanStatus,
  UserPlanUpdateInput,
  UserPlanVerificationRecord,
  UserTaskCreateInput,
  UserTaskRecord,
  UserTaskStartAIInput,
  UserTaskStatus,
  UserTaskUpdateInput,
} from "./client.js";

export type { ProjectSourceCreateInput, ProjectSourceRecord } from "./client.js";

const DEFAULT_API_URL = "https://api.openmates.org";
const DEFAULT_RECOVERY_POLL_INTERVAL_MS = 500;
const DEFAULT_RECOVERY_TIMEOUT_MS = 60_000;

export interface OpenMatesOptions {
  apiKey?: string;
  apiUrl?: string;
  deviceId?: string;
  deviceIdPath?: string;
}

export interface ChatCreateOptions {
  saveToAccount?: boolean;
  focusMode?: FocusModeSelection;
  chatId?: string;
  title?: string;
}

export interface ChatSendOptions extends ChatCreateOptions {
  history?: Array<Record<string, unknown>> | { messages?: Array<Record<string, unknown>> };
  memoryIds?: string[];
  model?: string;
  recoveryPollIntervalMs?: number;
  recoveryTimeoutMs?: number;
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

export interface EncryptedDraftRecord {
  chatId: string;
  encryptedDraftMd: string;
  encryptedDraftPreview: string | null;
  draftV: number;
}

export interface DraftRecord extends EncryptedDraftRecord {
  markdown: string;
  preview: string | null;
}

export interface SdkSessionResponse {
  user?: {
    id?: string;
  };
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
  readonly drafts: OpenMatesDrafts;
  readonly embeds: OpenMatesEmbeds;
  readonly feedback: OpenMatesFeedback;
  readonly inspirations: OpenMatesInspirations;
  readonly learningMode: OpenMatesLearningMode;
  readonly memories: OpenMatesMemories;
  readonly newChatSuggestions: OpenMatesNewChatSuggestions;
  readonly notifications: OpenMatesNotifications;
  readonly reminders: OpenMatesReminders;
  readonly projects: OpenMatesProjects;
  readonly settings: OpenMatesSettings;
  readonly plans: OpenMatesPlans;
  readonly tasks: OpenMatesTasks;
  readonly workflows: OpenMatesWorkflows;
  private readonly apiKey?: string;
  private readonly apiUrl: string;
  private readonly deviceId: string;
  private sdkSessionPromise?: Promise<SdkSessionResponse>;
  private masterKeyPromise?: Promise<Uint8Array>;

  constructor(options: OpenMatesOptions = {}) {
    this.apiKey = options.apiKey ?? process.env.OPENMATES_API_KEY;
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    this.deviceId = options.deviceId ?? loadOrCreateDeviceId(options.deviceIdPath);
    this.apps = new GeneratedAppSkills(this.runAppSkill.bind(this));
    this.account = new OpenMatesAccount(this);
    this.benchmark = new OpenMatesBenchmark(this);
    this.billing = new OpenMatesBilling(this);
    this.chats = new OpenMatesChats(this);
    this.connectedAccounts = new OpenMatesConnectedAccounts(this);
    this.docs = new OpenMatesDocs(this);
    this.drafts = new OpenMatesDrafts(this);
    this.embeds = new OpenMatesEmbeds(this);
    this.feedback = new OpenMatesFeedback(this);
    this.inspirations = new OpenMatesInspirations(this);
    this.learningMode = new OpenMatesLearningMode(this);
    this.memories = new OpenMatesMemories(this);
    this.newChatSuggestions = new OpenMatesNewChatSuggestions(this);
    this.notifications = new OpenMatesNotifications(this);
    this.reminders = new OpenMatesReminders(this);
    this.projects = new OpenMatesProjects(this);
    this.settings = new OpenMatesSettings(this);
    this.plans = new OpenMatesPlans(this);
    this.tasks = new OpenMatesTasks(this);
    this.workflows = new OpenMatesWorkflows(this);
  }

  async runAppSkill<T = unknown>(appId: string, skillId: string, input: unknown): Promise<T> {
    return this.request<T>(`/v1/apps/${appId}/skills/${skillId}`, {
      input_data: input,
      parameters: {},
    });
  }

  async request<T>(path: string, body?: unknown, timeoutMs?: number): Promise<T> {
    return this.requestWithMethod<T>("POST", path, body, timeoutMs);
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

  sdkSession(): Promise<SdkSessionResponse> {
    return this.getSdkSession();
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

  private async requestWithMethod<T>(method: string, path: string, body?: unknown, timeoutMs?: number): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: timeoutMs === undefined ? undefined : AbortSignal.timeout(timeoutMs),
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
    const session = await this.getSdkSession();
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

  private getSdkSession(): Promise<SdkSessionResponse> {
    this.sdkSessionPromise ??= this.request<SdkSessionResponse>("/v1/sdk/session", {
      sdk_name: "npm",
      device_identity: this.deviceId,
    });
    return this.sdkSessionPromise;
  }

  private headers(hasBody = true): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
      "X-OpenMates-SDK": "npm",
      "X-OpenMates-Device-Identity": this.deviceId,
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

function loadOrCreateDeviceId(customPath?: string): string {
  const path = customPath ?? join(homedir(), ".openmates", "sdk-device-id");
  if (existsSync(path)) {
    const stored = readFileSync(path, "utf8").trim();
    if (stored) return stored;
  }
  const deviceId = randomUUID();
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, `${deviceId}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(path, 0o600);
  return deviceId;
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
    if (options.saveToAccount === true) {
      return this.sendSaved(message, options);
    }
    const result = await this.client.request<{ response?: ChatResponse }>("/v1/sdk/chats", {
      message,
      history: normalizeHistory(options.history),
      save_to_account: false,
      memory_ids: options.memoryIds ?? [],
      model: options.model,
      focus_mode: options.focusMode
        ? { app_id: options.focusMode.appId, focus_mode_id: options.focusMode.focusModeId }
        : undefined,
    });
    return result.response ?? result;
  }

  private async sendSaved(message: string, options: ChatSendOptions): Promise<ChatResponse> {
    const masterKey = await this.client.masterKey();
    const session = await this.client.sdkSession();
    if (!session.user?.id) {
      throw new OpenMatesConfigError("SDK session did not include the authenticated user identity");
    }

    const chatId = options.chatId ?? randomUUID();
    const turnId = randomUUID();
    const messageId = randomUUID();
    const createdAt = Math.floor(Date.now() / 1000);
    let chatKey: Uint8Array;
    let encryptedChatKey: string;
    let expectedMessagesV = 0;
    let encryptedChatMetadata: Record<string, unknown> | undefined;

    if (options.chatId) {
      const loaded = await this.load(chatId);
      const chat = loaded.chat as EncryptedChatMetadata | undefined;
      if (!chat?.encrypted_chat_key) {
        throw new OpenMatesConfigError("Saved chat does not include encrypted chat key material");
      }
      const decrypted = await decryptBytesWithAesGcm(chat.encrypted_chat_key, masterKey);
      if (!decrypted) {
        throw new OpenMatesConfigError("Unable to decrypt saved chat key material");
      }
      chatKey = decrypted;
      encryptedChatKey = chat.encrypted_chat_key;
      expectedMessagesV = Number(chat.messages_v ?? 0);
    } else {
      chatKey = new Uint8Array(randomBytes(32));
      encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
      encryptedChatMetadata = {
        encrypted_title: await encryptWithAesGcmCombined(options.title ?? message.slice(0, 80), chatKey),
        encrypted_chat_key: encryptedChatKey,
        created_at: createdAt,
        updated_at: createdAt,
      };
    }

    const recovery = await deriveChatCompletionRecoveryKeypair(
      Buffer.from(chatKey).toString("base64url"),
      chatId,
      1,
    );
    const history = normalizeHistory(options.history);
    const inferenceRequest = {
      messages: [...history, { role: "user", content: message }],
      model: options.model,
      focus_mode: options.focusMode
        ? { app_id: options.focusMode.appId, focus_mode_id: options.focusMode.focusModeId }
        : undefined,
      memory_ids: options.memoryIds ?? [],
    };
    const result = await this.client.request<{
      chat_id?: string;
      preflight?: Record<string, unknown>;
      task_id?: string;
    }>("/v1/sdk/chats", {
      message,
      history,
      save_to_account: true,
      title: options.title,
      memory_ids: options.memoryIds ?? [],
      model: options.model,
      focus_mode: inferenceRequest.focus_mode,
      protocol_version: 1,
      chat_id: chatId,
      turn_id: turnId,
      message_id: messageId,
      chat_key_version: 1,
      encrypted_chat_key: encryptedChatKey,
      recovery_public_key: recovery.publicKey,
      expected_messages_v: expectedMessagesV,
      encrypted_user_message: {
        client_message_id: messageId,
        chat_id: chatId,
        encrypted_content: await encryptWithAesGcmCombined(message, chatKey),
        encrypted_sender_name: await encryptWithAesGcmCombined("User", chatKey),
        role: "user",
        created_at: createdAt,
        updated_at: createdAt,
      },
      encrypted_chat_metadata: encryptedChatMetadata,
      inference_request: inferenceRequest,
    });
    if (!result.task_id) {
      throw new OpenMatesConfigError("Saved chat dispatch did not return a stable inference task id");
    }
    const claim = await this.pollRecoveryClaim(
      result.task_id,
      options.recoveryTimeoutMs ?? DEFAULT_RECOVERY_TIMEOUT_MS,
      options.recoveryPollIntervalMs ?? DEFAULT_RECOVERY_POLL_INTERVAL_MS,
    );
    const recovered = await this.openRecoveryClaim(
      claim,
      recovery.privateKey,
      session.user.id,
      chatId,
      turnId,
    );
    const completedAt = Math.floor(Date.now() / 1000);
    const encryptedAssistantMessage: Record<string, unknown> = {
      client_message_id: recovered.assistantMessageId,
      chat_id: chatId,
      encrypted_content: await encryptWithAesGcmCombined(recovered.content, chatKey),
      encrypted_sender_name: await encryptWithAesGcmCombined("Assistant", chatKey),
      role: "assistant",
      user_message_id: messageId,
      created_at: completedAt,
      updated_at: completedAt,
    };
    if (recovered.category !== null) {
      encryptedAssistantMessage.encrypted_category = await encryptWithAesGcmCombined(recovered.category, chatKey);
    }
    if (recovered.modelName !== null) {
      encryptedAssistantMessage.encrypted_model_name = await encryptWithAesGcmCombined(recovered.modelName, chatKey);
    }
    const terminal = await this.client.request<Record<string, unknown>>(
      `/v1/sdk/chats/recovery/${encodeURIComponent(result.task_id)}/persist`,
      {
        protocol_version: 1,
        lease_generation: claim.lease_generation,
        lease_token: claim.lease_token,
        expected_messages_v: expectedMessagesV + 1,
        encrypted_assistant_message: encryptedAssistantMessage,
      },
    );
    if (terminal.state !== "TERMINAL") {
      throw new OpenMatesConfigError("Saved chat recovery did not reach terminal persistence");
    }
    return {
      content: recovered.content,
      category: recovered.category,
      model_name: recovered.modelName,
      chat_id: result.chat_id ?? chatId,
      task_id: result.task_id,
      preflight: result.preflight,
      terminal,
    };
  }

  private async pollRecoveryClaim(
    taskId: string,
    timeoutMs: number,
    pollIntervalMs: number,
  ): Promise<Record<string, unknown>> {
    if (!Number.isFinite(timeoutMs) || !Number.isFinite(pollIntervalMs) || timeoutMs <= 0 || pollIntervalMs <= 0) {
      throw new OpenMatesConfigError("Recovery timeout and poll interval must be finite and positive");
    }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) break;
        return await this.client.request<Record<string, unknown>>(
          `/v1/sdk/chats/recovery/${encodeURIComponent(taskId)}/claim`,
          { protocol_version: 1 },
          remainingMs,
        );
      } catch (error) {
        if (!(error instanceof OpenMatesApiError) || error.status !== 404) throw error;
      }
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) break;
      await new Promise((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remainingMs)));
    }
    throw new OpenMatesConfigError("Timed out waiting for saved chat recovery");
  }

  private async openRecoveryClaim(
    claim: Record<string, unknown>,
    recoveryPrivateKey: string,
    ownerId: string,
    chatId: string,
    turnId: string,
  ): Promise<{
    assistantMessageId: string;
    content: string;
    category: string | null;
    modelName: string | null;
  }> {
    const jobId = typeof claim.job_id === "string" ? claim.job_id : null;
    const assistantMessageId = typeof claim.assistant_message_id === "string" ? claim.assistant_message_id : null;
    const keyVersion = Number.isSafeInteger(claim.chat_key_version) ? Number(claim.chat_key_version) : null;
    if (
      claim.state !== "LEASED"
      || typeof claim.lease_token !== "string"
      || !Number.isSafeInteger(claim.lease_generation)
      || !jobId
      || !assistantMessageId
      || keyVersion !== 1
      || claim.chat_id !== chatId
      || claim.turn_id !== turnId
      || typeof claim.sealed_payload !== "string"
    ) {
      throw new OpenMatesConfigError("Recovery job claim returned invalid lease or identity data");
    }
    let envelope: ChatCompletionRecoveryEnvelope;
    try {
      envelope = JSON.parse(claim.sealed_payload) as ChatCompletionRecoveryEnvelope;
    } catch {
      throw new OpenMatesConfigError("Recovery job contained an invalid sealed envelope");
    }
    const plaintext = await openChatCompletionRecoveryEnvelope(envelope, {
      recoveryPrivateKey,
      ownerId,
      chatId,
      turnId,
      jobId,
      assistantMessageId,
      keyVersion,
    });
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext)) as Record<string, unknown>;
    } catch {
      throw new OpenMatesConfigError("Recovery job plaintext was not valid UTF-8 JSON");
    }
    const fields = ["assistant_message_id", "category", "chat_id", "content", "job_id", "key_version", "model_name", "turn_id"];
    if (
      Object.keys(payload).sort().join(",") !== fields.join(",")
      || payload.assistant_message_id !== assistantMessageId
      || payload.chat_id !== chatId
      || payload.turn_id !== turnId
      || payload.job_id !== jobId
      || payload.key_version !== keyVersion
      || typeof payload.content !== "string"
      || (payload.category !== null && typeof payload.category !== "string")
      || (payload.model_name !== null && typeof payload.model_name !== "string")
    ) {
      throw new OpenMatesConfigError("Recovery job plaintext did not match the terminal completion identity");
    }
    return {
      assistantMessageId,
      content: payload.content,
      category: payload.category as string | null,
      modelName: payload.model_name as string | null,
    };
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

export class OpenMatesDrafts {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async listEncrypted(): Promise<EncryptedDraftRecord[]> {
    const response = await this.client.get<{ drafts?: Array<Record<string, unknown>> }>("/v1/sdk/drafts");
    return (response.drafts ?? []).map(normalizeEncryptedDraft);
  }

  async list(): Promise<DraftRecord[]> {
    return Promise.all((await this.listEncrypted()).map((draft) => this.decrypt(draft)));
  }

  async getEncrypted(chatId: string): Promise<EncryptedDraftRecord | null> {
    const response = await this.client.get<{ draft?: Record<string, unknown> | null }>(
      `/v1/sdk/drafts/${encodeURIComponent(chatId)}`,
    );
    return response.draft ? normalizeEncryptedDraft(response.draft) : null;
  }

  async get(chatId: string): Promise<DraftRecord | null> {
    const encrypted = await this.getEncrypted(chatId);
    return encrypted ? this.decrypt(encrypted) : null;
  }

  private async decrypt(draft: EncryptedDraftRecord): Promise<DraftRecord> {
    const masterKey = await this.client.masterKey();
    const markdown = await decryptWithAesGcmCombined(draft.encryptedDraftMd, masterKey);
    if (markdown === null) throw new OpenMatesConfigError("Unable to decrypt draft markdown");
    const preview = draft.encryptedDraftPreview
      ? await decryptWithAesGcmCombined(draft.encryptedDraftPreview, masterKey)
      : markdown.slice(0, 160);
    return { ...draft, markdown, preview };
  }
}

function normalizeEncryptedDraft(raw: Record<string, unknown>): EncryptedDraftRecord {
  return {
    chatId: String(raw.chat_id ?? ""),
    encryptedDraftMd: String(raw.encrypted_draft_md ?? ""),
    encryptedDraftPreview: typeof raw.encrypted_draft_preview === "string"
      ? raw.encrypted_draft_preview
      : null,
    draftV: Number(raw.draft_v ?? 0),
  };
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

export class OpenMatesProjects {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async listSources(projectId: string): Promise<ProjectSourceRecord[]> {
    const response = await this.client.get<{ sources?: ProjectSourceRecord[] }>(`/v1/projects/${encodeURIComponent(projectId)}/sources`);
    return response.sources ?? [];
  }

  async createSource(projectId: string, input: ProjectSourceCreateInput): Promise<ProjectSourceRecord> {
    const response = await this.client.request<{ source?: ProjectSourceRecord }>(`/v1/projects/${encodeURIComponent(projectId)}/sources`, input);
    if (!response.source) throw new OpenMatesApiError(500, { detail: "Project source response missing source" });
    return response.source;
  }
}

export class OpenMatesTasks {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(filters: { status?: UserTaskStatus; chatId?: string; projectId?: string } = {}): Promise<UserTaskRecord[]> {
    const response = await this.client.get<{ tasks?: UserTaskRecord[] }>(withQuery("/v1/user-tasks", {
      status: filters.status,
      chat_id: filters.chatId,
      project_id: filters.projectId,
    }));
    return response.tasks ?? [];
  }

  async create(input: UserTaskCreateInput): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>("/v1/user-tasks", input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  async update(taskId: string, input: UserTaskUpdateInput): Promise<UserTaskRecord> {
    const response = await this.client.patch<{ task?: UserTaskRecord }>(`/v1/user-tasks/${encodeURIComponent(taskId)}`, input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  async startAI(taskId: string, input: UserTaskStartAIInput = {}): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>(`/v1/user-tasks/${encodeURIComponent(taskId)}/start-ai`, input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }
}

export class OpenMatesPlans {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(filters: { status?: UserPlanStatus; chatId?: string; projectId?: string; activeOnly?: boolean } = {}): Promise<UserPlanRecord[]> {
    const response = await this.client.get<{ plans?: UserPlanRecord[] }>(withQuery("/v1/user-plans", {
      status: filters.status,
      chat_id: filters.chatId,
      project_id: filters.projectId,
      active_only: filters.activeOnly,
    }));
    return response.plans ?? [];
  }

  async create(input: UserPlanCreateInput): Promise<UserPlanRecord> {
    const response = await this.client.request<{ plan?: UserPlanRecord }>("/v1/user-plans", input);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return response.plan;
  }

  async update(planId: string, input: UserPlanUpdateInput): Promise<UserPlanRecord> {
    const response = await this.client.patch<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}`, input);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return response.plan;
  }

  async activate(planId: string, input: Record<string, unknown> = {}): Promise<UserPlanRecord> {
    const response = await this.client.request<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/activate`, input);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return response.plan.primary_chat_id || typeof input.chat_id !== "string"
      ? response.plan
      : { ...response.plan, primary_chat_id: input.chat_id };
  }

  async complete(planId: string, input: Record<string, unknown> = {}): Promise<UserPlanRecord> {
    const response = await this.client.request<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/complete`, input);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return response.plan;
  }

  async createCriterion(planId: string, input: UserPlanCriterionRecord): Promise<UserPlanCriterionRecord> {
    const response = await this.client.request<{ criterion?: UserPlanCriterionRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/criteria`, input);
    if (!response.criterion) throw new OpenMatesApiError(500, { detail: "User plan criterion response missing criterion" });
    return response.criterion;
  }

  async createVerification(planId: string, input: UserPlanVerificationRecord & Record<string, unknown>): Promise<UserPlanVerificationRecord> {
    const response = await this.client.request<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/verification`, input);
    if (!response.verification) throw new OpenMatesApiError(500, { detail: "User plan verification response missing verification" });
    return response.verification;
  }

  async addVerificationEvidence(planId: string, verificationId: string, input: Partial<UserPlanVerificationRecord>): Promise<UserPlanVerificationRecord> {
    const response = await this.client.request<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/verification/${encodeURIComponent(verificationId)}/evidence`, input);
    if (!response.verification) throw new OpenMatesApiError(500, { detail: "User plan verification response missing verification" });
    return response.verification;
  }
}

export class OpenMatesWorkflows {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<WorkflowSummary[]> {
    const response = await this.client.get<{ workflows?: WorkflowSummary[] }>("/v1/workflows");
    return response.workflows ?? [];
  }

  async temporary(): Promise<WorkflowSummary[]> {
    const response = await this.client.get<{ workflows?: WorkflowSummary[] }>("/v1/workflows/temporary");
    return response.workflows ?? [];
  }

  async capabilities(): Promise<WorkflowCapability[]> {
    const response = await this.client.get<{ capabilities?: WorkflowCapability[] }>("/v1/workflows/capabilities");
    return response.capabilities ?? [];
  }

  async startInput(params: WorkflowInputStartParams): Promise<WorkflowInputSessionResult> {
    const response = await this.client.request<{ session?: WorkflowInputSessionResult }>("/v1/workflows/input", {
      ...(params.text !== undefined ? { text: params.text } : {}),
      input_type: params.inputType ?? "text",
      ...(params.audioRef !== undefined ? { audio_ref: params.audioRef } : {}),
      ...(params.selectedWorkflowId !== undefined ? { selected_workflow_id: params.selectedWorkflowId } : {}),
      ...(params.selectedProjectId !== undefined ? { selected_project_id: params.selectedProjectId } : {}),
    });
    if (!response.session) throw new OpenMatesApiError(500, { detail: "Workflow input response missing session" });
    return response.session;
  }

  async inputSession(sessionId: string): Promise<WorkflowInputSessionDetail> {
    const response = await this.client.get<{ session?: WorkflowInputSessionDetail }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}`);
    if (!response.session) throw new OpenMatesApiError(500, { detail: "Workflow input response missing session" });
    return response.session;
  }

  async inputEvents(sessionId: string, afterEventId = 0): Promise<WorkflowInputEvent[]> {
    const response = await this.client.get<{ events?: WorkflowInputEvent[] }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/events?after_event_id=${encodeURIComponent(String(afterEventId))}`);
    return response.events ?? [];
  }

  async followUpInput(sessionId: string, text: string): Promise<WorkflowInputSessionResult> {
    const response = await this.client.request<{ session?: WorkflowInputSessionResult }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/follow-up`, { text });
    if (!response.session) throw new OpenMatesApiError(500, { detail: "Workflow input response missing session" });
    return response.session;
  }

  async stopInput(sessionId: string): Promise<WorkflowInputSessionResult> {
    const response = await this.client.request<{ session?: WorkflowInputSessionResult }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/stop`, {});
    if (!response.session) throw new OpenMatesApiError(500, { detail: "Workflow input response missing session" });
    return response.session;
  }

  async undoInput(sessionId: string): Promise<WorkflowInputSessionResult> {
    const response = await this.client.request<{ session?: WorkflowInputSessionResult }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/undo`, {});
    if (!response.session) throw new OpenMatesApiError(500, { detail: "Workflow input response missing session" });
    return response.session;
  }

  async get(workflowId: string): Promise<WorkflowDetail> {
    const response = await this.client.get<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}`);
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async create(params: {
    title: string;
    description?: string | null;
    graph: WorkflowGraph;
    enabled?: boolean;
    runContentRetention?: WorkflowRunContentRetention;
    lifecycle?: "persisted" | "temporary";
    source?: string;
    sourceChatId?: string | null;
    createdByAssistant?: boolean;
    autoDeleteAt?: number | null;
  }): Promise<WorkflowDetail> {
    const response = await this.client.request<{ workflow?: WorkflowDetail }>("/v1/workflows", {
      title: params.title,
      ...(params.description !== undefined ? { description: params.description } : {}),
      graph: params.graph,
      enabled: params.enabled ?? false,
      run_content_retention: params.runContentRetention ?? "last_5",
      ...(params.lifecycle ? { lifecycle: params.lifecycle } : {}),
      ...(params.source ? { source: params.source } : {}),
      ...(params.sourceChatId !== undefined ? { source_chat_id: params.sourceChatId } : {}),
      ...(params.createdByAssistant !== undefined ? { created_by_assistant: params.createdByAssistant } : {}),
      ...(params.autoDeleteAt !== undefined ? { auto_delete_at: params.autoDeleteAt } : {}),
    });
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async update(
    workflowId: string,
    params: { title?: string; description?: string | null; graph?: WorkflowGraph; enabled?: boolean; runContentRetention?: WorkflowRunContentRetention },
  ): Promise<WorkflowDetail> {
    const payload: Record<string, unknown> = {};
    if (params.title !== undefined) payload.title = params.title;
    if (params.description !== undefined) payload.description = params.description;
    if (params.graph !== undefined) payload.graph = params.graph;
    if (params.enabled !== undefined) payload.enabled = params.enabled;
    if (params.runContentRetention !== undefined) payload.run_content_retention = params.runContentRetention;
    const response = await this.client.patch<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}`, payload);
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async enable(workflowId: string): Promise<WorkflowDetail> {
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/enable`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async disable(workflowId: string): Promise<WorkflowDetail> {
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/disable`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async delete(workflowId: string, options: ConfirmedMutationOptions = {}): Promise<{ deleted: boolean }> {
    requireConfirmed(options, "Deleting a workflow");
    return this.client.delete<{ deleted: boolean }>(`/v1/workflows/${encodeURIComponent(workflowId)}`);
  }

  async keep(workflowId: string): Promise<WorkflowDetail> {
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/keep`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return response.workflow;
  }

  async run(
    workflowId: string,
    params: { mode?: "manual" | "test"; input?: Record<string, unknown> } = {},
  ): Promise<WorkflowRunDetail> {
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
      mode: params.mode ?? "manual",
      input: params.input ?? {},
    });
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async runs(workflowId: string): Promise<WorkflowRunDetail[]> {
    const response = await this.client.get<{ runs?: WorkflowRunDetail[] }>(`/v1/workflows/${encodeURIComponent(workflowId)}/runs`);
    return response.runs ?? [];
  }

  async runDetail(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    const response = await this.client.get<{ run?: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`);
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }
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
