/*
 * OpenMates npm SDK facade.
 *
 * Purpose: provide an ergonomic API-key client for Node integrations.
 * Architecture: thin REST facade over public /v1 endpoints; CLI client remains separate.
 * Security: API keys are bearer credentials and are never persisted by this class.
 * Tests: frontend/packages/openmates-cli/tests/sdk.test.ts
 */

import { GeneratedAppSkills, type AppSkillRunOptions } from "./generated/appSkills.js";
import { decode as toonDecode } from "@toon-format/toon";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import {
  buildEncryptedConnectedAccountImportRow,
  decryptConnectedAccountCliTransferPayload,
} from "./connectedAccountImport.js";
import {
  exportDesignIcon,
  type DesignIconExportOptions,
  type DesignIconExportResult,
} from "./designIcons.js";
import {
  assertAccountExportPayloadSafe,
  sanitizeAccountExportManifest,
} from "./accountExportArchive.js";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  deriveChatCompletionRecoveryKeypair,
  bytesToBase64,
  createApiKeyCryptoMaterial,
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
import {
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptUserTask,
  decryptUserTasks,
  findTask,
  labelHashes,
  normalizeLabels,
  normalizeTaskPriority,
  type DecryptedUserTask,
  type TaskCreateOptions,
  type TaskPriorityLevel,
  type TaskUpdateOptions,
} from "./tasksCli.js";
import type {
  WorkflowCapability,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowInputEvent,
  WorkflowInputSessionDetail,
  WorkflowInputSessionResult,
  WorkflowInputStartParams,
  WorkflowTemplateImportPayload,
  WorkflowTemplateProjectionResult,
  WorkflowTemplateProjectionUpsertParams,
  PublicWorkflowTemplateProjection,
  WorkflowTemplateProjectionRevocationResult,
  WorkflowTemplateBindingCompletionParams,
  WorkflowTemplateBindingCompletionResult,
  WorkflowTemplateShortUrlParams,
  WorkflowTemplateShortUrlResult,
  ImportedWorkflowTemplate,
  ShortUrlRevokeResult,
  WorkflowRunContentRetention,
  WorkflowRunCancellationResult,
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
  UserTaskActionInput,
  UserTaskCreateInput,
  UserTaskReorderInput,
  UserTaskRecord,
  UserTaskStartAIInput,
  UserTaskStatus,
  UserTaskUpdateInput,
} from "./client.js";

export type { ProjectSourceCreateInput, ProjectSourceRecord } from "./client.js";

const DEFAULT_API_URL = "https://api.openmates.org";
const DEFAULT_RECOVERY_POLL_INTERVAL_MS = 500;
const DEFAULT_RECOVERY_TIMEOUT_MS = 60_000;
const PROMPT_INJECTION_DISABLED = "disabled";

function withAppSkillRunOptions(input: unknown, options?: AppSkillRunOptions): unknown {
  if (options?.promptInjectionProtection !== false) return input;
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new OpenMatesConfigError("App-skill prompt-injection opt-out requires object input.");
  }
  const currentSecurity = (input as Record<string, unknown>).security;
  const security = currentSecurity && typeof currentSecurity === "object" && !Array.isArray(currentSecurity)
    ? { ...(currentSecurity as Record<string, unknown>) }
    : {};
  return {
    ...(input as Record<string, unknown>),
    security: {
      ...security,
      prompt_injection_protection: PROMPT_INJECTION_DISABLED,
    },
  };
}

export interface OpenMatesOptions {
  apiKey?: string;
  apiUrl?: string;
  deviceId?: string;
  deviceIdPath?: string;
  sdkName?: "cli" | "npm" | "pip";
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

export interface AccountExportStartOptions {
  domains?: string[];
  filters?: Record<string, unknown>;
  format?: "zip" | "directory";
  includeAdvancedMetadata?: boolean;
  acceptPartial?: boolean;
}

export interface AccountExportResponse {
  export: Record<string, unknown>;
}

export interface AccountExportManifestResponse {
  manifest: Record<string, unknown>;
}

export interface AccountExportChunksResponse {
  chunks: Array<Record<string, unknown>>;
}

export interface ApiKeyCreateOptions {
  name: string;
  fullAccess?: boolean;
  scopes?: Record<string, unknown>;
  creditLimit?: Record<string, unknown> | null;
  expiresAt?: string | null;
}

export interface ApiKeyRecord {
  id: string;
  name: string;
  keyPrefix: string;
  createdAt?: string | null;
  expiresAt?: string | null;
  lastUsedAt?: string | null;
  lastUsedLabel: string;
  fullAccess: boolean;
  scopes: Record<string, unknown>;
  creditLimit?: Record<string, unknown> | null;
  pendingDeviceCount: number;
}

export interface ApiKeyCreateResult {
  apiKey: string;
  key: ApiKeyRecord;
}

export interface ApplicationPreviewStartOptions {
  chatId: string;
  sharedContext?: string;
  requestedRuntime?: string;
  sourceMessageId?: string;
  wait?: boolean;
  timeoutMs?: number;
}

export interface ApplicationPreviewStartResponse {
  session_id: string;
  preview_url: string;
  status: string;
  credits_per_minute: number;
}

export interface ApplicationPreviewEvent {
  kind: string;
  text: string;
  timestamp: number;
}

export interface ApplicationPreviewStatusResponse {
  session_id: string;
  status: string;
  events: ApplicationPreviewEvent[];
  error?: string | null;
  charged_credits?: number | null;
  latest_screenshot_url?: string | null;
  latest_screenshot?: Record<string, unknown> | null;
  auto_started: boolean;
  auto_opened_at?: number | null;
}

export interface ApplicationPreviewStopResponse {
  session_id: string;
  status: string;
  charged_credits?: number | null;
}

export interface EncryptedChatMetadata {
  id: string;
  encrypted_title?: string;
  encrypted_chat_key?: string;
  chat_key_wrappers?: ChatKeyWrapperRecord[];
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

export interface IdeaBucketAddInput extends Record<string, unknown> {
  text: string;
  chatId?: string;
  bucketId?: string;
  scheduledSendAt?: number;
  prompt?: string;
}

export interface IdeaBucketProcessOptions {
  now?: boolean;
}

export type IdeaBucketResult = Record<string, unknown>;

const IDEABUCKET_DEFAULT_PROCESSING_PROMPT = `These are my captured ideas for today. Please process them, group related thoughts, suggest next actions, and ask clarifying questions where needed:\n\nIf an idea requires deeper work, create or suggest sub-chats for focused research, planning, todos, docs, or implementation.`;

export type TaskListFilters = { status?: UserTaskStatus; chatId?: string; projectId?: string; labels?: string[]; tags?: string[]; priority?: TaskPriorityLevel | number | null };
export type TaskPlainCreateOptions = TaskCreateOptions;
export type TaskPlainUpdateOptions = TaskUpdateOptions;
export type TaskRecord = Omit<DecryptedUserTask, "encrypted">;

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

export interface ChatKeyWrapperRecord {
  hashed_chat_id?: string;
  key_type?: string;
  encrypted_chat_key?: string;
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
  readonly design: OpenMatesDesign;
  readonly drafts: OpenMatesDrafts;
  readonly embeds: OpenMatesEmbeds;
  readonly feedback: OpenMatesFeedback;
  readonly inspirations: OpenMatesInspirations;
  readonly ideabucket: OpenMatesIdeaBucket;
  readonly apiKeys: OpenMatesApiKeys;
  readonly learningMode: OpenMatesLearningMode;
  readonly memories: OpenMatesMemories;
  readonly newChatSuggestions: OpenMatesNewChatSuggestions;
  readonly notifications: OpenMatesNotifications;
  readonly reminders: OpenMatesReminders;
  readonly projects: OpenMatesProjects;
  readonly settings: OpenMatesSettings;
  readonly plans: OpenMatesPlans;
  readonly tasks: OpenMatesTasks;
  readonly teams: OpenMatesTeams;
  readonly workflows: OpenMatesWorkflows;
  private readonly apiKey?: string;
  private readonly apiUrl: string;
  private readonly deviceId: string;
  private readonly sdkName: "cli" | "npm" | "pip";
  private sdkSessionPromise?: Promise<SdkSessionResponse>;
  private masterKeyPromise?: Promise<Uint8Array>;

  constructor(options: OpenMatesOptions = {}) {
    this.apiKey = options.apiKey ?? process.env.OPENMATES_API_KEY;
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    this.deviceId = options.deviceId ?? loadOrCreateDeviceId(options.deviceIdPath);
    this.sdkName = options.sdkName ?? "npm";
    this.apps = new GeneratedAppSkills(this.runAppSkill.bind(this));
    this.account = new OpenMatesAccount(this);
    this.benchmark = new OpenMatesBenchmark(this);
    this.billing = new OpenMatesBilling(this);
    this.chats = new OpenMatesChats(this);
    this.connectedAccounts = new OpenMatesConnectedAccounts(this);
    this.docs = new OpenMatesDocs(this);
    this.design = new OpenMatesDesign(this);
    this.drafts = new OpenMatesDrafts(this);
    this.embeds = new OpenMatesEmbeds(this);
    this.feedback = new OpenMatesFeedback(this);
    this.inspirations = new OpenMatesInspirations(this);
    this.ideabucket = new OpenMatesIdeaBucket(this);
    this.apiKeys = new OpenMatesApiKeys(this);
    this.learningMode = new OpenMatesLearningMode(this);
    this.memories = new OpenMatesMemories(this);
    this.newChatSuggestions = new OpenMatesNewChatSuggestions(this);
    this.notifications = new OpenMatesNotifications(this);
    this.reminders = new OpenMatesReminders(this);
    this.projects = new OpenMatesProjects(this);
    this.settings = new OpenMatesSettings(this);
    this.plans = new OpenMatesPlans(this);
    this.tasks = new OpenMatesTasks(this);
    this.teams = new OpenMatesTeams(this);
    this.workflows = new OpenMatesWorkflows(this);
  }

  async runAppSkill<T = unknown>(appId: string, skillId: string, input: unknown, options?: AppSkillRunOptions): Promise<T> {
    return this.request<T>(`/v1/apps/${appId}/skills/${skillId}`, withAppSkillRunOptions(input, options));
  }

  async request<T>(path: string, body?: unknown, timeoutMs?: number, extraHeaders?: Record<string, string>): Promise<T> {
    return this.requestWithMethod<T>("POST", path, body, timeoutMs, extraHeaders);
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    return this.requestWithMethod<T>("PATCH", path, body);
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    return this.requestWithMethod<T>("PUT", path, body);
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

  async getPublic<T>(path: string): Promise<T> {
    const response = await fetch(`${this.apiUrl}${path}`, {
      method: "GET",
      headers: this.publicHeaders(),
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

  async decryptChatMetadata<T extends EncryptedChatMetadata>(
    chat: T,
    chatKeyWrappers?: ChatKeyWrapperRecord[],
  ): Promise<T> {
    const chatKey = await this.resolveLoadedChatKey(chat, chatKeyWrappers);
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
    const chatKeyWrappers = Array.isArray(payload.chat_key_wrappers)
      ? payload.chat_key_wrappers as ChatKeyWrapperRecord[]
      : Array.isArray(chatMetadata.chat_key_wrappers)
        ? chatMetadata.chat_key_wrappers
        : [];
    const decryptedChat = await this.decryptChatMetadata(chatMetadata, chatKeyWrappers);
    const chatKey = await this.resolveLoadedChatKey(chatMetadata, chatKeyWrappers);
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

  private async resolveLoadedChatKey(
    chat: EncryptedChatMetadata,
    chatKeyWrappers?: ChatKeyWrapperRecord[],
  ): Promise<Uint8Array | null> {
    const masterKey = await this.getMasterKey();
    const hashedChatId = createHash("sha256").update(chat.id).digest("hex");
    const wrapper = (chatKeyWrappers ?? []).find(
      (entry) =>
        entry.key_type === "master" &&
        entry.hashed_chat_id === hashedChatId &&
        typeof entry.encrypted_chat_key === "string",
    );
    const encryptedChatKey = typeof wrapper?.encrypted_chat_key === "string"
      ? wrapper.encrypted_chat_key
      : typeof chat.encrypted_chat_key === "string"
        ? chat.encrypted_chat_key
        : null;
    return encryptedChatKey ? decryptBytesWithAesGcm(encryptedChatKey, masterKey) : null;
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

  private async requestWithMethod<T>(
    method: string,
    path: string,
    body?: unknown,
    timeoutMs?: number,
    extraHeaders?: Record<string, string>,
  ): Promise<T> {
    if (!this.apiKey) {
      throw new OpenMatesConfigError("OpenMates API key is required");
    }

    const response = await fetch(`${this.apiUrl}${path}`, {
      method,
      headers: { ...this.headers(body !== undefined), ...extraHeaders },
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
      sdk_name: this.sdkName,
      device_identity: this.deviceId,
    });
    return this.sdkSessionPromise;
  }

  private headers(hasBody = true): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
      "X-OpenMates-SDK": this.sdkName,
      "X-OpenMates-Device-Identity": this.deviceId,
    };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  private publicHeaders(): Record<string, string> {
    return {
      Accept: "application/json",
      "X-OpenMates-SDK": this.sdkName,
      "X-OpenMates-Device-Identity": this.deviceId,
    };
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

function withQuery(path: string, query: Record<string, string | number | boolean | Array<string | number | boolean> | undefined | null> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.set(key, String(value));
    }
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
    try {
      return toonDecode(value, { strict: false }) as unknown;
    } catch {
      return value;
    }
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
        if (error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError")) break;
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

export class OpenMatesIdeaBucket {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async add(input: IdeaBucketAddInput): Promise<IdeaBucketResult> {
    const payload = await this.buildEncryptedAddPayload(input);
    const bucketId = String(payload.ideabucket_processing_window_id);
    return this.client.request<IdeaBucketResult>(
      `/v1/sdk/ideabucket/buckets/${encodeURIComponent(bucketId)}/add`,
      payload,
    );
  }

  async status(bucketId?: string): Promise<IdeaBucketResult> {
    const path = bucketId
      ? `/v1/sdk/ideabucket/buckets/${encodeURIComponent(bucketId)}`
      : "/v1/sdk/ideabucket/buckets";
    return this.client.get<IdeaBucketResult>(path);
  }

  async process(bucketId: string, options: IdeaBucketProcessOptions = {}): Promise<IdeaBucketResult> {
    return this.client.request<IdeaBucketResult>(
      `/v1/sdk/ideabucket/buckets/${encodeURIComponent(bucketId)}/process`,
      { now: options.now === true },
    );
  }

  private async buildEncryptedAddPayload(input: IdeaBucketAddInput): Promise<Record<string, unknown>> {
    const ideaText = input.text.trim();
    if (!ideaText) throw new OpenMatesConfigError("IdeaBucket add requires non-empty text.");
    const now = Math.floor(Date.now() / 1000);
    const bucketId = input.bucketId ?? new Date(now * 1000).toISOString().slice(0, 10);
    const scheduledSendAt = input.scheduledSendAt ?? defaultIdeaBucketScheduledSendAt(now);
    const chatId = input.chatId ?? randomUUID();
    const prompt = input.prompt ?? IDEABUCKET_DEFAULT_PROCESSING_PROMPT;
    const markdown = buildIdeaBucketMarkdown(prompt, ideaText);
    const preview = `IdeaBucket ${bucketId}: ${ideaText.slice(0, 120)}`;
    const serverProcessablePayload = JSON.stringify({
      prompt,
      bucket_id: bucketId,
      processing_window_id: bucketId,
      ideas: [{ index: 1, type: "text", text: ideaText }],
    });
    const payloadHash = createHash("sha256").update(serverProcessablePayload).digest("hex");
    const masterKey = await this.client.masterKey();
    return {
      chat_id: chatId,
      encrypted_draft_md: await encryptWithAesGcmCombined(markdown, masterKey),
      encrypted_draft_preview: await encryptWithAesGcmCombined(preview, masterKey),
      ideabucket: true,
      ideabucket_processing_window_id: bucketId,
      ideabucket_processing_version: now,
      scheduled_send_at: scheduledSendAt,
      server_vault_encrypted_processing_payload: await encryptWithAesGcmCombined(serverProcessablePayload, masterKey),
      client_encrypted_future_user_message: await encryptWithAesGcmCombined(markdown, masterKey),
      client_encrypted_ideabucket_system_event: await encryptWithAesGcmCombined(JSON.stringify({
        type: "ideabucket_triggered_send",
        bucket_id: bucketId,
        processing_window_id: bucketId,
        source: "openmates_sdk",
      }), masterKey),
      payload_hash: payloadHash,
    };
  }
}

function defaultIdeaBucketScheduledSendAt(nowSeconds: number): number {
  const date = new Date(nowSeconds * 1000);
  return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1, 9, 0, 0) / 1000);
}

function buildIdeaBucketMarkdown(prompt: string, ideaText: string): string {
  return [prompt.trim(), [
    "----- Idea 1 -----",
    ideaText.trim(),
    "-----------------",
  ].join("\n")].join("\n\n");
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

  async startExport(options: AccountExportStartOptions = {}): Promise<AccountExportResponse> {
    return this.client.request<AccountExportResponse>("/v1/account-exports", {
      domains: options.domains,
      filters: options.filters ?? {},
      format: options.format ?? "zip",
      include_advanced_metadata: options.includeAdvancedMetadata === true,
    });
  }

  async getExport(exportId: string): Promise<AccountExportResponse> {
    return this.client.get<AccountExportResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}`);
  }

  async exportJobManifest(exportId: string): Promise<AccountExportManifestResponse> {
    return this.client.get<AccountExportManifestResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}/manifest`);
  }

  async exportChunks(exportId: string): Promise<AccountExportChunksResponse> {
    return this.client.get<AccountExportChunksResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}/chunks`);
  }

  async exportChunk(exportId: string, chunkId: string): Promise<Record<string, unknown>> {
    const result = await this.client.get<{ chunk?: Record<string, unknown> }>(`/v1/account-exports/${encodeURIComponent(exportId)}/chunks/${encodeURIComponent(chunkId)}`);
    const chunk = result.chunk ?? {};
    assertAccountExportPayloadSafe(chunk);
    return chunk;
  }

  async *iterExportChunks(exportId: string): AsyncGenerator<Record<string, unknown>> {
    const listed = await this.exportChunks(exportId);
    for (const chunk of listed.chunks) {
      const chunkId = String(chunk.chunk_id ?? "");
      yield chunkId ? await this.exportChunk(exportId, chunkId) : chunk;
    }
  }

  async completeExport(exportId: string): Promise<AccountExportResponse> {
    return this.client.request<AccountExportResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}/complete`, {});
  }

  async acceptPartialExport(exportId: string): Promise<AccountExportResponse> {
    return this.client.request<AccountExportResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}/accept-partial`, {});
  }

  async cancelExport(exportId: string): Promise<AccountExportResponse> {
    return this.client.request<AccountExportResponse>(`/v1/account-exports/${encodeURIComponent(exportId)}/cancel`, {});
  }

  async downloadExport(options: AccountExportStartOptions = {}): Promise<Record<string, unknown>> {
    const started = await this.startExport(options);
    const exportId = String(started.export.export_id ?? "");
    const [manifest, chunks] = await Promise.all([
      this.exportJobManifest(exportId),
      this.exportChunks(exportId),
    ]);
    const downloadedChunks: Array<Record<string, unknown>> = [];
    try {
      for (const chunk of chunks.chunks) {
        const chunkId = String(chunk.chunk_id ?? "");
        downloadedChunks.push(chunkId ? await this.exportChunk(exportId, chunkId) : chunk);
      }
    } catch (error) {
      await this.cancelExport(exportId).catch(() => undefined);
      throw error;
    }
    let completed = await this.completeExport(exportId);
    const status = String(completed.export.status ?? "");
    if (status === "partial") {
      if (options.acceptPartial !== true) throw new Error(`Account export ${exportId} is partial. Pass acceptPartial: true to accept it explicitly.`);
      completed = await this.acceptPartialExport(exportId);
    }
    return { export: completed.export, manifest: sanitizeAccountExportManifest(manifest.manifest), chunks: downloadedChunks };
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

export class OpenMatesApiKeys {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<{ apiKeys: ApiKeyRecord[] }> {
    const data = await this.client.get<{ api_keys?: Array<Record<string, unknown>> }>("/v1/sdk/settings/api-keys");
    const masterKey = await this.client.masterKey();
    const apiKeys = [];
    for (const key of data.api_keys ?? []) {
      apiKeys.push(await this.decryptRecord(key, masterKey));
    }
    return { apiKeys };
  }

  async create(options: ApiKeyCreateOptions): Promise<ApiKeyCreateResult> {
    const name = options.name.trim();
    if (!name) throw new OpenMatesConfigError("API key name is required");
    const masterKey = await this.client.masterKey();
    const material = await createApiKeyCryptoMaterial(name, bytesToBase64(masterKey));
    const key = await this.client.request<Record<string, unknown>>("/v1/sdk/settings/api-keys", {
      encrypted_name: material.encryptedName,
      api_key_hash: material.apiKeyHash,
      encrypted_key_prefix: material.encryptedKeyPrefix,
      encrypted_master_key: material.encryptedMasterKey,
      salt: material.saltB64,
      key_iv: material.keyIv,
      full_access: options.fullAccess ?? true,
      scopes: options.scopes ?? {},
      credit_limit: options.creditLimit ?? null,
      expires_at: options.expiresAt ?? null,
    });
    return { apiKey: material.apiKey, key: await this.decryptRecord(key, masterKey) };
  }

  async revoke(id: string): Promise<Record<string, unknown>> {
    return this.client.delete<Record<string, unknown>>(`/v1/sdk/settings/api-keys/${encodeURIComponent(id)}`);
  }

  private async decryptRecord(record: Record<string, unknown>, masterKey: Uint8Array): Promise<ApiKeyRecord> {
    const encryptedName = typeof record.encrypted_name === "string" ? record.encrypted_name : "";
    const encryptedPrefix = typeof record.encrypted_key_prefix === "string" ? record.encrypted_key_prefix : "";
    const name = encryptedName ? await decryptWithAesGcmCombined(encryptedName, masterKey) : null;
    const keyPrefix = encryptedPrefix ? await decryptWithAesGcmCombined(encryptedPrefix, masterKey) : null;
    const lastUsedAt = typeof record.last_used_at === "string" ? record.last_used_at : null;
    return {
      id: String(record.id ?? ""),
      name: name || encryptedName || "Unnamed API key",
      keyPrefix: keyPrefix || encryptedPrefix || "sk-api-...",
      createdAt: typeof record.created_at === "string" ? record.created_at : null,
      expiresAt: typeof record.expires_at === "string" ? record.expires_at : null,
      lastUsedAt,
      lastUsedLabel: lastUsedAt ? new Date(lastUsedAt).toLocaleString() : "Never used",
      fullAccess: typeof record.full_access === "boolean" ? record.full_access : true,
      scopes: (record.scopes && typeof record.scopes === "object" ? record.scopes : {}) as Record<string, unknown>,
      creditLimit: (record.credit_limit && typeof record.credit_limit === "object" ? record.credit_limit : null) as Record<string, unknown> | null,
      pendingDeviceCount: typeof record.pending_device_count === "number" ? record.pending_device_count : 0,
    };
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

export class OpenMatesDesign {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async exportIcon(options: DesignIconExportOptions): Promise<DesignIconExportResult> {
    return exportDesignIcon({
      ...options,
      fetchSvg: async (path) => (await this.client.getRaw(path)).data,
    });
  }
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

  async list(filters: TaskListFilters = {}): Promise<TaskRecord[]> {
    return (await this.listInternal(filters)).map(toPublicTask);
  }

  async listDecrypted(filters: TaskListFilters = {}): Promise<TaskRecord[]> {
    return this.list(filters);
  }

  async show(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return toPublicTask(await this.resolve(id, filters));
  }

  async create(input: TaskPlainCreateOptions): Promise<TaskRecord> {
    const masterKey = await this.client.masterKey();
    const created = await this.createRaw(await buildCreateUserTaskInput(masterKey, input));
    return toPublicTask(await decryptUserTask(created, masterKey));
  }

  async update(id: string, input: TaskPlainUpdateOptions, filters: TaskListFilters = {}): Promise<TaskRecord> {
    let task = await this.resolve(id, filters);
    const masterKey = await this.client.masterKey();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const updated = await this.updateRaw(task.taskId, await buildUpdateUserTaskInput(task, masterKey, input));
        return toPublicTask(await decryptUserTask(updated, masterKey));
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, filters);
      }
    }
    throw new OpenMatesConfigError("Task update retry failed unexpectedly");
  }

  async edit(id: string, input: TaskPlainUpdateOptions, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.update(id, input, filters);
  }

  async start(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    let task = await this.resolve(id, filters);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const started = await this.startAIRaw(task.taskId, {
          version: task.version,
          primary_chat_id: task.primaryChatId ?? undefined,
          linked_project_ids: task.linkedProjectIds,
          plaintext_title: task.title,
          plaintext_description: task.description,
          plaintext_latest_instruction: task.latestInstruction,
        });
        return toPublicTask(await decryptUserTask(started, await this.client.masterKey()));
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, filters);
      }
    }
    throw new OpenMatesConfigError("Task start retry failed unexpectedly");
  }

  async startAI(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.start(id, filters);
  }

  async delete(id: string, options: ConfirmedMutationOptions & { filters?: TaskListFilters } = {}): Promise<{ deleted?: boolean; task_id?: string }> {
    requireConfirmed(options, "Deleting a task");
    let task = await this.resolve(id, options.filters ?? {});
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await this.client.delete<{ deleted?: boolean; task_id?: string }>(`/v1/user-tasks/${encodeURIComponent(task.taskId)}?version=${encodeURIComponent(String(task.version))}`);
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, options.filters ?? {});
      }
    }
    throw new OpenMatesConfigError("Task delete retry failed unexpectedly");
  }

  async done(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.actionById(id, "complete", {}, filters);
  }

  async complete(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.done(id, filters);
  }

  async block(id: string, reason: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.actionById(id, "block", { blocked_reason_code: reason }, filters);
  }

  async unblock(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.actionById(id, "unblock", {}, filters);
  }

  async skip(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.actionById(id, "skip", {}, filters);
  }

  async reorder(id: string, move: Omit<UserTaskReorderInput["moves"][number], "task_id" | "version">, filters: TaskListFilters = {}): Promise<TaskRecord[]> {
    let task = await this.resolve(id, filters);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await this.client.request<{ tasks?: UserTaskRecord[] }>("/v1/user-tasks/reorder", {
          moves: [{ ...move, task_id: task.taskId, version: task.version }],
        });
        return (await decryptUserTasks(response.tasks ?? [], await this.client.masterKey())).map(toPublicTask);
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, filters);
      }
    }
    throw new OpenMatesConfigError("Task reorder retry failed unexpectedly");
  }

  async move(id: string, move: Omit<UserTaskReorderInput["moves"][number], "task_id" | "version">, filters: TaskListFilters = {}): Promise<TaskRecord[]> {
    return this.reorder(id, move, filters);
  }

  private async listRaw(filters: TaskListFilters = {}): Promise<UserTaskRecord[]> {
    const masterKey = filters.labels || filters.tags ? await this.client.masterKey() : undefined;
    const response = await this.client.get<{ tasks?: UserTaskRecord[] }>(withQuery("/v1/user-tasks", {
      status: filters.status,
      chat_id: filters.chatId,
      project_id: filters.projectId,
      label_hash: masterKey ? labelHashes(masterKey, normalizeLabels(filters.labels ?? filters.tags ?? [])) : undefined,
      priority: normalizeTaskPriority(filters.priority),
    }));
    return response.tasks ?? [];
  }

  private async createRaw(input: UserTaskCreateInput): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>("/v1/user-tasks", input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  private async updateRaw(taskId: string, input: UserTaskUpdateInput): Promise<UserTaskRecord> {
    const response = await this.client.patch<{ task?: UserTaskRecord }>(`/v1/user-tasks/${encodeURIComponent(taskId)}`, input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  private async startAIRaw(taskId: string, input: UserTaskStartAIInput): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>(`/v1/user-tasks/${encodeURIComponent(taskId)}/start-ai`, input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  private async listInternal(filters: TaskListFilters): Promise<DecryptedUserTask[]> {
    return decryptUserTasks(await this.listRaw(filters), await this.client.masterKey());
  }

  private async resolve(id: string, filters: TaskListFilters): Promise<DecryptedUserTask> {
    return findTask(await this.listInternal(filters), id);
  }

  private async actionRaw(taskId: string, action: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>(`/v1/user-tasks/${encodeURIComponent(taskId)}/${encodeURIComponent(action)}`, input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  private async actionById(id: string, action: string, patch: Partial<UserTaskActionInput>, filters: TaskListFilters): Promise<TaskRecord> {
    let task = await this.resolve(id, filters);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const updated = await this.actionRaw(task.taskId, action, { version: task.version, ...patch });
        return toPublicTask(await decryptUserTask(updated, await this.client.masterKey()));
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, filters);
      }
    }
    throw new OpenMatesConfigError("Task action retry failed unexpectedly");
  }
}

function toPublicTask(task: DecryptedUserTask): TaskRecord {
  const { encrypted: _encrypted, ...publicTask } = task;
  return publicTask;
}

function isTaskVersionConflict(error: unknown): boolean {
  return error instanceof OpenMatesApiError && error.status === 409 && String(JSON.stringify(error.data)).includes("TASK_VERSION_CONFLICT");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

  async validateYaml(source: string): Promise<Record<string, unknown>> {
    const response = await this.client.request<{ validation?: Record<string, unknown> }>("/v1/workflows/validate", { source });
    if (!response.validation) throw new OpenMatesApiError(500, { detail: "Workflow validation response missing validation" });
    return response.validation;
  }

  async createFromYaml(source: string): Promise<{ workflow: WorkflowDetail; validation: Record<string, unknown> }> {
    const response = await this.client.request<{ workflow?: WorkflowDetail; validation?: Record<string, unknown> }>("/v1/workflows/yaml", { source });
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing workflow" });
    if (!response.validation) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing validation" });
    return { workflow: response.workflow, validation: response.validation };
  }

  async updateFromYaml(workflowId: string, source: string): Promise<{ workflow: WorkflowDetail; validation: Record<string, unknown> }> {
    const response = await this.client.request<{ workflow?: WorkflowDetail; validation?: Record<string, unknown> }>(`/v1/workflows/${encodeURIComponent(workflowId)}/yaml`, { source });
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing workflow" });
    if (!response.validation) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing validation" });
    return { workflow: response.workflow, validation: response.validation };
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
    params: { idempotencyKey: string; mode?: "manual" | "test"; input?: Record<string, unknown> },
  ): Promise<WorkflowRunDetail> {
    if (!params.idempotencyKey.trim()) throw new OpenMatesConfigError("Workflow run requires a stable idempotencyKey");
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
      mode: params.mode ?? "manual",
      input: params.input ?? {},
    }, undefined, { "Idempotency-Key": params.idempotencyKey });
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

  async cancelRun(workflowId: string, runId: string): Promise<WorkflowRunCancellationResult> {
    const result = await this.client.request<WorkflowRunCancellationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/cancel`,
      {},
    );
    if (result.status !== "cancellation_requested" && result.status !== "cancelled") {
      throw new OpenMatesApiError(500, { detail: "Workflow response has invalid cancellation status" });
    }
    return result;
  }

  async respond(workflowId: string, runId: string, stepId: string, input: Record<string, unknown>): Promise<WorkflowRunDetail> {
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/respond`,
      { step_id: stepId, input },
    );
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async upsertTemplateProjection(
    workflowId: string,
    params: WorkflowTemplateProjectionUpsertParams,
  ): Promise<WorkflowTemplateProjectionResult> {
    return this.client.put<WorkflowTemplateProjectionResult>(`/v1/workflows/${encodeURIComponent(workflowId)}/template-projection`, {
      template_id: params.templateId,
      source_version: params.sourceVersion,
      ciphertext: params.ciphertext,
      ciphertext_checksum: params.ciphertextChecksum,
      owner_wrapped_key: params.ownerWrappedKey,
      projection_schema_version: params.projectionSchemaVersion,
    });
  }

  async getPublicTemplateProjection(templateId: string): Promise<PublicWorkflowTemplateProjection> {
    return this.client.getPublic<PublicWorkflowTemplateProjection>(
      `/v1/workflows/template-projections/${encodeURIComponent(templateId)}`,
    );
  }

  async revokeTemplateProjection(workflowId: string): Promise<WorkflowTemplateProjectionRevocationResult> {
    return this.client.request<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/revoke`,
      {},
    );
  }

  async unrevokeTemplateProjection(workflowId: string): Promise<WorkflowTemplateProjectionRevocationResult> {
    return this.client.request<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/unrevoke`,
      {},
    );
  }

  async completeImportedBinding(
    workflowId: string,
    params: WorkflowTemplateBindingCompletionParams,
  ): Promise<WorkflowTemplateBindingCompletionResult> {
    return this.client.request<WorkflowTemplateBindingCompletionResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/binding-requirements/complete`,
      { type: params.type, node_id: params.nodeId },
    );
  }

  async createTemplateShortUrl(params: WorkflowTemplateShortUrlParams): Promise<WorkflowTemplateShortUrlResult> {
    return this.client.request<WorkflowTemplateShortUrlResult>("/v1/share/short-url", {
      token: params.token,
      encrypted_url: params.encryptedUrl,
      content_type: "workflow_template",
      content_id: params.templateId,
      password_protected: params.passwordProtected ?? false,
      ...(params.ttlSeconds !== undefined ? { ttl_seconds: params.ttlSeconds } : {}),
    });
  }

  async revokeShortUrl(token: string): Promise<ShortUrlRevokeResult> {
    return this.client.delete<ShortUrlRevokeResult>(`/v1/share/short-url/${encodeURIComponent(token)}`);
  }

  async importTemplate(payload: WorkflowTemplateImportPayload): Promise<ImportedWorkflowTemplate> {
    const response = await this.client.request<{ workflow?: ImportedWorkflowTemplate }>("/v1/workflows/template-import", payload);
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow template import response missing workflow" });
    return response.workflow;
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
  readonly preview: OpenMatesEmbedPreview;
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
    this.preview = new OpenMatesEmbedPreview(client);
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

export class OpenMatesEmbedPreview {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async start(embedId: string, options: ApplicationPreviewStartOptions): Promise<ApplicationPreviewStartResponse | ApplicationPreviewStatusResponse> {
    const response = await this.client.request<ApplicationPreviewStartResponse>(
      `/v1/applications/${encodeURIComponent(embedId)}/preview/start`,
      {
        chat_id: options.chatId,
        ...(options.sharedContext ? { shared_context: options.sharedContext } : {}),
        ...(options.requestedRuntime ? { requested_runtime: options.requestedRuntime } : {}),
        ...(options.sourceMessageId ? { source_message_id: options.sourceMessageId } : {}),
      },
    );
    return options.wait === true
      ? this.waitForRunning(response.session_id, options.timeoutMs ?? 120_000)
      : response;
  }

  async status(sessionId: string): Promise<ApplicationPreviewStatusResponse> {
    return this.client.get<ApplicationPreviewStatusResponse>(`/v1/applications/preview/${encodeURIComponent(sessionId)}`);
  }

  async open(sessionId: string): Promise<ApplicationPreviewStatusResponse> {
    return this.client.request<ApplicationPreviewStatusResponse>(`/v1/applications/preview/${encodeURIComponent(sessionId)}/open`, {});
  }

  async stop(sessionId: string): Promise<ApplicationPreviewStopResponse> {
    return this.client.request<ApplicationPreviewStopResponse>(`/v1/applications/preview/${encodeURIComponent(sessionId)}/stop`, {});
  }

  private async waitForRunning(sessionId: string, timeoutMs: number): Promise<ApplicationPreviewStatusResponse> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const status = await this.status(sessionId);
      if (["running", "failed", "timeout", "cancelled", "stopped"].includes(status.status)) {
        return status;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new OpenMatesApiError(408, { detail: "Application preview did not reach running state before timeout" });
  }
}

export class OpenMatesConnectedAccounts {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async import(input: { payload: string; passcode: string; teamId?: string | null }): Promise<Record<string, unknown>> {
    if (input.teamId) {
      throw new OpenMatesConfigError("Team connected accounts are not supported yet.");
    }
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

export class OpenMatesTeams {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<Record<string, unknown>[]> {
    const result = await this.client.get<{ teams?: Record<string, unknown>[] }>("/v1/teams");
    return result.teams ?? [];
  }

  async get(teamId: string): Promise<Record<string, unknown>> {
    const result = await this.client.get<{ team?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}`);
    return result.team ?? result;
  }

  async create(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const result = await this.client.request<{ team?: Record<string, unknown> }>("/v1/teams", input);
    return result.team ?? result;
  }

  async update(teamId: string, input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const result = await this.client.patch<{ team?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}`, input);
    return result.team ?? result;
  }

  async delete(teamId: string): Promise<Record<string, unknown>> {
    return this.client.delete<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}`);
  }

  async invite(teamId: string, input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const result = await this.client.request<{ invite?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}/invites`, input);
    return result.invite ?? result;
  }

  async acceptInvite(inviteId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/team-invites/${encodeURIComponent(inviteId)}/accept`, input);
  }

  async declineInvite(inviteId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/team-invites/${encodeURIComponent(inviteId)}/decline`, input);
  }

  async accessRequests(teamId: string, status?: string): Promise<Record<string, unknown>[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    const result = await this.client.get<{ access_requests?: Record<string, unknown>[] }>(`/v1/teams/${encodeURIComponent(teamId)}/access-requests${query}`);
    return result.access_requests ?? [];
  }

  async approveAccess(teamId: string, accessRequestId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    const result = await this.client.request<{ membership?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}/access-requests/${encodeURIComponent(accessRequestId)}/approve`, input);
    return result.membership ?? result;
  }

  async rejectAccess(teamId: string, accessRequestId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}/access-requests/${encodeURIComponent(accessRequestId)}/reject`, input);
  }

  async removeMember(teamId: string, memberUserId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(memberUserId)}/remove`, input);
  }

  async billing(teamId: string): Promise<Record<string, unknown>> {
    const result = await this.client.get<{ billing?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}/billing`);
    return result.billing ?? result;
  }

  async addCredits(teamId: string, input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const result = await this.client.request<{ billing?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}/billing/credits`, input);
    return result.billing ?? result;
  }

  async usage(teamId: string, memberUserId?: string): Promise<Record<string, unknown>[]> {
    const query = memberUserId ? `?member_user_id=${encodeURIComponent(memberUserId)}` : "";
    const result = await this.client.get<{ usage?: Record<string, unknown>[] }>(`/v1/teams/${encodeURIComponent(teamId)}/billing/usage${query}`);
    return result.usage ?? [];
  }

  async memories(teamId: string): Promise<Record<string, unknown>[]> {
    const result = await this.client.get<{ memories?: Record<string, unknown>[] }>(`/v1/teams/${encodeURIComponent(teamId)}/memories`);
    return result.memories ?? [];
  }

  async move(workspaceType: string, objectId: string, teamId: string): Promise<Record<string, unknown>> {
    const routes: Record<string, string> = {
      chat: "chats",
      project: "projects",
      task: "user-tasks",
      plan: "user-plans",
      workflow: "workflows",
    };
    const route = routes[workspaceType];
    if (!route) throw new OpenMatesConfigError("Unsupported team move workspace type");
    return this.client.request<Record<string, unknown>>(
      `/v1/${route}/${encodeURIComponent(objectId)}/move`,
      { team_id: teamId, confirmed: true, moved_at: Math.floor(Date.now() / 1000) },
    );
  }

  async export(teamId: string, input: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}/export`, input);
  }

  async import(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("/v1/teams/import", input);
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
