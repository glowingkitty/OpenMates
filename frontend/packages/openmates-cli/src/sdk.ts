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
import { createHash, createHmac, randomBytes, randomUUID } from "node:crypto";
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
  appendCompressionSummary,
  buildAccountImportMessageBatches,
  COMPRESSION_SUMMARY_CATEGORY,
  parseClaudeImportBuffer,
  parseChatGPTImportBuffer,
  parseGenericImportBuffer,
  parseOpenCodeImportBuffer,
  parseOpenMatesImportBuffer,
  type AccountImportSource,
  type ParsedAccountImport,
  type ParsedImportChat,
} from "./accountImport.js";
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
  buildBlockUserTaskInput,
  buildCreateTaskActivityInput,
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptTaskActivityEntries,
  decryptTaskActivityEntry,
  decryptUserTask,
  decryptUserTasks,
  externalChatLookupHash,
  findTask,
  labelHashes,
  normalizeLabels,
  normalizeTaskPriority,
  type DecryptedUserTask,
  type DecryptedTaskActivityEntry,
  type ExternalChatContext,
  type TaskActivityCreateOptions,
  type TaskCreateOptions,
  type TaskPriorityLevel,
  type TaskUpdateOptions,
} from "./tasksCli.js";
import {
  buildCreatePlanCriterionInput,
  buildCreatePlanLearningInput,
  buildCreatePlanVerificationInput,
  buildCreateUserPlanInput,
  buildUserPlanKeyWrappers,
  buildPlanVerificationEvidenceInput,
  buildUpdatePlanLearningInput,
  buildUpdatePlanVerificationInput,
  buildUpdateUserPlanInput,
  decryptPlanLearning,
  findPlan,
  decryptUserPlan,
  decryptUserPlans,
  planKeyFromRecord,
  serializeAssumptionProofInputs,
  type DecryptedPlanLearning,
  type DecryptedUserPlan,
  type PlanCriterionCreateOptions,
  type PlanLearningCreateOptions,
  type PlanLearningUpdateOptions,
  type PlanVerificationCreateOptions,
  type PlanVerificationEvidenceOptions,
  type PlanVerificationUpdateOptions,
  type PlanCreateOptions,
  type PlanUpdateOptions,
  type UserPlanFlow,
} from "./plansCli.js";
import {
  buildEncryptedObjectSlugMetadata,
  decryptObjectSlug,
  objectSlugMatches,
} from "./objectSlugs.js";
import { hasRememberMessageReference, rewriteRememberMessageReferences } from "./rememberMessage.js";
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
  ProjectItemRecord,
  ProjectRecord,
  UserPlanAssumptionRecord,
  UserPlanCriterionRecord,
  UserPlanLearningCreateTasksInput,
  UserPlanLearningCreateTasksResult,
  UserPlanLearningRecord,
  UserPlanRecord,
  UserPlanReferencePatternRecord,
  UserPlanStatus,
  UserPlanUpdateInput,
  UserPlanVerificationRecord,
  UserTaskActionInput,
  UserTaskActivityRecord,
  UserTaskCreateInput,
  UserTaskReorderInput,
  UserTaskRecord,
  UserTaskStartAIInput,
  UserTaskStatus,
  UserTaskUpdateInput,
} from "./client.js";

export type { ProjectItemRecord } from "./client.js";

const DEFAULT_API_URL = "https://api.openmates.org";
const DEFAULT_RECOVERY_POLL_INTERVAL_MS = 500;
const DEFAULT_RECOVERY_TIMEOUT_MS = 60_000;
const SKILL_TASK_POLL_INTERVAL_MS = 2_000;
const SKILL_TASK_POLL_TIMEOUT_MS = 1_200_000;
const SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS = 500;
const CODE_RUN_POLL_INTERVAL_MS = 1_000;
const CODE_RUN_POLL_TIMEOUT_MS = 1_200_000;
const CODE_RUN_TERMINAL_STATUSES = new Set(["finished", "failed", "timeout", "cancelled"]);
const PROMPT_INJECTION_DISABLED = "disabled";
const CANONICAL_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface TaskStatusResponse {
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed" | string;
  result?: unknown;
  error?: string | null;
}

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

function normalizeOptionalGoal(value: string | undefined): string | null {
  if (value === undefined) return null;
  const trimmed = value.trim();
  if (!trimmed) throw new OpenMatesConfigError("Chat goal must not be empty");
  return trimmed;
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
  slug?: string;
  title?: string;
  goal?: string;
  goalTitle?: string;
  teamId?: string;
}

export interface ChatSendOptions extends ChatCreateOptions {
  history?: Array<Record<string, unknown>> | { messages?: Array<Record<string, unknown>> };
  memoryIds?: string[];
  model?: string;
  recoveryPollIntervalMs?: number;
  recoveryTimeoutMs?: number;
  connectedAccountDirectory?: ConnectedAccountDirectoryEntry[];
  connectedAccountTokenRefInputs?: ConnectedAccountTurnTokenRefInput[];
  senderName?: string;
  teamMemberMentions?: string[];
}

export interface AiModelDefaults {
  default_ai_model_simple?: string | null;
  default_ai_model_complex?: string | null;
  default_ai_model_most_demanding?: string | null;
}

export interface ConnectedAccountDirectoryEntry {
  connected_account_id: string;
  app_id: string;
  provider_id?: string;
  account_ref: string;
  label: string;
  capabilities: string[];
  runtime_modes?: Record<string, string>;
}

export interface ConnectedAccountTurnTokenRefInput {
  connected_account_id: string;
  app_id: string;
  provider_id?: string;
  allowed_actions: string[];
  refresh_token_envelope: Record<string, unknown>;
  action_scope?: Record<string, unknown>;
}

export interface ConnectedAccountSkillRunOptions {
  connectedAccountTokenRefInputs?: ConnectedAccountTurnTokenRefInput[];
  chatId?: string;
  messageId?: string;
  promptInjectionProtection?: boolean;
}

export interface FinanceCheckAccountsInput extends Record<string, unknown> {
  period?: "monthly" | "quarterly" | "yearly" | "custom";
  start_date?: string;
  end_date?: string;
  projection_horizon?: "monthly" | "quarterly" | "yearly";
  connected_account_requests?: Array<Record<string, unknown>>;
  csv_statements?: Array<{ filename: string; content: string }>;
}

export interface ChatListOptions {
  limit?: number;
  offset?: number;
}

export interface ConfirmedMutationOptions {
  confirmed?: boolean;
}

export interface BankTransferOrderOptions {
  emailEncryptionKey?: string;
}

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
}

export interface AccountExportStartOptions {
  domains?: string[];
  filters?: Record<string, unknown>;
  format?: "zip" | "directory";
  includeAdvancedMetadata?: boolean;
}

export interface AccountExportDownloadOptions extends AccountExportStartOptions {
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

export interface AccountImportPreviewOptions {
  source: AccountImportSource;
  chats?: ParsedImportChat[];
  chatCount?: number;
  sourceFingerprints?: string[];
  estimatedTokens?: number;
  estimatedTokensByChat?: number[];
  estimatedBytes?: number;
}

export interface AccountImportCompleteOptions {
  importedChatIds: string[];
  sourceFingerprints: string[];
  recordCounts: Record<string, number>;
  clientFailures?: Array<Record<string, unknown>>;
}

export interface AccountImportRunOptions {
  select?: "default" | "all";
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
  slug?: string;
  encrypted_title?: string;
  encrypted_slug?: string;
  slug_lookup_hash?: string;
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

export interface IdeaBucketSettingsInput {
  processingPrompt?: string;
  processingTimes?: string[] | string;
}

export interface IdeaBucketSettings {
  processingPrompt: string;
  processingTimes: string[];
  entryId?: string;
  itemVersion?: number;
  source: "account" | "default";
}

export interface IdeaBucketProcessOptions {
  now?: boolean;
}

export type IdeaBucketResult = Record<string, unknown>;

const IDEABUCKET_DEFAULT_PROCESSING_PROMPT = `These are my captured ideas for today. Please process them, group related thoughts, suggest next actions, and ask clarifying questions where needed:\n\nIf an idea requires deeper work, create or suggest sub-chats for focused research, planning, todos, docs, or implementation.`;
const IDEABUCKET_APP_ID = "ideabucket";
const IDEABUCKET_SETTINGS_ITEM_TYPE = "processing_settings";
const IDEABUCKET_DEFAULT_PROCESSING_TIMES = ["09:00"];
const IDEABUCKET_PROCESSING_TIME_PATTERN = /^([01]\d|2[0-3]):([0-5]\d)$/;

export type TaskListFilters = { status?: UserTaskStatus; chatId?: string; externalChat?: ExternalChatContext; projectId?: string; planId?: string; teamId?: string; labels?: string[]; tags?: string[]; priority?: TaskPriorityLevel | number | null };
export type TaskBlockOptions = TaskListFilters & { reasonText?: string };
export type TaskPlainCreateOptions = TaskCreateOptions;
export type TaskPlainUpdateOptions = TaskUpdateOptions;
export type TaskRecord = Omit<DecryptedUserTask, "encrypted">;
export type TaskActivityRecord = DecryptedTaskActivityEntry;
export type TaskActivityInput = TaskActivityCreateOptions;
export type PlanRecord = Omit<DecryptedUserPlan, "encrypted">;
export type PlanPlainCreateOptions = PlanCreateOptions;
export type PlanPlainUpdateOptions = PlanUpdateOptions;
export type ProjectPlainCreateOptions = {
  name: string;
  slug?: string;
  description?: string;
  icon?: string;
  color?: string;
  pinned?: boolean;
  archived?: boolean;
};
export type ProjectPlainUpdateOptions = Partial<Omit<ProjectPlainCreateOptions, "pinned"> & { pinned: boolean }>;
export type ProjectContextOptions =
  | { personal: true; teamId?: never }
  | { teamId: string; personal?: never };
export type TeamGeneratedProfileImageOptions = {
  iconName?: string;
  backgroundColor?: string;
};
export type TeamPlainCreateOptions = {
  name: string;
  description?: string | null;
  slug?: string | null;
  teamId?: string;
  profile?: TeamGeneratedProfileImageOptions;
  createdAt?: number;
};
export type ProjectRecordPlain = {
  projectId: string;
  slug: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  pinned: boolean;
  archived: boolean;
  version: number | null;
  createdAt: number | null;
  updatedAt: number | null;
  lastOpenedAt: number | null;
};

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

function appSkillChatContent(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  if (typeof record.content === "string") return record.content;
  if (typeof record.response === "string") return record.response;
  if (typeof record.answer === "string") return record.answer;
  const choices = record.choices;
  if (Array.isArray(choices)) {
    const first = choices[0] as Record<string, unknown> | undefined;
    const message = first?.message as Record<string, unknown> | undefined;
    if (typeof message?.content === "string") return message.content;
    if (typeof first?.text === "string") return first.text;
  }
  return appSkillChatContent(record.data);
}

function sdkOrigin(apiUrl: string): string {
  if (process.env.OPENMATES_APP_URL) return process.env.OPENMATES_APP_URL.replace(/\/$/, "");
  const url = new URL(apiUrl);
  if (url.hostname === "api.dev.openmates.org") return "https://app.dev.openmates.org";
  if (url.hostname === "api.openmates.org") return "https://openmates.org";
  return url.origin;
}

export interface ChatMessageRecord {
  id: string;
  role: string;
  content: string;
  senderName: string | null;
  category: string | null;
  modelName: string | null;
  createdAt: number;
  preview: string;
}

export type ChatMessageWindowDirection = "latest" | "before" | "after" | "around";

export interface ChatMessageWindowCursor {
  created_at: number;
  message_id: string;
}

export interface ChatMessagesOptions {
  chatId: string;
  direction?: ChatMessageWindowDirection;
  limit?: number;
  beforeTimestamp?: number;
  beforeMessageId?: string;
  afterTimestamp?: number;
  afterMessageId?: string;
  anchorMessageId?: string;
  respectCompressionBoundary?: boolean;
  all?: boolean;
}

export interface ChatMessagesResult {
  chat: EncryptedChatMetadata;
  messages: ChatMessageRecord[];
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  startCursor: ChatMessageWindowCursor | null;
  endCursor: ChatMessageWindowCursor | null;
  anchorFound: boolean;
  serverMessageCount: number | null;
}

export interface ChatForkOptions {
  chatId: string;
  fromMessageId: string;
  title?: string;
}

export interface ChatRewindOptions {
  chatId: string;
  toMessageId: string;
  send?: string;
  dryRun?: boolean;
  confirmDestructive?: boolean;
}

export interface ChatRetryOptions {
  chatId: string;
  dryRun?: boolean;
  confirmDestructive?: boolean;
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
  readonly finance: OpenMatesFinance;
  readonly inspirations: OpenMatesInspirations;
  readonly ideabucket: OpenMatesIdeaBucket;
  readonly apiKeys: OpenMatesApiKeys;
  readonly learningMode: OpenMatesLearningMode;
  readonly memories: OpenMatesMemories;
  readonly newChatSuggestions: OpenMatesNewChatSuggestions;
  readonly notifications: OpenMatesNotifications;
  readonly reminders: OpenMatesReminders;
  readonly history: OpenMatesHistory;
  readonly projects: OpenMatesProjects;
  readonly settings: OpenMatesSettings;
  readonly plans: OpenMatesPlans;
  readonly tasks: OpenMatesTasks;
  readonly teams: OpenMatesTeams;
  readonly workflows: OpenMatesWorkflows;
  readonly wikipedia: OpenMatesWikipedia;
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
    this.finance = new OpenMatesFinance(this);
    this.inspirations = new OpenMatesInspirations(this);
    this.ideabucket = new OpenMatesIdeaBucket(this);
    this.apiKeys = new OpenMatesApiKeys(this);
    this.learningMode = new OpenMatesLearningMode(this);
    this.memories = new OpenMatesMemories(this);
    this.newChatSuggestions = new OpenMatesNewChatSuggestions(this);
    this.notifications = new OpenMatesNotifications(this);
    this.reminders = new OpenMatesReminders(this);
    this.history = new OpenMatesHistory(this);
    this.projects = new OpenMatesProjects(this);
    this.settings = new OpenMatesSettings(this);
    this.plans = new OpenMatesPlans(this);
    this.tasks = new OpenMatesTasks(this);
    this.teams = new OpenMatesTeams(this);
    this.workflows = new OpenMatesWorkflows(this);
    this.wikipedia = new OpenMatesWikipedia(this);
  }

  async runAppSkill<T = unknown>(appId: string, skillId: string, input: unknown, options?: AppSkillRunOptions): Promise<T> {
    const response = await this.request<unknown>(`/v1/apps/${appId}/skills/${skillId}`, withAppSkillRunOptions(input, options));
    if (appId === "code" && skillId === "run") {
      return this.resolveCodeRunSkillResponse(response) as Promise<T>;
    }
    return this.resolveAsyncSkillResponse(response) as Promise<T>;
  }

  async runConnectedAccountSkill<T = unknown>(
    appId: string,
    skillId: string,
    input: Record<string, unknown>,
    options: ConnectedAccountSkillRunOptions = {},
  ): Promise<T> {
    return this.request<T>(`/v1/sdk/connected-account-skills/${encodeURIComponent(appId)}/${encodeURIComponent(skillId)}`, {
      input: withAppSkillRunOptions(input, options),
      connected_account_token_ref_inputs: options.connectedAccountTokenRefInputs ?? [],
      chat_id: options.chatId,
      message_id: options.messageId,
    });
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
    if (typeof chat.encrypted_slug === "string") {
      decrypted.slug = await decryptObjectSlug(chat.encrypted_slug, chatKey);
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
    if (!encryptedChatKey) {
      return null;
    }
    const masterKey = await this.getMasterKey();
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
      Origin: sdkOrigin(this.apiUrl),
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

  private async resolveAsyncSkillResponse(responseData: unknown): Promise<unknown> {
    const envelope = responseData as Record<string, unknown>;
    const data = (envelope?.data ?? envelope) as Record<string, unknown>;
    const taskId = typeof data?.task_id === "string" ? data.task_id : null;
    const taskIds = Array.isArray(data?.task_ids)
      ? (data.task_ids as unknown[]).filter((id): id is string => typeof id === "string")
      : [];

    if (taskId) {
      const result = await this.pollTaskUntilComplete(taskId);
      return this.wrapResolvedSkillResult(responseData, result.result);
    }

    if (taskIds.length > 0) {
      const taskResults = await Promise.all(taskIds.map((id) => this.pollTaskUntilComplete(id)));
      return this.wrapResolvedSkillResult(
        responseData,
        this.mergeTaskResults(taskResults.map((task) => task.result)),
      );
    }

    return responseData;
  }

  private async resolveCodeRunSkillResponse(responseData: unknown): Promise<unknown> {
    const envelope = responseData as Record<string, unknown>;
    const data = (envelope?.data ?? envelope) as Record<string, unknown>;
    const results = Array.isArray(data?.results) ? data.results as unknown[] : [];
    if (results.length === 0) return responseData;

    const resolvedResults = await Promise.all(results.map(async (result) => {
      if (!result || typeof result !== "object" || Array.isArray(result)) return result;
      const item = result as Record<string, unknown>;
      const statusPath = typeof item.status_path === "string" ? item.status_path : null;
      if (!statusPath) return item;
      return { ...item, final: await this.pollCodeRunUntilComplete(statusPath) };
    }));

    const resolvedData = { ...data, results: resolvedResults };
    if (envelope && typeof envelope === "object" && "success" in envelope) {
      return { ...envelope, data: resolvedData };
    }
    return resolvedData;
  }

  private async pollCodeRunUntilComplete(statusPath: string): Promise<Record<string, unknown>> {
    const path = this.normalizeCodeRunStatusPath(statusPath);
    const started = Date.now();
    let lastTransientError: string | null = null;
    while (Date.now() - started < CODE_RUN_POLL_TIMEOUT_MS) {
      let response: Response;
      try {
        response = await fetch(`${this.apiUrl}${path}`, {
          method: "GET",
          headers: this.headers(false),
        });
      } catch (error) {
        lastTransientError = error instanceof Error ? error.message : String(error);
        await new Promise((resolve) => setTimeout(resolve, CODE_RUN_POLL_INTERVAL_MS));
        continue;
      }

      if (!response.ok) {
        if (response.status >= SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS) {
          lastTransientError = `HTTP ${response.status}`;
          await new Promise((resolve) => setTimeout(resolve, CODE_RUN_POLL_INTERVAL_MS));
          continue;
        }
        throw new OpenMatesApiError(response.status, await this.safeJson(response));
      }

      lastTransientError = null;
      const status = await this.parseResponse<Record<string, unknown>>(response);
      const value = typeof status.status === "string" ? status.status : "";
      if (CODE_RUN_TERMINAL_STATUSES.has(value)) return status;
      await new Promise((resolve) => setTimeout(resolve, CODE_RUN_POLL_INTERVAL_MS));
    }
    if (lastTransientError) {
      throw new Error(`Code Run did not complete within ${CODE_RUN_POLL_TIMEOUT_MS / 1000}s; last polling error: ${lastTransientError}`);
    }
    throw new Error(`Code Run did not complete within ${CODE_RUN_POLL_TIMEOUT_MS / 1000}s`);
  }

  private normalizeCodeRunStatusPath(statusPath: string): string {
    if (!statusPath.startsWith("/v1/code/run/")) {
      throw new OpenMatesConfigError("Code Run returned an invalid status path.");
    }
    return statusPath;
  }

  private async pollTaskUntilComplete(taskId: string): Promise<TaskStatusResponse> {
    const started = Date.now();
    let lastTransientError: string | null = null;
    while (Date.now() - started < SKILL_TASK_POLL_TIMEOUT_MS) {
      let response: Response;
      try {
        response = await fetch(`${this.apiUrl}/v1/tasks/${encodeURIComponent(taskId)}`, {
          method: "GET",
          headers: this.headers(false),
        });
      } catch (error) {
        lastTransientError = error instanceof Error ? error.message : String(error);
        await new Promise((resolve) => setTimeout(resolve, SKILL_TASK_POLL_INTERVAL_MS));
        continue;
      }

      if (!response.ok) {
        if (response.status >= SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS) {
          lastTransientError = `HTTP ${response.status}`;
          await new Promise((resolve) => setTimeout(resolve, SKILL_TASK_POLL_INTERVAL_MS));
          continue;
        }
        throw new OpenMatesApiError(response.status, await this.safeJson(response));
      }

      lastTransientError = null;
      const task = await this.parseResponse<TaskStatusResponse>(response);
      if (task.status === "completed") return task;
      if (task.status === "failed") throw new Error(task.error ?? "Task failed");
      await new Promise((resolve) => setTimeout(resolve, SKILL_TASK_POLL_INTERVAL_MS));
    }
    if (lastTransientError) {
      throw new Error(`Task ${taskId} did not complete within ${SKILL_TASK_POLL_TIMEOUT_MS / 1000}s; last polling error: ${lastTransientError}`);
    }
    throw new Error(`Task ${taskId} did not complete within ${SKILL_TASK_POLL_TIMEOUT_MS / 1000}s`);
  }

  private async safeJson(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  private wrapResolvedSkillResult(original: unknown, result: unknown): unknown {
    const envelope = original as Record<string, unknown>;
    if (envelope && typeof envelope === "object" && "success" in envelope) {
      return { ...envelope, data: result };
    }
    return result;
  }

  private mergeTaskResults(results: unknown[]): unknown {
    const resultObjects = results.filter(
      (result): result is Record<string, unknown> => result !== null && typeof result === "object",
    );
    const groupedResults = resultObjects.flatMap((result) =>
      Array.isArray(result.results) ? (result.results as unknown[]) : [],
    );
    if (groupedResults.length === 0) return { results };
    const first = resultObjects[0] ?? {};
    return { ...first, results: groupedResults };
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

function appendUniqueProjectId(existing: string[] = [], projectId: string): string[] {
  return existing.includes(projectId) ? existing : [...existing, projectId];
}

function removeProjectId(existing: string[] = [], projectId: string): string[] {
  return existing.filter((id) => id !== projectId);
}

function requireProjectContext(options: Partial<ProjectContextOptions>): { teamId: string | null } {
  const personal = options.personal === true;
  const teamId = typeof options.teamId === "string" && options.teamId.length > 0 ? options.teamId : null;
  if (personal === Boolean(teamId)) throw new OpenMatesConfigError("Projects require explicit Personal or Team context");
  return { teamId };
}

function generatedTeamProfileImageMetadata(input: TeamGeneratedProfileImageOptions = {}): Record<string, unknown> {
  return {
    version: 1,
    mode: "generated",
    icon_name: input.iconName ?? "users",
    icon_color: "#ffffff",
    background_color: input.backgroundColor ?? "#4d73ff",
  };
}

async function buildTeamPlainCreatePayload(client: OpenMates, input: TeamPlainCreateOptions): Promise<Record<string, unknown>> {
  const name = input.name.trim();
  if (!name) throw new OpenMatesConfigError("Team name is required");
  const teamKey = randomBytes(32);
  const now = Math.floor(Date.now() / 1000);
  const createdAt = input.createdAt ?? now;
  const payload = {
    team_id: input.teamId ?? randomUUID(),
    slug: input.slug ?? undefined,
    encrypted_name: await encryptWithAesGcmCombined(name, teamKey),
    encrypted_description: input.description ? await encryptWithAesGcmCombined(input.description, teamKey) : undefined,
    encrypted_profile_image_metadata: await encryptWithAesGcmCombined(JSON.stringify(generatedTeamProfileImageMetadata(input.profile)), teamKey),
    encrypted_team_key: await encryptBytesWithAesGcm(teamKey, await client.masterKey()),
    encrypted_zero_balance: await encryptWithAesGcmCombined("0", teamKey),
    created_at: createdAt,
    updated_at: createdAt,
  };
  return payload;
}

async function teamKeyForRecord(client: OpenMates, team: Record<string, unknown>): Promise<Uint8Array> {
  const encryptedTeamKey = team.encrypted_team_key;
  if (typeof encryptedTeamKey !== "string") throw new OpenMatesConfigError("Team response is missing encrypted Team key");
  const teamKey = await decryptBytesWithAesGcm(encryptedTeamKey, await client.masterKey());
  if (!teamKey) throw new OpenMatesConfigError("Failed to decrypt Team key");
  return teamKey;
}

async function projectWrappingKey(client: OpenMates, options: ProjectContextOptions): Promise<{ teamId: string | null; key: Uint8Array }> {
  const { teamId } = requireProjectContext(options);
  const masterKey = await client.masterKey();
  if (!teamId) return { teamId: null, key: masterKey };
  const response = await client.get<{ team?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}`);
  const encryptedTeamKey = response.team?.encrypted_team_key;
  if (typeof encryptedTeamKey !== "string") throw new OpenMatesConfigError(`Team ${teamId} is missing encrypted team key`);
  const teamKey = await decryptBytesWithAesGcm(encryptedTeamKey, masterKey);
  if (!teamKey) throw new OpenMatesConfigError(`Failed to decrypt Team key for ${teamId}`);
  return { teamId, key: teamKey };
}

async function buildProjectCreatePayload(wrappingKey: Uint8Array, input: ProjectPlainCreateOptions, teamId: string | null = null): Promise<{ payload: ProjectRecord; projectKey: Uint8Array }> {
  const name = input.name.trim();
  if (!name) throw new OpenMatesConfigError("Project name is required");
  const projectKey = randomBytes(32);
  const timestamp = Math.floor(Date.now() / 1000);
  const slugMetadata = await buildEncryptedObjectSlugMetadata({
    value: input.slug ?? name,
    encryptionKey: projectKey,
    lookupKey: wrappingKey,
  });
  const payload: ProjectRecord = {
    project_id: randomUUID(),
    encrypted_project_key: teamId ? null : await encryptBytesWithAesGcm(projectKey, wrappingKey),
    encrypted_slug: slugMetadata.encrypted_slug,
    slug_lookup_hash: slugMetadata.slug_lookup_hash,
    encrypted_name: await encryptWithAesGcmCombined(name, projectKey),
    encrypted_description: await encryptWithAesGcmCombined(input.description ?? "", projectKey),
    encrypted_icon: await encryptWithAesGcmCombined(input.icon ?? "folder", projectKey),
    encrypted_color: await encryptWithAesGcmCombined(input.color ?? "default", projectKey),
    pinned: input.pinned === true,
    archived: input.archived === true,
    created_at: timestamp,
    updated_at: timestamp,
    last_opened_at: timestamp,
    key_wrappers: teamId ? [{
      key_type: "team",
      hashed_team_id: createHash("sha256").update(teamId).digest("hex"),
      team_key_epoch: 1,
      encrypted_project_key: await encryptBytesWithAesGcm(projectKey, wrappingKey),
      wrapper_version: 1,
      created_at: timestamp,
    }] : [],
  };
  return { payload, projectKey };
}

async function decryptSdkProject(record: ProjectRecord, wrappingKey: Uint8Array, teamId: string | null = null): Promise<ProjectRecordPlain> {
  const encryptedProjectKey = teamId
    ? record.key_wrappers?.find((wrapper) => wrapper.key_type === "team"
      && wrapper.hashed_team_id === createHash("sha256").update(teamId).digest("hex")
      && wrapper.team_key_epoch === 1)?.encrypted_project_key
    : record.encrypted_project_key;
  if (typeof encryptedProjectKey !== "string") throw new OpenMatesConfigError(`Project ${record.project_id} is missing encrypted project key`);
  const projectKey = await decryptBytesWithAesGcm(encryptedProjectKey, wrappingKey);
  if (!projectKey) throw new OpenMatesConfigError(`Failed to decrypt Project key for ${record.project_id}`);
  return decryptSdkProjectWithKey(record, projectKey);
}

async function decryptSdkProjectWithKey(record: ProjectRecord, projectKey: Uint8Array): Promise<ProjectRecordPlain> {
  return {
    projectId: record.project_id,
    slug: await decryptObjectSlug(record.encrypted_slug, projectKey),
    name: await decryptOptionalProjectField(record.encrypted_name, projectKey) || "(untitled project)",
    description: await decryptOptionalProjectField(record.encrypted_description, projectKey),
    icon: await decryptOptionalProjectField(record.encrypted_icon, projectKey),
    color: await decryptOptionalProjectField(record.encrypted_color, projectKey),
    pinned: record.pinned === true,
    archived: record.archived === true,
    version: typeof record.version === "number" ? record.version : null,
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    updatedAt: typeof record.updated_at === "number" ? record.updated_at : null,
    lastOpenedAt: typeof record.last_opened_at === "number" ? record.last_opened_at : null,
  };
}

async function decryptOptionalProjectField(value: string | null | undefined, projectKey: Uint8Array): Promise<string> {
  return value ? (await decryptWithAesGcmCombined(value, projectKey)) ?? "" : "";
}

async function buildProjectUpdatePayload(client: OpenMates, projectId: string, input: ProjectPlainUpdateOptions, context: ProjectContextOptions = { personal: true }): Promise<{ project_id: string; patch: Record<string, unknown>; projectKey: Uint8Array }> {
  const { record, projectKey } = await resolveSdkProject(client, projectId, context);
  const patch: Record<string, unknown> = {
    ...(typeof record.version === "number" ? { version: record.version } : {}),
    updated_at: Math.floor(Date.now() / 1000),
  };
  if (input.name !== undefined) patch.encrypted_name = await encryptWithAesGcmCombined(input.name, projectKey);
  if (input.description !== undefined) patch.encrypted_description = await encryptWithAesGcmCombined(input.description, projectKey);
  if (input.icon !== undefined) patch.encrypted_icon = await encryptWithAesGcmCombined(input.icon, projectKey);
  if (input.color !== undefined) patch.encrypted_color = await encryptWithAesGcmCombined(input.color, projectKey);
  if (input.slug !== undefined) {
    const wrappingKey = (await projectWrappingKey(client, context)).key;
    const slugMetadata = await buildEncryptedObjectSlugMetadata({
      value: input.slug,
      encryptionKey: projectKey,
      lookupKey: wrappingKey,
    });
    patch.encrypted_slug = slugMetadata.encrypted_slug;
    patch.slug_lookup_hash = slugMetadata.slug_lookup_hash;
  }
  if (input.pinned !== undefined) patch.pinned = input.pinned;
  if (input.archived !== undefined) patch.archived = input.archived;
  return { project_id: record.project_id, patch, projectKey };
}

function toPublicPlan(plan: DecryptedUserPlan): PlanRecord {
  const { encrypted: _encrypted, ...publicPlan } = plan;
  return publicPlan;
}

function publicTaskAskResponse(response: Record<string, unknown>, tasks: TaskRecord[]): Record<string, unknown> {
  return { ...response, task: tasks.length === 1 ? tasks[0] : null, tasks };
}

function publicPlanAskResponse(response: Record<string, unknown>, plans: PlanRecord[]): Record<string, unknown> {
  return { ...response, plan: plans.length === 1 ? plans[0] : null, plans };
}

function publicProjectAskResponse(response: Record<string, unknown>, projects: ProjectRecordPlain[]): Record<string, unknown> {
  return { ...response, project: projects.length === 1 ? projects[0] : null, projects };
}

async function resolveSdkProject(client: OpenMates, projectId: string, context: ProjectContextOptions = { personal: true }): Promise<{ record: ProjectRecord; projectKey: Uint8Array }> {
  const resolvedProjectId = await resolveSdkProjectId(client, projectId, context);
  const crypto = await projectWrappingKey(client, context);
  const response = await client.get<{ project?: ProjectRecord }>(withQuery(`/v1/projects/${encodeURIComponent(resolvedProjectId)}`, { team_id: crypto.teamId }));
  const record = response.project;
  if (!record) throw new OpenMatesApiError(404, { detail: "Project not found" });
  const teamHash = crypto.teamId ? createHash("sha256").update(crypto.teamId).digest("hex") : null;
  const encryptedProjectKey = crypto.teamId
    ? record.key_wrappers?.find((wrapper) => wrapper.key_type === "team"
      && wrapper.hashed_team_id === teamHash
      && wrapper.team_key_epoch === 1)?.encrypted_project_key
    : record.encrypted_project_key;
  if (typeof encryptedProjectKey !== "string") throw new OpenMatesConfigError("Project response is missing encrypted Project key wrapper");
  const projectKey = await decryptBytesWithAesGcm(encryptedProjectKey, crypto.key);
  if (!projectKey) throw new OpenMatesConfigError("Failed to decrypt Project key");
  return { record, projectKey };
}

async function resolveSdkProjectId(client: OpenMates, projectId: string, context: ProjectContextOptions = { personal: true }): Promise<string> {
  if (CANONICAL_UUID_PATTERN.test(projectId)) return projectId;
  const projects = await client.projects.list({ ...context, includeArchived: true });
  const exact = projects.find((project) => project.projectId === projectId);
  if (exact) return exact.projectId;
  const lower = projectId.toLowerCase();
  const prefixMatches = projectId.length >= 8
    ? projects.filter((project) => project.projectId.toLowerCase().startsWith(lower))
    : [];
  if (prefixMatches.length > 1) throw new OpenMatesConfigError(`Project '${projectId}' is ambiguous. Use the full project ID.`);
  if (prefixMatches.length === 1) return prefixMatches[0].projectId;
  const slugMatches = projects.filter((project) => objectSlugMatches(project.slug, projectId));
  if (slugMatches.length > 1) throw new OpenMatesConfigError(`Project slug '${projectId}' is ambiguous. Use the full project ID.`);
  if (slugMatches.length === 1) return slugMatches[0].projectId;
  const normalizedName = projectId.trim().toLowerCase().replace(/\s+/g, " ");
  const nameMatches = projects.filter((project) => project.name.trim().toLowerCase().replace(/\s+/g, " ") === normalizedName);
  if (nameMatches.length > 1) throw new OpenMatesConfigError(`Project '${projectId}' is ambiguous. Use the full project ID.`);
  if (nameMatches.length === 1) return nameMatches[0].projectId;
  throw new OpenMatesConfigError(`Project '${projectId}' was not found.`);
}

async function resolveSdkChatKey(client: OpenMates, chatId: string): Promise<Uint8Array> {
  const resolvedChatId = await resolveSdkChatId(client, chatId);
  const payload = await client.get<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(resolvedChatId)}`);
  const chat = payload.chat as EncryptedChatMetadata | undefined;
  if (!chat) throw new OpenMatesConfigError("Saved chat payload did not include chat metadata");
  const hashedChatId = createHash("sha256").update(chat.id).digest("hex");
  const wrappers = Array.isArray(payload.chat_key_wrappers)
    ? payload.chat_key_wrappers as ChatKeyWrapperRecord[]
    : Array.isArray(chat.chat_key_wrappers)
      ? chat.chat_key_wrappers
      : [];
  const wrapper = wrappers.find(
    (entry) => entry.key_type === "master" && entry.hashed_chat_id === hashedChatId && typeof entry.encrypted_chat_key === "string",
  );
  const encryptedChatKey = typeof wrapper?.encrypted_chat_key === "string"
    ? wrapper.encrypted_chat_key
    : typeof chat.encrypted_chat_key === "string"
      ? chat.encrypted_chat_key
      : null;
  if (!encryptedChatKey) throw new OpenMatesConfigError("Saved chat does not include encrypted chat key material");
  const chatKey = await decryptBytesWithAesGcm(encryptedChatKey, await client.masterKey());
  if (!chatKey) throw new OpenMatesConfigError("Unable to decrypt saved chat key material");
  return chatKey;
}

async function resolveSdkChatId(client: OpenMates, chatId: string): Promise<string> {
  if (CANONICAL_UUID_PATTERN.test(chatId)) return chatId;
  const chats = await client.chats.list({ limit: 0 });
  const lower = chatId.toLowerCase();
  const exactId = chats.find((chat) => chat.id === chatId);
  if (exactId) return exactId.id;
  const prefixMatches = chatId.length >= 8 ? chats.filter((chat) => chat.id.toLowerCase().startsWith(lower)) : [];
  if (prefixMatches.length > 1) throw new OpenMatesConfigError(`Chat '${chatId}' is ambiguous. Use the full chat ID.`);
  if (prefixMatches.length === 1) return prefixMatches[0].id;
  const slugMatches = chats.filter((chat) => objectSlugMatches(chat.slug, chatId));
  if (slugMatches.length > 1) throw new OpenMatesConfigError(`Chat slug '${chatId}' is ambiguous. Use the full chat ID.`);
  if (slugMatches.length === 1) return slugMatches[0].id;
  const normalizedTitle = chatId.trim().toLowerCase().replace(/\s+/g, " ");
  const titleMatches = chats.filter((chat) => typeof chat.title === "string" && chat.title.trim().toLowerCase().replace(/\s+/g, " ") === normalizedTitle);
  if (titleMatches.length > 1) throw new OpenMatesConfigError(`Chat '${chatId}' is ambiguous. Use the full chat ID.`);
  if (titleMatches.length === 1) return titleMatches[0].id;
  throw new OpenMatesConfigError(`Chat '${chatId}' was not found.`);
}

function isSdkChatNotFound(error: unknown): boolean {
  return error instanceof OpenMatesApiError && error.status === 404;
}

async function resolveSdkPlanId(client: OpenMates, planId: string): Promise<string> {
  if (CANONICAL_UUID_PATTERN.test(planId)) return planId;
  const plans = await decryptUserPlans(await listSdkRawPlans(client, { activeOnly: false }), await client.masterKey());
  return findPlan(plans, planId).planId;
}

async function listSdkRawPlans(
  client: OpenMates,
  filters: { status?: UserPlanStatus; chatId?: string; projectId?: string; activeOnly?: boolean } = {},
): Promise<UserPlanRecord[]> {
  const resolvedChatId = typeof filters.chatId === "string" && filters.chatId ? await resolveSdkChatId(client, filters.chatId) : filters.chatId;
  const resolvedProjectId = typeof filters.projectId === "string" && filters.projectId ? await resolveSdkProjectId(client, filters.projectId) : filters.projectId;
  const response = await client.get<{ plans?: UserPlanRecord[] }>(withQuery("/v1/user-plans", {
    status: filters.status,
    chat_id: resolvedChatId,
    project_id: resolvedProjectId,
    active_only: filters.activeOnly,
  }));
  return response.plans ?? [];
}

async function resolveSdkPlanProjectLinks(client: OpenMates, projectIds: string[] | undefined): Promise<{ linkedProjectIds?: string[]; linkedProjectKeys?: Array<{ projectId: string; projectKey: Uint8Array }> }> {
  if (projectIds === undefined) return {};
  const entries = await Promise.all(projectIds.map(async (projectId) => {
    const { record, projectKey } = await resolveSdkProject(client, projectId);
    return { projectId: record.project_id, projectKey };
  }));
  return {
    linkedProjectIds: entries.map((entry) => entry.projectId),
    linkedProjectKeys: entries,
  };
}

async function canonicalizeTaskCreateInput(client: OpenMates, input: TaskPlainCreateOptions): Promise<TaskPlainCreateOptions> {
  return {
    ...input,
    chatId: typeof input.chatId === "string" && input.chatId ? await resolveSdkChatId(client, input.chatId) : input.chatId,
    projectIds: input.projectIds ? await Promise.all(input.projectIds.map((projectId) => resolveSdkProjectId(client, projectId))) : input.projectIds,
    planId: typeof input.planId === "string" && input.planId ? await resolveSdkPlanId(client, input.planId) : input.planId,
  };
}

async function canonicalizeTaskUpdateInput(client: OpenMates, input: TaskPlainUpdateOptions, teamId?: string): Promise<TaskPlainUpdateOptions> {
  return {
    ...input,
    chatId: typeof input.chatId === "string" && input.chatId ? await resolveSdkChatId(client, input.chatId) : input.chatId,
    projectIds: input.projectIds ? await Promise.all(input.projectIds.map((projectId) => resolveSdkProjectId(client, projectId, teamId ? { teamId } : { personal: true }))) : input.projectIds,
    planId: typeof input.planId === "string" && input.planId && !teamId ? await resolveSdkPlanId(client, input.planId) : input.planId,
  };
}

async function canonicalizeTaskFilters(client: OpenMates, filters: TaskListFilters = {}): Promise<TaskListFilters> {
  return {
    ...filters,
    chatId: typeof filters.chatId === "string" && filters.chatId ? await resolveSdkChatId(client, filters.chatId) : filters.chatId,
    projectId: typeof filters.projectId === "string" && filters.projectId ? await resolveSdkProjectId(client, filters.projectId, filters.teamId ? { teamId: filters.teamId } : { personal: true }) : filters.projectId,
    planId: typeof filters.planId === "string" && filters.planId && !filters.teamId ? await resolveSdkPlanId(client, filters.planId) : filters.planId,
  };
}

async function buildSdkPlanKeyWrappers(
  client: OpenMates,
  planRecord: UserPlanRecord,
  input: { primaryChatId?: string | null; linkedProjectIds?: string[]; createdAt?: number },
): Promise<Array<Record<string, unknown>>> {
  const masterKey = await client.masterKey();
  const planKey = await planKeyFromRecord(planRecord, masterKey);
  const projectLinks = await resolveSdkPlanProjectLinks(client, input.linkedProjectIds ?? []);
  const linkedProjectIds = projectLinks.linkedProjectIds ?? [];
  return buildUserPlanKeyWrappers({
    planKey,
    masterKey,
    createdAt: input.createdAt ?? Math.floor(Date.now() / 1000),
    primaryChatId: input.primaryChatId ?? null,
    primaryChatKey: input.primaryChatId ? await resolveSdkChatKey(client, input.primaryChatId) : null,
    linkedProjectIds,
    linkedProjectKeys: projectLinks.linkedProjectKeys,
  });
}

async function decryptOptionalPlanField(value: string | null | undefined, planKey: Uint8Array): Promise<string> {
  return value ? (await decryptWithAesGcmCombined(value, planKey)) ?? "" : "";
}

function withoutEncryptedLearning(learning: DecryptedPlanLearning): PlanLearningRecord {
  const { encrypted: _encrypted, ...publicLearning } = learning;
  return publicLearning;
}

async function toPublicPlanCriterion(record: UserPlanCriterionRecord, planKey: Uint8Array): Promise<PlanCriterionRecord> {
  return {
    criterionId: record.criterion_id,
    text: await decryptOptionalPlanField(record.encrypted_text, planKey),
    type: record.type,
    status: record.status,
    required: record.required,
    linkedTaskIds: record.linked_task_ids ?? [],
    verificationIds: record.verification_ids ?? [],
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    updatedAt: typeof record.updated_at === "number" ? record.updated_at : null,
  };
}

async function toPublicPlanAssumption(record: UserPlanAssumptionRecord, planKey: Uint8Array): Promise<PlanAssumptionRecord> {
  return {
    assumptionId: record.assumption_id,
    text: await decryptOptionalPlanField(record.encrypted_text, planKey),
    category: record.category,
    status: record.status,
    requiredBefore: record.required_before,
    linkedSubChatId: record.linked_sub_chat_id ?? null,
    linkedTaskId: record.linked_task_id ?? null,
    linkedCriterionIds: record.linked_criterion_ids ?? [],
    sourceCount: record.source_count,
    correctedText: await decryptOptionalPlanField(record.encrypted_corrected_text, planKey),
    evidenceSummary: await decryptOptionalPlanField(record.encrypted_evidence_summary, planKey),
    blockerReason: await decryptOptionalPlanField(record.encrypted_blocker_reason, planKey),
    waiverReason: await decryptOptionalPlanField(record.encrypted_waiver_reason, planKey),
    sources: await decryptOptionalPlanField(record.encrypted_sources, planKey),
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    updatedAt: typeof record.updated_at === "number" ? record.updated_at : null,
  };
}

async function toPublicPlanReferencePattern(record: UserPlanReferencePatternRecord, planKey: Uint8Array): Promise<PlanReferencePatternRecord> {
  return {
    patternId: record.pattern_id,
    title: await decryptOptionalPlanField(record.encrypted_title, planKey) || "(untitled pattern)",
    description: await decryptOptionalPlanField(record.encrypted_description, planKey),
    category: record.category,
    status: record.status,
    requiredBefore: record.required_before,
    sourceCount: record.source_count,
    linkedTaskIds: record.linked_task_ids ?? [],
    linkedCheckIds: record.linked_check_ids ?? [],
    sources: await decryptOptionalPlanField(record.encrypted_sources, planKey),
    matchRules: await decryptOptionalPlanField(record.encrypted_match_rules, planKey),
    antiPatterns: await decryptOptionalPlanField(record.encrypted_anti_patterns, planKey),
    evidenceSummary: await decryptOptionalPlanField(record.encrypted_evidence_summary, planKey),
    waiverReason: await decryptOptionalPlanField(record.encrypted_waiver_reason, planKey),
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    updatedAt: typeof record.updated_at === "number" ? record.updated_at : null,
  };
}

async function toPublicPlanVerification(record: UserPlanVerificationRecord, planKey: Uint8Array): Promise<PlanVerificationRecord> {
  return {
    verificationId: record.verification_id,
    kind: record.kind,
    phase: record.phase,
    status: record.status,
    requiredForDone: record.required_for_done,
    covers: record.covers ?? [],
    sourceHash: record.source_hash ?? null,
    threshold: record.threshold ?? null,
    score: record.score ?? null,
    confidence: record.confidence ?? null,
    linkedTaskId: record.linked_task_id ?? null,
    runId: record.run_id ?? null,
    lifecycleStatus: record.lifecycle_status ?? null,
    linkedSubChatId: record.linked_sub_chat_id ?? null,
    sourceEmbedId: record.source_embed_id ?? null,
    runnerKind: record.runner_kind ?? null,
    description: await decryptOptionalPlanField(record.encrypted_description, planKey),
    command: await decryptOptionalPlanField(record.encrypted_command, planKey),
    evaluationPrompt: await decryptOptionalPlanField(record.encrypted_evaluation_prompt, planKey),
    evaluatorInstructions: await decryptOptionalPlanField(record.encrypted_evaluator_instructions, planKey),
    expectedResult: await decryptOptionalPlanField(record.encrypted_expected_result, planKey),
    sourcePath: await decryptOptionalPlanField(record.encrypted_source_path, planKey),
    redPhaseReason: await decryptOptionalPlanField(record.encrypted_red_phase_reason, planKey),
    resultSummary: await decryptOptionalPlanField(record.encrypted_result_summary, planKey),
    requiredFixes: await decryptOptionalPlanField(record.encrypted_required_fixes, planKey),
    createdAt: typeof record.created_at === "number" ? record.created_at : null,
    updatedAt: typeof record.updated_at === "number" ? record.updated_at : null,
  };
}

async function buildPlanAssumptionCreateInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanAssumptionCreateOptions): Promise<UserPlanAssumptionRecord> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const timestamp = Math.floor(Date.now() / 1000);
  return {
    assumption_id: input.assumptionId ?? randomUUID(),
    encrypted_text: await encryptWithAesGcmCombined(input.text, planKey),
    category: input.category,
    status: input.status,
    required_before: input.requiredBefore,
    linked_sub_chat_id: input.linkedSubChatId,
    linked_task_id: input.linkedTaskId,
    linked_criterion_ids: input.linkedCriterionIds,
    source_count: input.sourceCount,
    encrypted_corrected_text: input.correctedText !== undefined ? await encryptWithAesGcmCombined(input.correctedText, planKey) : undefined,
    encrypted_evidence_summary: input.evidenceSummary !== undefined ? await encryptWithAesGcmCombined(input.evidenceSummary, planKey) : undefined,
    encrypted_blocker_reason: input.blockerReason !== undefined ? await encryptWithAesGcmCombined(input.blockerReason, planKey) : undefined,
    encrypted_waiver_reason: input.waiverReason !== undefined ? await encryptWithAesGcmCombined(input.waiverReason, planKey) : undefined,
    encrypted_sources: input.proofInputs !== undefined
      ? await encryptWithAesGcmCombined(serializeAssumptionProofInputs(input.proofInputs), planKey)
      : input.sources !== undefined ? await encryptWithAesGcmCombined(input.sources, planKey) : undefined,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

async function buildPlanAssumptionUpdateInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanAssumptionUpdateOptions): Promise<Partial<UserPlanAssumptionRecord>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: Partial<UserPlanAssumptionRecord> = { updated_at: Math.floor(Date.now() / 1000) };
  if (input.category !== undefined) patch.category = input.category;
  if (input.status !== undefined) patch.status = input.status;
  if (input.requiredBefore !== undefined) patch.required_before = input.requiredBefore;
  if (input.linkedSubChatId !== undefined) patch.linked_sub_chat_id = input.linkedSubChatId;
  if (input.linkedTaskId !== undefined) patch.linked_task_id = input.linkedTaskId;
  if (input.sourceCount !== undefined) patch.source_count = input.sourceCount;
  if (input.correctedText !== undefined) patch.encrypted_corrected_text = await encryptWithAesGcmCombined(input.correctedText, planKey);
  if (input.evidenceSummary !== undefined) patch.encrypted_evidence_summary = await encryptWithAesGcmCombined(input.evidenceSummary, planKey);
  if (input.blockerReason !== undefined) patch.encrypted_blocker_reason = await encryptWithAesGcmCombined(input.blockerReason, planKey);
  if (input.waiverReason !== undefined) patch.encrypted_waiver_reason = await encryptWithAesGcmCombined(input.waiverReason, planKey);
  if (input.proofInputs !== undefined) patch.encrypted_sources = await encryptWithAesGcmCombined(serializeAssumptionProofInputs(input.proofInputs), planKey);
  else if (input.sources !== undefined) patch.encrypted_sources = await encryptWithAesGcmCombined(input.sources, planKey);
  return patch;
}

async function buildPlanReferencePatternCreateInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanReferencePatternCreateOptions): Promise<UserPlanReferencePatternRecord> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const timestamp = Math.floor(Date.now() / 1000);
  return {
    pattern_id: input.patternId ?? randomUUID(),
    encrypted_title: await encryptWithAesGcmCombined(input.title, planKey),
    encrypted_description: input.description !== undefined ? await encryptWithAesGcmCombined(input.description, planKey) : undefined,
    category: input.category,
    status: input.status,
    required_before: input.requiredBefore,
    source_count: input.sourceCount,
    linked_task_ids: input.linkedTaskIds,
    linked_check_ids: input.linkedCheckIds,
    encrypted_sources: input.sources !== undefined ? await encryptWithAesGcmCombined(input.sources, planKey) : undefined,
    encrypted_match_rules: input.matchRules !== undefined ? await encryptWithAesGcmCombined(input.matchRules, planKey) : undefined,
    encrypted_anti_patterns: input.antiPatterns !== undefined ? await encryptWithAesGcmCombined(input.antiPatterns, planKey) : undefined,
    encrypted_evidence_summary: input.evidenceSummary !== undefined ? await encryptWithAesGcmCombined(input.evidenceSummary, planKey) : undefined,
    encrypted_waiver_reason: input.waiverReason !== undefined ? await encryptWithAesGcmCombined(input.waiverReason, planKey) : undefined,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

async function buildPlanReferencePatternUpdateInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanReferencePatternUpdateOptions): Promise<Partial<UserPlanReferencePatternRecord>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: Partial<UserPlanReferencePatternRecord> = { updated_at: Math.floor(Date.now() / 1000) };
  if (input.description !== undefined) patch.encrypted_description = await encryptWithAesGcmCombined(input.description, planKey);
  if (input.category !== undefined) patch.category = input.category;
  if (input.status !== undefined) patch.status = input.status;
  if (input.requiredBefore !== undefined) patch.required_before = input.requiredBefore;
  if (input.sourceCount !== undefined) patch.source_count = input.sourceCount;
  if (input.linkedTaskIds !== undefined) patch.linked_task_ids = input.linkedTaskIds;
  if (input.linkedCheckIds !== undefined) patch.linked_check_ids = input.linkedCheckIds;
  if (input.sources !== undefined) patch.encrypted_sources = await encryptWithAesGcmCombined(input.sources, planKey);
  if (input.matchRules !== undefined) patch.encrypted_match_rules = await encryptWithAesGcmCombined(input.matchRules, planKey);
  if (input.antiPatterns !== undefined) patch.encrypted_anti_patterns = await encryptWithAesGcmCombined(input.antiPatterns, planKey);
  if (input.evidenceSummary !== undefined) patch.encrypted_evidence_summary = await encryptWithAesGcmCombined(input.evidenceSummary, planKey);
  if (input.waiverReason !== undefined) patch.encrypted_waiver_reason = await encryptWithAesGcmCombined(input.waiverReason, planKey);
  return patch;
}

async function createSdkProjectItem(
  client: OpenMates,
  projectId: string,
  projectKey: Uint8Array,
  input: {
    itemType: "embed" | "chat" | "workflow";
    targetId: string;
    displayName: string;
    folder?: string;
    metadata?: Record<string, unknown>;
  },
): Promise<ProjectItemRecord> {
  const timestamp = Math.floor(Date.now() / 1000);
  const response = await client.request<{ item?: ProjectItemRecord }>(`/v1/projects/${encodeURIComponent(projectId)}/items`, {
    project_item_id: randomUUID(),
    folder_id: input.folder ?? null,
    item_type: input.itemType,
    target_id: input.targetId,
    target_id_encrypted: await encryptWithAesGcmCombined(input.targetId, projectKey),
    encrypted_display_name: await encryptWithAesGcmCombined(input.displayName, projectKey),
    encrypted_note: await encryptWithAesGcmCombined("", projectKey),
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify(input.metadata ?? {}), projectKey),
    created_at: timestamp,
    updated_at: timestamp,
    position: timestamp,
  });
  if (!response.item) throw new OpenMatesApiError(500, { detail: "Project item response missing item" });
  return response.item;
}

async function deleteSdkProjectItemByTarget(client: OpenMates, projectId: string, itemType: "embed" | "chat" | "workflow", targetId: string): Promise<{ deleted: boolean; deletedCount: number }> {
  const response = await client.delete<{ deleted?: boolean; deleted_count?: number }>(withQuery(`/v1/projects/${encodeURIComponent(projectId)}/items`, {
    item_type: itemType,
    target_id: targetId,
  }));
  return { deleted: response.deleted === true, deletedCount: Number(response.deleted_count ?? 0) };
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

function rememberableMessagesFromRecords(records: Array<Record<string, unknown>>): ChatMessageRecord[] {
  return records
    .map((record) => {
      const id = stringField(record.id) ?? stringField(record.client_message_id) ?? stringField(record.message_id);
      const content = stringField(record.content);
      if (!id || content === null) return null;
      return {
        id,
        role: stringField(record.role) ?? "unknown",
        content,
        senderName: stringField(record.senderName) ?? stringField(record.sender_name),
        category: stringField(record.category),
        modelName: stringField(record.modelName) ?? stringField(record.model_name),
        createdAt: numericField(record.created_at) ?? 0,
        preview: content.replace(/\s+/g, " ").trim().slice(0, 120),
      } satisfies ChatMessageRecord;
    })
    .filter((message): message is ChatMessageRecord => message !== null);
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
      const haystack = [chat.title, chat.chat_summary, chat.category, chat.slug, chat.id]
        .filter((value): value is string => typeof value === "string")
        .join("\n")
        .toLowerCase();
      return haystack.includes(normalized);
    });
    return matches.slice(offset, limit === 0 ? undefined : offset + limit);
  }

  async load(chatId: string): Promise<Record<string, unknown>> {
    const resolvedChatId = CANONICAL_UUID_PATTERN.test(chatId) ? chatId : await resolveSdkChatId(this.client, chatId);
    try {
      const payload = await this.client.get<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(resolvedChatId)}`);
      return this.client.decryptLoadedChatPayload(payload);
    } catch (error) {
      if (!isSdkChatNotFound(error)) throw error;
      if (resolvedChatId === chatId) throw error;
      throw new OpenMatesConfigError(`Chat '${chatId}' was not found.`);
    }
  }

  async addToProject(chatId: string, projectId: string, options: { folder?: string } = {}): Promise<ProjectItemRecord> {
    const { record, projectKey } = await resolveSdkProject(this.client, projectId);
    const loaded = await this.load(chatId);
    const chat = loaded.chat as EncryptedChatMetadata | undefined;
    const targetId = String(chat?.id ?? chatId);
    const displayName = typeof chat?.title === "string" ? chat.title : targetId;
    return createSdkProjectItem(this.client, record.project_id, projectKey, {
      itemType: "chat",
      targetId,
      displayName,
      folder: options.folder,
      metadata: { storage: "save_only_in_openmates", source: "sdk_add_to_project" },
    });
  }

  async removeFromProject(chatId: string, projectId: string): Promise<{ deleted: boolean; deletedCount: number }> {
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId);
    const loaded = await this.load(chatId);
    const chat = loaded.chat as EncryptedChatMetadata | undefined;
    return deleteSdkProjectItemByTarget(this.client, resolvedProjectId, "chat", String(chat?.id ?? chatId));
  }

  async messages(options: ChatMessagesOptions): Promise<ChatMessagesResult> {
    if (options.all === true) {
      const loaded = await this.load(options.chatId);
      const chat = loaded.chat as EncryptedChatMetadata | undefined;
      if (!chat) {
        throw new OpenMatesConfigError("Saved chat payload did not include chat metadata");
      }
      const messages = normalizeLoadedChatMessages(loaded);
      return {
        chat,
        messages,
        hasMoreBefore: false,
        hasMoreAfter: false,
        startCursor: messages[0] ? { created_at: messages[0].createdAt, message_id: messages[0].id } : null,
        endCursor: messages[messages.length - 1] ? { created_at: messages[messages.length - 1].createdAt, message_id: messages[messages.length - 1].id } : null,
        anchorFound: true,
        serverMessageCount: messages.length,
      };
    }
    const messageWindowPath = (chatId: string) => withQuery(
      `/v1/sdk/chats/${encodeURIComponent(chatId)}/messages`,
      {
        direction: options.direction ?? "latest",
        limit: options.limit ?? 30,
        before_timestamp: options.beforeTimestamp,
        before_message_id: options.beforeMessageId,
        after_timestamp: options.afterTimestamp,
        after_message_id: options.afterMessageId,
        anchor_message_id: options.anchorMessageId,
        respect_compression_boundary: options.respectCompressionBoundary === false ? false : undefined,
      },
    );
    let payload: Record<string, unknown>;
    try {
      payload = await this.client.get<Record<string, unknown>>(messageWindowPath(options.chatId));
    } catch (error) {
      if (!isSdkChatNotFound(error)) throw error;
      const resolvedChatId = await resolveSdkChatId(this.client, options.chatId);
      payload = await this.client.get<Record<string, unknown>>(messageWindowPath(resolvedChatId));
    }
    const loaded = await this.client.decryptLoadedChatPayload(payload);
    const chat = loaded.chat as EncryptedChatMetadata | undefined;
    if (!chat) {
      throw new OpenMatesConfigError("Saved chat payload did not include chat metadata");
    }
    return {
      chat,
      messages: normalizeLoadedChatMessages(loaded),
      hasMoreBefore: loaded.has_more_before === true,
      hasMoreAfter: loaded.has_more_after === true,
      startCursor: (loaded.start_cursor as ChatMessageWindowCursor | null | undefined) ?? null,
      endCursor: (loaded.end_cursor as ChatMessageWindowCursor | null | undefined) ?? null,
      anchorFound: loaded.anchor_found !== false,
      serverMessageCount: typeof loaded.server_message_count === "number" ? loaded.server_message_count : null,
    };
  }

  async *messagePages(options: ChatMessagesOptions): AsyncGenerator<ChatMessagesResult> {
    let direction: ChatMessageWindowDirection = options.direction ?? "latest";
    let beforeTimestamp = options.beforeTimestamp;
    let beforeMessageId = options.beforeMessageId;
    while (true) {
      const page = await this.messages({
        ...options,
        all: false,
        direction,
        beforeTimestamp,
        beforeMessageId,
      });
      yield page;
      if (!page.hasMoreBefore || !page.startCursor) break;
      direction = "before";
      beforeTimestamp = page.startCursor.created_at;
      beforeMessageId = page.startCursor.message_id;
    }
  }

  async fork(options: ChatForkOptions): Promise<Record<string, unknown>> {
    const { loaded, chat } = await this.loadPersonalEncryptedChat(options.chatId);
    const messages = normalizeLoadedChatMessages(loaded);
    const boundaryIndex = findMessageBoundaryIndex(messages, options.fromMessageId);
    const sourceSlice = messages.slice(0, boundaryIndex + 1);
    const masterKey = await this.client.masterKey();
    const newChatId = randomUUID();
    const newChatKey = new Uint8Array(randomBytes(32));
    const now = Math.floor(Date.now() / 1000);
    const idMap = new Map<string, string>();
    const encryptedMessages = [] as Record<string, unknown>[];
    for (const message of sourceSlice) {
      const newMessageId = randomUUID();
      idMap.set(message.id, newMessageId);
      const raw = message.raw;
      const encryptedMessage: Record<string, unknown> = {
        client_message_id: newMessageId,
        message_id: newMessageId,
        chat_id: newChatId,
        encrypted_content: await encryptWithAesGcmCombined(message.content, newChatKey),
        encrypted_sender_name: await encryptWithAesGcmCombined(message.senderName ?? defaultSenderName(message.role), newChatKey),
        role: message.role,
        created_at: message.createdAt || now,
        updated_at: numericField(raw.updated_at) ?? (message.createdAt || now),
      };
      const oldUserMessageId = stringField(raw.user_message_id);
      if (oldUserMessageId && idMap.has(oldUserMessageId)) {
        encryptedMessage.user_message_id = idMap.get(oldUserMessageId);
      }
      if (message.category) {
        encryptedMessage.encrypted_category = await encryptWithAesGcmCombined(message.category, newChatKey);
      }
      if (message.modelName) {
        encryptedMessage.encrypted_model_name = await encryptWithAesGcmCombined(message.modelName, newChatKey);
      }
      encryptedMessages.push(encryptedMessage);
    }
    const slugMetadata = await buildEncryptedObjectSlugMetadata({
      value: options.title ?? `fork-of-${String(chat.slug ?? chat.title ?? chat.id)}`,
      encryptionKey: newChatKey,
      lookupKey: masterKey,
    });
    return this.client.request<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(chat.id)}/fork`, {
      protocol_version: 1,
      from_message_id: options.fromMessageId,
      new_chat_id: newChatId,
      expected_source_messages_v: Number(chat.messages_v ?? messages.length),
      encrypted_chat_metadata: {
        id: newChatId,
        encrypted_title: await encryptWithAesGcmCombined(options.title ?? `Fork of ${String(chat.title ?? chat.id)}`, newChatKey),
        encrypted_slug: slugMetadata.encrypted_slug,
        slug_lookup_hash: slugMetadata.slug_lookup_hash,
        encrypted_chat_key: await encryptBytesWithAesGcm(newChatKey, masterKey),
        created_at: now,
        updated_at: now,
      },
      encrypted_messages: encryptedMessages,
    });
  }

  async rewind(options: ChatRewindOptions): Promise<Record<string, unknown>> {
    if (!options.dryRun) {
      requireConfirmed({ confirmed: options.confirmDestructive === true }, "Rewinding a chat");
    }
    const { loaded, chat } = await this.loadPersonalEncryptedChat(options.chatId);
    const messages = normalizeLoadedChatMessages(loaded);
    findMessageBoundaryIndex(messages, options.toMessageId);
    const rewind = await this.client.request<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(chat.id)}/rewind`, {
      protocol_version: 1,
      to_message_id: options.toMessageId,
      expected_messages_v: Number(chat.messages_v ?? messages.length),
      dry_run: options.dryRun === true,
      confirm_destructive: options.confirmDestructive === true,
    });
    if (options.send && options.dryRun !== true) {
      const response = await this.send(options.send, { saveToAccount: true, chatId: chat.id });
      return { ...rewind, response };
    }
    return rewind;
  }

  async retry(options: ChatRetryOptions): Promise<Record<string, unknown>> {
    if (!options.dryRun) {
      requireConfirmed({ confirmed: options.confirmDestructive === true }, "Retrying a chat");
    }
    const { loaded } = await this.loadPersonalEncryptedChat(options.chatId);
    const messages = normalizeLoadedChatMessages(loaded);
    const retryIndex = findRetryableUserMessageIndex(messages);
    if (retryIndex < 0) {
      throw new OpenMatesConfigError("No retryable user message found for this chat");
    }
    if (retryIndex === 0) {
      throw new OpenMatesConfigError("Cannot retry a chat whose first message is the failed user turn");
    }
    const retryMessage = messages[retryIndex];
    const boundary = messages[retryIndex - 1];
    return this.rewind({
      chatId: options.chatId,
      toMessageId: boundary.id,
      send: retryMessage.content,
      dryRun: options.dryRun,
      confirmDestructive: options.confirmDestructive,
    });
  }

  async send(message: string, options: ChatSendOptions = {}): Promise<ChatResponse> {
    const history = normalizeHistory(options.history);
    const finalMessage = hasRememberMessageReference(message)
      ? rewriteRememberMessageReferences(message, rememberableMessagesFromRecords(history))
      : message;
    const goal = normalizeOptionalGoal(options.goal);
    if (goal && options.saveToAccount === false) {
      throw new OpenMatesConfigError("Chat goals require a saved account chat. Omit saveToAccount or set saveToAccount: true.");
    }
    if (options.saveToAccount === true || goal || options.teamId) {
      return this.sendSaved(finalMessage, options);
    }
    try {
      const result = await this.client.request<{ response?: ChatResponse }>("/v1/sdk/chats", {
        message: finalMessage,
        history,
        save_to_account: false,
        memory_ids: options.memoryIds ?? [],
        model: options.model,
        focus_mode: options.focusMode
          ? { app_id: options.focusMode.appId, focus_mode_id: options.focusMode.focusModeId }
          : undefined,
        connected_account_directory: options.connectedAccountDirectory ?? [],
        connected_account_token_ref_inputs: options.connectedAccountTokenRefInputs ?? [],
      });
      const response: ChatResponse = result.response ?? result;
      return options.model && response.modelName === undefined && response.model_name === undefined
        ? { ...response, modelName: options.model }
        : response;
    } catch (error) {
      if (!(error instanceof OpenMatesApiError) || error.status !== 401) throw error;
      const result = await this.client.runAppSkill<Record<string, unknown>>("ai", "ask", {
        messages: [...history, { role: "user", content: finalMessage }],
        stream: false,
        apps_enabled: true,
        is_incognito: true,
        model: options.model,
      });
      return { content: appSkillChatContent(result), modelName: options.model, raw: result };
    }
  }

  private async sendSaved(message: string, options: ChatSendOptions): Promise<ChatResponse> {
    const masterKey = await this.client.masterKey();
    const session = await this.client.sdkSession();
    if (!session.user?.id) {
      throw new OpenMatesConfigError("SDK session did not include the authenticated user identity");
    }

    const teamId = options.teamId?.trim() || null;
    const wrappingKey = teamId
      ? await teamKeyForRecord(this.client, await this.client.teams.get(teamId))
      : masterKey;
    const chatId = options.chatId ? await resolveSdkChatId(this.client, options.chatId) : randomUUID();
    const turnId = randomUUID();
    const messageId = randomUUID();
    const createdAt = Math.floor(Date.now() / 1000);
    let chatKey: Uint8Array;
    let encryptedChatKey: string;
    let expectedMessagesV = 0;
    let encryptedChatMetadata: Record<string, unknown> | undefined;
    let loadedMessages: ChatMessageRecord[] = [];

    if (options.chatId) {
      if (teamId) {
        throw new OpenMatesConfigError("Sending to an existing Team chat is not supported yet");
      }
      const loaded = await this.load(chatId);
      const chat = loaded.chat as EncryptedChatMetadata | undefined;
      loadedMessages = normalizeLoadedChatMessages(loaded);
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
      encryptedChatKey = await encryptBytesWithAesGcm(chatKey, wrappingKey);
      const slugMetadata = await buildEncryptedObjectSlugMetadata({
        value: options.slug ?? options.title ?? message,
        encryptionKey: chatKey,
        lookupKey: wrappingKey,
      });
      encryptedChatMetadata = {
        encrypted_title: await encryptWithAesGcmCombined(options.title ?? (teamId ? "New team chat" : message.slice(0, 80)), chatKey),
        encrypted_slug: slugMetadata.encrypted_slug,
        slug_lookup_hash: slugMetadata.slug_lookup_hash,
        encrypted_chat_key: encryptedChatKey,
        created_at: createdAt,
        updated_at: createdAt,
      };
    }

    const history = normalizeHistory(options.history);
    const rememberableMessages = loadedMessages.length > 0
      ? loadedMessages
      : rememberableMessagesFromRecords(history);
    const finalMessage = hasRememberMessageReference(message)
      ? rewriteRememberMessageReferences(message, rememberableMessages)
      : message;
    if (encryptedChatMetadata && !options.title && finalMessage !== message) {
      encryptedChatMetadata.encrypted_title = await encryptWithAesGcmCombined(finalMessage.slice(0, 80), chatKey);
    }

    const recovery = await deriveChatCompletionRecoveryKeypair(
      Buffer.from(chatKey).toString("base64url"),
      chatId,
      1,
    );
    const inferenceHistory = [...history, {
      role: "user",
      content: finalMessage,
      ...(options.senderName ? { name: options.senderName } : {}),
    }];
    const teamAiInvocation = teamId && finalMessage.toLocaleLowerCase().includes("@openmates")
      ? { history: inferenceHistory }
      : undefined;
    const inferenceRequest = {
      messages: teamId ? teamAiInvocation?.history ?? [] : inferenceHistory,
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
      message: teamId ? undefined : finalMessage,
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
        encrypted_content: await encryptWithAesGcmCombined(finalMessage, chatKey),
        encrypted_sender_name: await encryptWithAesGcmCombined(options.senderName ?? "User", chatKey),
        role: "user",
        created_at: createdAt,
        updated_at: createdAt,
      },
      encrypted_chat_metadata: encryptedChatMetadata,
      inference_request: inferenceRequest,
      team_id: teamId ?? undefined,
      team_ai_invocation: teamAiInvocation,
      team_member_mentions: options.teamMemberMentions ?? [],
      connected_account_directory: options.connectedAccountDirectory ?? [],
      connected_account_token_ref_inputs: options.connectedAccountTokenRefInputs ?? [],
    });
    if (teamId && !teamAiInvocation && !result.task_id) {
      return { raw: result };
    }
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
    const goal = normalizeOptionalGoal(options.goal);
    const plan = goal
      ? await this.createAttachedGoalPlan({
          chatId,
          chatKey,
          goal,
          title: normalizeOptionalGoal(options.goalTitle) ?? options.title ?? goal,
        })
      : null;
    return {
      content: recovered.content,
      category: recovered.category,
      model_name: recovered.modelName,
      chat_id: result.chat_id ?? chatId,
      task_id: result.task_id,
      preflight: result.preflight,
      terminal,
      ...(plan ? { plan } : {}),
    };
  }

  private async createAttachedGoalPlan(input: {
    chatId: string;
    chatKey: Uint8Array;
    goal: string;
    title: string;
  }): Promise<PlanRecord> {
    const masterKey = await this.client.masterKey();
    const payload = await buildCreateUserPlanInput(masterKey, {
      title: input.title,
      goal: input.goal,
      primaryChatId: input.chatId,
      primaryChatKey: input.chatKey,
      status: "draft",
    });
    const response = await this.client.request<{ plan?: UserPlanRecord }>("/v1/user-plans", payload);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return toPublicPlan(await decryptUserPlan(response.plan, masterKey));
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
    const resolvedChatId = String((payload.chat as EncryptedChatMetadata | undefined)?.id ?? await resolveSdkChatId(this.client, chatId));
    return this.client.request<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(resolvedChatId)}/export`, {
      format: options.format ?? "json",
      payload,
    });
  }

  async delete(chatId: string, options: ConfirmedMutationOptions): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Deleting a chat");
    return this.client.delete<Record<string, unknown>>(`/v1/sdk/chats/${encodeURIComponent(await resolveSdkChatId(this.client, chatId))}`);
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
    const resolvedChatId = String(chat.id ?? await resolveSdkChatId(this.client, chatId));
    const blob = await generateChatShareBlob(resolvedChatId, chatKey, (options.expires ?? 0) as ShareDuration, options.password);
    return { url: buildChatShareUrl(this.client.webOrigin(), resolvedChatId, blob) };
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

  private async loadPersonalEncryptedChat(chatId: string): Promise<{
    loaded: Record<string, unknown>;
    chat: EncryptedChatMetadata;
    chatKey: Uint8Array;
  }> {
    const loaded = await this.load(chatId);
    const chat = loaded.chat as EncryptedChatMetadata | undefined;
    if (!chat) {
      throw new OpenMatesConfigError("Saved chat payload did not include chat metadata");
    }
    if (chat.hashed_team_id || chat.team_id || chat.shared_chat_id) {
      throw new OpenMatesConfigError("Only personal saved chats are supported for fork, rewind, and retry");
    }
    if (typeof chat.encrypted_chat_key !== "string") {
      throw new OpenMatesConfigError("Saved chat does not include encrypted chat key material");
    }
    const chatKey = await decryptBytesWithAesGcm(chat.encrypted_chat_key, await this.client.masterKey());
    if (!chatKey) {
      throw new OpenMatesConfigError("Unable to decrypt saved chat key material");
    }
    return { loaded, chat, chatKey };
  }
}

type LoadedMessageWithRaw = ChatMessageRecord & { raw: Record<string, unknown> };

function normalizeLoadedChatMessages(payload: Record<string, unknown>): LoadedMessageWithRaw[] {
  const rawMessages = Array.isArray(payload.messages) ? payload.messages : [];
  return rawMessages.map((entry) => {
    const raw = typeof entry === "string"
      ? JSON.parse(entry) as Record<string, unknown>
      : { ...(entry as Record<string, unknown>) };
    const id = stringField(raw.client_message_id) ?? stringField(raw.message_id) ?? stringField(raw.id);
    if (!id) {
      throw new OpenMatesConfigError("Loaded chat message is missing a stable message id");
    }
    const content = stringField(raw.content) ?? "";
    const preview = content.replace(/\s+/g, " ").trim().slice(0, 120);
    return {
      id,
      role: stringField(raw.role) ?? "unknown",
      content,
      senderName: stringField(raw.senderName) ?? stringField(raw.sender_name),
      category: stringField(raw.category),
      modelName: stringField(raw.modelName) ?? stringField(raw.model_name),
      createdAt: numericField(raw.created_at) ?? 0,
      preview,
      raw,
    };
  }).sort((a, b) => a.createdAt - b.createdAt);
}

function findMessageBoundaryIndex(messages: ChatMessageRecord[], messageId: string): number {
  const index = messages.findIndex((message) => message.id === messageId || message.id.startsWith(messageId));
  if (index < 0) {
    throw new OpenMatesConfigError(`Message '${messageId}' was not found in the chat`);
  }
  return index;
}

function findRetryableUserMessageIndex(messages: ChatMessageRecord[]): number {
  let hasLaterAssistant = false;
  for (let index = messages.length - 1; index >= 0; index--) {
    const role = messages[index].role.toLowerCase();
    if (role === "assistant") hasLaterAssistant = true;
    if (role === "user" && !hasLaterAssistant) return index;
  }
  return -1;
}

function stringField(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numericField(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value);
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed > 10_000_000_000 ? Math.floor(parsed / 1000) : Math.floor(parsed);
  }
  return null;
}

function defaultSenderName(role: string): string {
  if (role === "assistant") return "Assistant";
  if (role === "system") return "System";
  return "User";
}

export class OpenMatesIdeaBucket {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async settings(): Promise<IdeaBucketSettings> {
    const response = await this.client.memories.list({
      query: { app_id: IDEABUCKET_APP_ID, item_type: IDEABUCKET_SETTINGS_ITEM_TYPE },
    });
    const memories = Array.isArray(response.memories) ? response.memories as Array<Record<string, unknown>> : [];
    const entry = memories[0];
    if (!entry) {
      return this.normalizeSettings(null, undefined, undefined);
    }
    const data = entry.data && typeof entry.data === "object" && !Array.isArray(entry.data)
      ? entry.data as Record<string, unknown>
      : null;
    return this.normalizeSettings(
      data,
      typeof entry.id === "string" ? entry.id : undefined,
      typeof entry.item_version === "number" ? entry.item_version : undefined,
    );
  }

  async saveSettings(input: IdeaBucketSettingsInput): Promise<IdeaBucketSettings> {
    const current = await this.settings();
    const settings = this.normalizeSettings({
      processing_prompt: input.processingPrompt ?? current.processingPrompt,
      processing_times: input.processingTimes ?? current.processingTimes,
    }, current.entryId, current.itemVersion);
    const data = this.settingsToMemoryValue(settings);
    const result = await this.client.memories.create({
      id: settings.entryId,
      appId: IDEABUCKET_APP_ID,
      itemType: IDEABUCKET_SETTINGS_ITEM_TYPE,
      itemVersion: settings.itemVersion ? settings.itemVersion + 1 : 1,
      data,
    });
    return { ...settings, entryId: String(result.id ?? settings.entryId ?? ""), itemVersion: settings.itemVersion ? settings.itemVersion + 1 : 1, source: "account" };
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

  private normalizeSettings(
    data: Record<string, unknown> | null,
    entryId?: string,
    itemVersion?: number,
  ): IdeaBucketSettings {
    const processingPrompt = typeof data?.processing_prompt === "string" && data.processing_prompt.trim()
      ? data.processing_prompt.trim()
      : IDEABUCKET_DEFAULT_PROCESSING_PROMPT;
    return {
      processingPrompt,
      processingTimes: normalizeIdeaBucketProcessingTimes(data?.processing_times),
      entryId,
      itemVersion,
      source: entryId ? "account" : "default",
    };
  }

  private settingsToMemoryValue(settings: IdeaBucketSettings): Record<string, unknown> {
    return {
      processing_prompt: settings.processingPrompt,
      processing_times: settings.processingTimes.join(","),
    };
  }

  private async buildEncryptedAddPayload(input: IdeaBucketAddInput): Promise<Record<string, unknown>> {
    const ideaText = input.text.trim();
    if (!ideaText) throw new OpenMatesConfigError("IdeaBucket add requires non-empty text.");
    const now = Math.floor(Date.now() / 1000);
    const bucketId = input.bucketId ?? new Date(now * 1000).toISOString().slice(0, 10);
    const settings = input.prompt === undefined || input.scheduledSendAt === undefined
      ? await this.settings()
      : null;
    const scheduledSendAt = input.scheduledSendAt
      ?? (settings?.source === "account"
        ? nextIdeaBucketScheduledSendAt(now, settings.processingTimes)
        : defaultIdeaBucketScheduledSendAt(now));
    const chatId = input.chatId ?? randomUUID();
    const prompt = input.prompt ?? settings?.processingPrompt ?? IDEABUCKET_DEFAULT_PROCESSING_PROMPT;
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
    const chatKey = new Uint8Array(randomBytes(32));
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    return {
      chat_id: chatId,
      encrypted_draft_md: await encryptWithAesGcmCombined(markdown, masterKey),
      encrypted_draft_preview: await encryptWithAesGcmCombined(preview, masterKey),
      ideabucket: true,
      ideabucket_processing_window_id: bucketId,
      ideabucket_processing_version: now,
      encrypted_chat_key: encryptedChatKey,
      scheduled_send_at: scheduledSendAt,
      server_vault_encrypted_processing_payload: await encryptWithAesGcmCombined(serverProcessablePayload, masterKey),
      client_encrypted_future_user_message: await encryptWithAesGcmCombined(markdown, chatKey),
      client_encrypted_ideabucket_system_event: await encryptWithAesGcmCombined(JSON.stringify({
        type: "ideabucket_triggered_send",
        bucket_id: bucketId,
        processing_window_id: bucketId,
        source: "openmates_sdk",
      }), chatKey),
      payload_hash: payloadHash,
    };
  }
}

function defaultIdeaBucketScheduledSendAt(nowSeconds: number): number {
  const date = new Date(nowSeconds * 1000);
  return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1, 9, 0, 0) / 1000);
}

function normalizeIdeaBucketProcessingTimes(value: unknown): string[] {
  const rawTimes = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? value.split(",")
      : IDEABUCKET_DEFAULT_PROCESSING_TIMES;
  const times = rawTimes.map((time) => String(time).trim()).filter(Boolean);
  const uniqueSortedTimes = [...new Set(times)].sort((a, b) => ideaBucketTimeToMinutes(a) - ideaBucketTimeToMinutes(b));
  if (uniqueSortedTimes.length < 1 || uniqueSortedTimes.length > 3) {
    throw new OpenMatesConfigError("IdeaBucket processing_times must include one to three HH:MM values.");
  }
  for (const time of uniqueSortedTimes) {
    if (!IDEABUCKET_PROCESSING_TIME_PATTERN.test(time)) {
      throw new OpenMatesConfigError(`Invalid IdeaBucket processing time '${time}'. Expected HH:MM in 24-hour format.`);
    }
  }
  return uniqueSortedTimes;
}

function ideaBucketTimeToMinutes(value: string): number {
  const match = IDEABUCKET_PROCESSING_TIME_PATTERN.exec(value);
  if (!match) return Number.POSITIVE_INFINITY;
  return Number(match[1]) * 60 + Number(match[2]);
}

function nextIdeaBucketScheduledSendAt(nowSeconds: number, processingTimes: string[]): number {
  const now = new Date(nowSeconds * 1000);
  const candidates = processingTimes.map((time) => {
    const [hour, minute] = time.split(":").map((part) => Number(part));
    const candidate = new Date(now);
    candidate.setHours(hour, minute, 0, 0);
    if (Math.floor(candidate.getTime() / 1000) <= nowSeconds) {
      candidate.setDate(candidate.getDate() + 1);
    }
    return Math.floor(candidate.getTime() / 1000);
  });
  return Math.min(...candidates);
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

  async downloadExport(options: AccountExportDownloadOptions = {}): Promise<Record<string, unknown>> {
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

  async parseClaudeImport(payload: Buffer | Uint8Array | string, sourceName = "claude-export", source: AccountImportSource = "claude"): Promise<ParsedAccountImport> {
    const buffer = typeof payload === "string" ? Buffer.from(payload) : Buffer.from(payload);
    return parseClaudeImportBuffer(buffer, sourceName, source);
  }

  async parseGenericImport(payload: Buffer | Uint8Array | string, sourceName = "generic-transcript.json", source: "gemini" | "other"): Promise<ParsedAccountImport> {
    const buffer = typeof payload === "string" ? Buffer.from(payload, "utf-8") : Buffer.from(payload);
    return parseGenericImportBuffer(buffer, sourceName, source);
  }

  async parseChatGPTImport(payload: Buffer | Uint8Array | string, sourceName = "chatgpt-export", source: AccountImportSource = "chatgpt"): Promise<ParsedAccountImport> {
    const buffer = typeof payload === "string" ? Buffer.from(payload) : Buffer.from(payload);
    return parseChatGPTImportBuffer(buffer, sourceName, source);
  }

  async parseOpenCodeImport(payload: Buffer | Uint8Array | string, sourceName = "opencode-session.json", source: AccountImportSource = "opencode"): Promise<ParsedAccountImport> {
    const buffer = typeof payload === "string" ? Buffer.from(payload, "utf-8") : Buffer.from(payload);
    return parseOpenCodeImportBuffer(buffer, sourceName, source);
  }

  async parseOpenMatesImport(payload: Buffer | Uint8Array | string, sourceName = "openmates-export.zip", password?: string, source: AccountImportSource = "openmates"): Promise<ParsedAccountImport> {
    const buffer = typeof payload === "string" ? Buffer.from(payload) : Buffer.from(payload);
    return parseOpenMatesImportBuffer(buffer, sourceName, password, source);
  }

  async previewImport(options: AccountImportPreviewOptions): Promise<Record<string, unknown>> {
    const chats = options.chats ?? [];
    return this.client.request<Record<string, unknown>>("/v1/account-imports/preview", {
      source: options.source,
      ...(options.chats?.[0]?.parser_format ? { parser_format: options.chats[0].parser_format } : {}),
      chat_count: options.chatCount ?? chats.length,
      source_fingerprints: options.sourceFingerprints ?? chats.map((chat) => chat.source_fingerprint),
      estimated_tokens: options.estimatedTokens ?? 0,
      estimated_tokens_by_chat: options.estimatedTokensByChat ?? chats.map((chat) => Math.ceil(chat.messages.reduce((total, message) => total + message.content.length, 0) / 4)),
      estimated_bytes: options.estimatedBytes ?? 0,
    });
  }

  async confirmImport(importId: string, selectedFingerprints: string[]): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/confirm`, { selected_fingerprints: selectedFingerprints });
  }

  async scanImport(importId: string, chats: ParsedImportChat[], sequence = 0, finalBatch = true, batchId = `scan-${sequence}`): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/scan`, {
      batch_id: batchId,
      sequence,
      final_batch: finalBatch,
      chats,
    });
  }

  async importStatus(importId: string): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/status`);
  }

  async compressImport(
    importId: string,
    input: { sanitizedMessages: ParsedImportChat["messages"]; scanSequence: number; sourceFingerprint: string; priorSummary?: string; sequence?: number; finalBatch?: boolean; batchId?: string },
  ): Promise<Record<string, unknown>> {
    const sequence = input.sequence ?? 0;
    return this.client.request<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/compress`, {
      batch_id: input.batchId ?? `compress-${sequence}`,
      sequence,
      final_batch: input.finalBatch ?? true,
      scan_sequence: input.scanSequence,
      source_fingerprint: input.sourceFingerprint,
      sanitized_messages: input.sanitizedMessages,
      ...(input.priorSummary !== undefined ? { prior_summary: input.priorSummary } : {}),
    });
  }

  async persistImport(importId: string, chats: ParsedImportChat[]): Promise<Record<string, unknown>> {
    const masterKey = await this.client.masterKey();
    const encryptedChats = [];
    for (const chat of chats) {
      const chatId = randomUUID();
      const chatKey = new Uint8Array(randomBytes(32));
      const createdAt = Math.floor((chat.created_at ? Date.parse(chat.created_at) : Date.now()) / 1000);
      const updatedAt = Math.floor((chat.updated_at ? Date.parse(chat.updated_at) : Date.now()) / 1000);
      const messages = [];
      let previousUserMessageId: string | null = null;
      for (const message of chat.messages) {
        const messageId = randomUUID();
        const identity = message.role === "assistant" ? message.imported_assistant_identity : null;
        const isCompressionSummary = message.provider_metadata.import_type === COMPRESSION_SUMMARY_CATEGORY;
        messages.push({
          message_id: messageId,
          role: message.role,
          encrypted_content: await encryptWithAesGcmCombined(message.content, chatKey),
          encrypted_sender_name: await encryptWithAesGcmCombined(identity?.sender_name ?? (message.role === "assistant" ? "AI assistant" : message.role === "system" ? "System" : "User"), chatKey),
          ...(identity ? {
            encrypted_category: await encryptWithAesGcmCombined(identity.category, chatKey),
            encrypted_model_name: await encryptWithAesGcmCombined(identity.model_name, chatKey),
          } : isCompressionSummary ? {
            encrypted_category: await encryptWithAesGcmCombined(COMPRESSION_SUMMARY_CATEGORY, chatKey),
            encrypted_model_name: await encryptWithAesGcmCombined(chat.selected_source, chatKey),
          } : {}),
          created_at: Math.floor((message.created_at ? Date.parse(message.created_at) : Date.now()) / 1000),
          updated_at: Math.floor(Date.now() / 1000),
          ...(message.role === "assistant" && previousUserMessageId ? { user_message_id: previousUserMessageId } : {}),
        });
        if (message.role === "user") previousUserMessageId = messageId;
      }
      encryptedChats.push({
        chat_id: chatId,
        encrypted_title: await encryptWithAesGcmCombined(chat.title || "Imported chat", chatKey),
        encrypted_chat_key: await encryptBytesWithAesGcm(chatKey, masterKey),
        created_at: Number.isFinite(createdAt) ? createdAt : Math.floor(Date.now() / 1000),
        updated_at: Number.isFinite(updatedAt) ? updatedAt : Math.floor(Date.now() / 1000),
        source_fingerprint: chat.source_fingerprint,
        messages,
      });
    }
    return this.client.request<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/persist-encrypted`, { chats: encryptedChats });
  }

  async completeImport(importId: string, options: AccountImportCompleteOptions): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(`/v1/account-imports/${encodeURIComponent(importId)}/complete`, {
      imported_chat_ids: options.importedChatIds,
      source_fingerprints: options.sourceFingerprints,
      encrypted_record_counts: options.recordCounts,
      client_failures: options.clientFailures ?? [],
    });
  }

  async importChats(parsed: ParsedAccountImport, options: AccountImportRunOptions = {}): Promise<Record<string, unknown>> {
    const preview = await this.previewImport({ source: parsed.source, chats: parsed.chats });
    if (preview.can_import === false) throw new OpenMatesConfigError(`Account import blocked: ${String(preview.reason ?? "unknown")}`);
    const defaultSelectionCount = typeof preview.default_selection_count === "number" ? preview.default_selection_count : 0;
    const maxBatchCount = typeof preview.max_batch_count === "number" ? preview.max_batch_count : defaultSelectionCount;
    const selectedCount = options.select === "all"
      ? Math.min(parsed.chats.length, maxBatchCount)
      : Math.min(defaultSelectionCount, parsed.chats.length, maxBatchCount);
    if (selectedCount <= 0) throw new OpenMatesConfigError("No chats are selected for import.");
    const importId = typeof preview.import_id === "string" ? preview.import_id : randomUUID();
    const selectedChats = parsed.chats.slice(0, selectedCount);
    const selectedFingerprints = selectedChats.map((chat) => chat.source_fingerprint);
    const confirmation = await this.confirmImport(importId, selectedFingerprints);
    const initialStatus = await this.importStatus(importId);
    if (Number(initialStatus.last_scan_sequence ?? -1) !== -1 || Number(initialStatus.last_compression_sequence ?? -1) !== -1) {
      throw new OpenMatesConfigError("Resuming this import requires the client-held sanitized batch state.");
    }
    const batches = buildAccountImportMessageBatches(selectedChats);
    const sanitizedChats = selectedChats.map((chat) => ({ ...chat, messages: [] as ParsedImportChat["messages"] }));
    const sanitizedBatches: Array<{ messages: ParsedImportChat["messages"]; scanSequence: number; sourceFingerprint: string; chatIndex: number }> = [];
    let scan: Record<string, unknown> = {};
    for (let sequence = 0; sequence < batches.length; sequence++) {
      const batch = batches[sequence];
      scan = await this.scanImport(importId, [batch.chat], sequence, sequence === batches.length - 1, batch.batchId);
      if (scan.status !== "acknowledged" || scan.sequence !== sequence || scan.batch_id !== batch.batchId || !Array.isArray(scan.chats)) {
        throw new OpenMatesConfigError("Account import scan batch was not acknowledged at the expected cursor.");
      }
      const sanitizedChat = scan.chats[0] as ParsedImportChat | undefined;
      if (!sanitizedChat) throw new OpenMatesConfigError("Account import scan omitted the sanitized batch.");
      sanitizedChats[batch.chatIndex].messages.push(...sanitizedChat.messages);
      sanitizedBatches.push({ messages: sanitizedChat.messages, scanSequence: sequence, sourceFingerprint: batch.sourceFingerprint, chatIndex: batch.chatIndex });
    }
    const postScanStatus = await this.importStatus(importId);
    if (Number(postScanStatus.last_scan_sequence) !== batches.length - 1) throw new OpenMatesConfigError("Account import scan status cursor did not advance as expected.");
    const summaries = new Map<string, string>();
    let compression: Record<string, unknown> = {};
    for (let sequence = 0; sequence < sanitizedBatches.length; sequence++) {
      const batch = sanitizedBatches[sequence];
      const priorSummary = summaries.get(batch.sourceFingerprint);
      const finalChatBatch = sanitizedBatches[sequence + 1]?.sourceFingerprint !== batch.sourceFingerprint;
      compression = await this.compressImport(importId, {
        sanitizedMessages: batch.messages,
        scanSequence: batch.scanSequence,
        sourceFingerprint: batch.sourceFingerprint,
        priorSummary,
        sequence,
        finalBatch: finalChatBatch,
        batchId: `compress-${batch.sourceFingerprint.slice(0, 16)}-${batches[sequence].chunkIndex}`,
      });
      if (compression.status !== "acknowledged" || compression.sequence !== sequence) throw new OpenMatesConfigError("Account import compression was not acknowledged at the expected cursor.");
      if (typeof compression.summary === "string" && compression.summary.trim()) summaries.set(batch.sourceFingerprint, compression.summary);
    }
    const postCompressionStatus = await this.importStatus(importId);
    if (Number(postCompressionStatus.last_compression_sequence) !== sanitizedBatches.length - 1) throw new OpenMatesConfigError("Account import compression status cursor did not advance as expected.");
    const persistedChats = sanitizedChats.map((chat) => appendCompressionSummary(chat, summaries.get(chat.source_fingerprint)));
    const persistence = await this.persistImport(importId, persistedChats);
    const complete = await this.completeImport(importId, {
      importedChatIds: Array.isArray(persistence.imported_chat_ids) ? persistence.imported_chat_ids as string[] : [],
      sourceFingerprints: persistedChats.map((chat) => chat.source_fingerprint),
      recordCounts: typeof persistence.encrypted_record_counts === "object" && persistence.encrypted_record_counts !== null
        ? persistence.encrypted_record_counts as Record<string, number>
        : { chats: 0, messages: 0 },
      clientFailures: Array.isArray(persistence.failures) ? persistence.failures as Array<Record<string, unknown>> : [],
    });
    return { source: parsed.source, parsed, preview, import_id: importId, confirmation, initial_status: initialStatus, post_scan_status: postScanStatus, scan, compression, post_compression_status: postCompressionStatus, persistence, complete };
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

  async setModelDefaults(defaults: AiModelDefaults): Promise<Record<string, unknown>> {
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
  async usageOverview(options: RequestOptions = {}): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/billing/usage/overview", options.query)); }
  async usageDetails(options: { type: "chat" | "app" | "api_key"; identifier: string; yearMonth: string }): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/billing/usage/details", { type: options.type, identifier: options.identifier, year_month: options.yearMonth })); }
  async chatTotal(chatId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(withQuery("/v1/sdk/billing/usage/chat-total", { chat_id: chatId })); }
  async usageSummaries(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/usage/summaries"); }
  async usageDaily(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/usage/daily"); }
  async usageExport(options: { months?: number } = {}): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(withQuery("/v1/sdk/billing/usage/export", { months: options.months })); }
  async createBankTransferOrder(credits: number, options: BankTransferOrderOptions = {}): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/bank-transfer-orders", { credits_amount: credits, currency: "eur", email_encryption_key: options.emailEncryptionKey }); }
  async bankTransferStatus(orderId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/billing/bank-transfer-orders/${encodeURIComponent(orderId)}`); }
  async listBankTransferOrders(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/bank-transfer-orders"); }
  async listInvoices(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/invoices"); }
  async downloadInvoice(invoiceId: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(`/v1/sdk/billing/invoices/${encodeURIComponent(invoiceId)}/download`); }
  async downloadCreditNote(invoiceId: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> { return this.client.getRaw(`/v1/sdk/billing/invoices/${encodeURIComponent(invoiceId)}/credit-note/download`); }
  async requestRefund(invoiceId: string, options: ConfirmedMutationOptions & { emailEncryptionKey?: string }): Promise<Record<string, unknown>> { requireConfirmed(options, "Requesting an invoice refund"); return this.client.request<Record<string, unknown>>("/v1/sdk/billing/refund", { invoice_id: invoiceId, email_encryption_key: options.emailEncryptionKey }); }
  async redeemGiftCard(code: string): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/gift-cards/redeem", { code }); }
  async listRedeemedGiftCards(): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>("/v1/sdk/billing/gift-cards/redeemed"); }
  async createGiftCardBankTransferOrder(credits: number, options: BankTransferOrderOptions = {}): Promise<Record<string, unknown>> { return this.client.request<Record<string, unknown>>("/v1/sdk/billing/gift-cards/bank-transfer-orders", { credits_amount: credits, currency: "eur", email_encryption_key: options.emailEncryptionKey }); }
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

export class OpenMatesHistory {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(filters: { objectType?: string; objectId?: string; limit?: number } = {}): Promise<Record<string, unknown>[]> {
    const params = new URLSearchParams();
    if (filters.objectType) params.set("object_type", filters.objectType);
    if (filters.objectId) params.set("object_id", filters.objectId);
    if (filters.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    const response = await this.client.get<{ change_sets?: Record<string, unknown>[] }>(`/v1/workspace/history${query ? `?${query}` : ""}`);
    return response.change_sets ?? [];
  }

  async show(changeSetId: string): Promise<Record<string, unknown>> {
    return await this.client.get<Record<string, unknown>>(`/v1/workspace/history/${encodeURIComponent(changeSetId)}`);
  }

  async undo(changeSetId: string): Promise<Record<string, unknown>> {
    return await this.client.request<Record<string, unknown>>(`/v1/workspace/history/${encodeURIComponent(changeSetId)}/undo`, {});
  }
}

export class OpenMatesProjects {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(options: ProjectContextOptions & { includeArchived?: boolean }): Promise<ProjectRecordPlain[]> {
    const crypto = await projectWrappingKey(this.client, options);
    const response = await this.client.get<{ projects?: ProjectRecord[] }>(withQuery("/v1/projects", {
      include_archived: options.includeArchived,
      team_id: crypto.teamId,
    }));
    return Promise.all((response.projects ?? []).map((project) => decryptSdkProject(project, crypto.key, crypto.teamId)));
  }

  async show(projectId: string, context: ProjectContextOptions): Promise<ProjectRecordPlain> {
    const { record, projectKey } = await resolveSdkProject(this.client, projectId, context);
    return decryptSdkProjectWithKey(record, projectKey);
  }

  async create(input: ProjectPlainCreateOptions, context: ProjectContextOptions): Promise<ProjectRecordPlain> {
    const crypto = await projectWrappingKey(this.client, context);
    const created = await buildProjectCreatePayload(crypto.key, input, crypto.teamId);
    const response = await this.client.request<{ project?: ProjectRecord }>(withQuery("/v1/projects", { team_id: crypto.teamId }), created.payload);
    if (!response.project) throw new OpenMatesApiError(500, { detail: "Project response missing project" });
    return decryptSdkProjectWithKey(response.project, created.projectKey);
  }

  async update(projectId: string, input: ProjectPlainUpdateOptions, context: ProjectContextOptions): Promise<ProjectRecordPlain> {
    const update = await buildProjectUpdatePayload(this.client, projectId, input, context);
    const { teamId } = requireProjectContext(context);
    const response = await this.client.patch<{ project?: ProjectRecord }>(
      withQuery(`/v1/projects/${encodeURIComponent(update.project_id)}`, { team_id: teamId }),
      update.patch,
    );
    if (!response.project) throw new OpenMatesApiError(500, { detail: "Project response missing project" });
    return decryptSdkProjectWithKey(response.project, update.projectKey);
  }

  async archive(projectId: string, context: ProjectContextOptions): Promise<ProjectRecordPlain> {
    return this.update(projectId, { archived: true }, context);
  }

  async unarchive(projectId: string, context: ProjectContextOptions): Promise<ProjectRecordPlain> {
    return this.update(projectId, { archived: false }, context);
  }

  async delete(projectId: string, options: ProjectContextOptions & ConfirmedMutationOptions): Promise<{ deleted: boolean }> {
    requireConfirmed(options, "Project delete");
    const { teamId } = requireProjectContext(options);
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId, options);
    const response = await this.client.delete<{ deleted?: boolean }>(withQuery(`/v1/projects/${encodeURIComponent(resolvedProjectId)}`, {
      confirmation_project_id: resolvedProjectId,
      team_id: teamId,
    }));
    return { deleted: response.deleted === true };
  }

  async history(projectId: string, options: { limit?: number } = {}): Promise<Record<string, unknown>[]> {
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId);
    const query = options.limit ? `?limit=${encodeURIComponent(String(options.limit))}` : "";
    const response = await this.client.get<{ entries?: Record<string, unknown>[] }>(`/v1/projects/${encodeURIComponent(resolvedProjectId)}/history${query}`);
    return response.entries ?? [];
  }

  async restore(projectId: string, options: { entryId: string; state?: "before" | "after" }): Promise<Record<string, unknown>> {
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId);
    return await this.client.request<Record<string, unknown>>(`/v1/projects/${encodeURIComponent(resolvedProjectId)}/restore`, {
      entry_id: options.entryId,
      state: options.state ?? "after",
    });
  }

  async ask(instruction: string, options: {
    create?: ProjectPlainCreateOptions;
    update?: { projectId: string; patch: ProjectPlainUpdateOptions };
    updates?: Array<{ projectId: string; patch: ProjectPlainUpdateOptions }>;
    exactDelete?: Record<string, unknown>;
    exactDeletes?: Record<string, unknown>[];
  } = {}): Promise<Record<string, unknown>> {
    const plannedCreate = !options.create && !options.update && !options.updates?.length && !options.exactDelete && !options.exactDeletes?.length
      ? await this.client.request<{ proposed_project?: Record<string, unknown> }>("/v1/projects/ask/plan", { instruction })
      : null;
    const proposal = options.create ?? (plannedCreate?.proposed_project ? {
      name: String(plannedCreate.proposed_project.name ?? instruction),
      description: String(plannedCreate.proposed_project.description ?? ""),
      icon: String(plannedCreate.proposed_project.icon ?? "folder"),
      color: String(plannedCreate.proposed_project.color ?? "default"),
    } : undefined);
    const encryptedUpdates = options.updates
      ? await Promise.all(options.updates.map(async (update) => {
        const built = await buildProjectUpdatePayload(this.client, update.projectId, update.patch);
        return { project_id: built.project_id, patch: built.patch };
      }))
      : undefined;
    const encryptedCreate = proposal ? await buildProjectCreatePayload(await this.client.masterKey(), proposal) : null;
    const encryptedUpdate = options.update ? await buildProjectUpdatePayload(this.client, options.update.projectId, options.update.patch) : null;
    return await this.client.request<Record<string, unknown>>("/v1/projects/ask", {
      instruction,
      ...(encryptedCreate ? { encrypted_create: encryptedCreate.payload } : {}),
      ...(encryptedUpdate ? { encrypted_update: { project_id: encryptedUpdate.project_id, patch: encryptedUpdate.patch } } : {}),
      ...(encryptedUpdates ? { encrypted_updates: encryptedUpdates } : {}),
      ...(options.exactDelete ? { exact_delete: options.exactDelete } : {}),
      ...(options.exactDeletes ? { exact_deletes: options.exactDeletes } : {}),
    }).then(async (response) => {
      const records = Array.isArray(response.projects) ? response.projects as ProjectRecord[] : response.project ? [response.project as ProjectRecord] : [];
      const masterKey = await this.client.masterKey();
      return publicProjectAskResponse(response, await Promise.all(records.map((project) => decryptSdkProject(project, masterKey))));
    });
  }
}

export class OpenMatesTasks {
  private readonly client: OpenMates;
  readonly dependencies: {
    add: (taskId: string, target: WorkDependencyTarget, filters?: TaskListFilters) => Promise<Record<string, unknown>>;
    remove: (taskId: string, target: WorkDependencyTarget, filters?: TaskListFilters) => Promise<Record<string, unknown>>;
    list: (taskId: string, filters?: TaskListFilters) => Promise<{ dependencies: Record<string, unknown>[]; blockers: Record<string, unknown>[] }>;
  };

  constructor(client: OpenMates) {
    this.client = client;
    this.dependencies = {
      add: async (taskId, target, filters = {}) => {
        const task = await this.resolve(taskId, filters);
        return client.request(`/v1/user-tasks/${encodeURIComponent(task.taskId)}/dependencies`, { target_ref: `${target.kind}:${target.id}` });
      },
      remove: async (taskId, target, filters = {}) => {
        const task = await this.resolve(taskId, filters);
        return client.delete(`/v1/user-tasks/${encodeURIComponent(task.taskId)}/dependencies/${target.kind}/${encodeURIComponent(target.id)}`);
      },
      list: async (taskId, filters = {}) => {
        const task = await this.resolve(taskId, filters);
        const response = await client.get<{ dependencies?: Record<string, unknown>[]; blockers?: Record<string, unknown>[] }>(`/v1/user-tasks/${encodeURIComponent(task.taskId)}/dependencies`);
        return { dependencies: response.dependencies ?? [], blockers: response.blockers ?? [] };
      },
    };
  }

  async list(filters: TaskListFilters = {}): Promise<TaskRecord[]> {
    return (await this.listInternal(filters)).map(toPublicTask);
  }

  async show(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return toPublicTask(await this.resolve(id, filters));
  }

  async listActivity(id: string, filters: TaskListFilters & { limit?: number } = {}): Promise<TaskActivityRecord[]> {
    const task = await this.resolve(id, filters);
    const records: UserTaskActivityRecord[] = [];
    let cursor: string | undefined;
    do {
      const response = await this.client.get<{ entries?: UserTaskActivityRecord[]; next_cursor?: string | null }>(withQuery(
        `/v1/user-tasks/${encodeURIComponent(task.taskId)}/activity`,
        { team_id: filters.teamId, cursor, limit: filters.limit },
      ));
      records.push(...(response.entries ?? []));
      const nextCursor = response.next_cursor ?? undefined;
      if (nextCursor && nextCursor === cursor) throw new OpenMatesConfigError("Task Activity pagination cursor did not advance");
      cursor = nextCursor;
    } while (cursor);
    return decryptTaskActivityEntries(task, await this.client.masterKey(), records);
  }

  async addActivityComment(id: string, input: TaskActivityInput, filters: TaskListFilters = {}): Promise<TaskActivityRecord> {
    const task = await this.resolve(id, filters);
    const masterKey = await this.client.masterKey();
    const response = await this.client.request<{ entry?: UserTaskActivityRecord }>(withQuery(
      `/v1/user-tasks/${encodeURIComponent(task.taskId)}/activity`,
      { team_id: filters.teamId },
    ), await buildCreateTaskActivityInput(task, masterKey, input));
    if (!response.entry) throw new OpenMatesApiError(500, { detail: "User task activity response missing entry" });
    return decryptTaskActivityEntry(task, masterKey, response.entry);
  }

  async deleteActivityComment(id: string, entryId: string, filters: TaskListFilters = {}): Promise<TaskActivityRecord> {
    const task = await this.resolve(id, filters);
    const response = await this.client.delete<{ entry?: UserTaskActivityRecord }>(withQuery(
      `/v1/user-tasks/${encodeURIComponent(task.taskId)}/activity/${encodeURIComponent(entryId)}`,
      { team_id: filters.teamId },
    ));
    if (!response.entry) throw new OpenMatesApiError(500, { detail: "User task activity response missing entry" });
    return decryptTaskActivityEntry(task, await this.client.masterKey(), response.entry);
  }

  async history(id: string, filters: TaskListFilters & { limit?: number } = {}): Promise<Record<string, unknown>[]> {
    const task = await this.resolve(id, filters);
    const query = filters.limit ? `?limit=${encodeURIComponent(String(filters.limit))}` : "";
    const response = await this.client.get<{ entries?: Record<string, unknown>[] }>(`/v1/user-tasks/${encodeURIComponent(task.taskId)}/history${query}`);
    return response.entries ?? [];
  }

  async restore(id: string, options: { entryId: string; state?: "before" | "after"; filters?: TaskListFilters }): Promise<Record<string, unknown>> {
    const task = await this.resolve(id, options.filters ?? {});
    return await this.client.request<Record<string, unknown>>(`/v1/user-tasks/${encodeURIComponent(task.taskId)}/restore`, {
      entry_id: options.entryId,
      state: options.state ?? "after",
    });
  }

  async ask(instruction: string, options: {
    create?: TaskPlainCreateOptions;
    creates?: TaskPlainCreateOptions[];
    update?: { taskId: string; patch: TaskPlainUpdateOptions; filters?: TaskListFilters };
    updates?: Array<{ taskId: string; patch: TaskPlainUpdateOptions; filters?: TaskListFilters }>;
    exactDelete?: Record<string, unknown>;
    exactDeletes?: Record<string, unknown>[];
  } = {}): Promise<Record<string, unknown>> {
    const masterKey = await this.client.masterKey();
    const plannedCreates = !options.create && !options.creates?.length && !options.update && !options.updates?.length && !options.exactDelete && !options.exactDeletes?.length
      ? (await this.client.request<{ proposed_tasks?: TaskPlainCreateOptions[] }>("/v1/user-tasks/ask/plan", { instruction })).proposed_tasks ?? []
      : [];
    const creates = options.creates ?? (options.create ? [options.create] : plannedCreates);
    const encryptedCreates = await Promise.all(creates.map(async (create) => buildCreateUserTaskInput(masterKey, await canonicalizeTaskCreateInput(this.client, create))));
    const encryptedUpdates = options.updates
      ? await Promise.all(options.updates.map(async (update) => {
        const task = await this.resolve(update.taskId, update.filters ?? {});
        return { task_id: task.taskId, patch: await buildUpdateUserTaskInput(task, masterKey, await canonicalizeTaskUpdateInput(this.client, update.patch, update.filters?.teamId)) };
      }))
      : undefined;
    const update = options.update;
    const encryptedUpdate = update
      ? await (async () => {
        const task = await this.resolve(update.taskId, update.filters ?? {});
        return { task_id: task.taskId, patch: await buildUpdateUserTaskInput(task, masterKey, await canonicalizeTaskUpdateInput(this.client, update.patch, update.filters?.teamId)) };
      })()
      : undefined;
    const response = await this.client.request<Record<string, unknown>>("/v1/user-tasks/ask", {
      instruction,
      ...(options.create && encryptedCreates[0] ? { encrypted_create: encryptedCreates[0] } : {}),
      ...(options.creates || plannedCreates.length > 0 ? { encrypted_creates: encryptedCreates } : {}),
      ...(encryptedUpdate ? { encrypted_update: encryptedUpdate } : {}),
      ...(encryptedUpdates ? { encrypted_updates: encryptedUpdates } : {}),
      ...(options.exactDelete ? { exact_delete: options.exactDelete } : {}),
      ...(options.exactDeletes ? { exact_deletes: options.exactDeletes } : {}),
    });
    const records = Array.isArray(response.tasks) ? response.tasks as UserTaskRecord[] : response.task ? [response.task as UserTaskRecord] : [];
    return publicTaskAskResponse(response, (await decryptUserTasks(records, masterKey)).map(toPublicTask));
  }

  async create(input: TaskPlainCreateOptions): Promise<TaskRecord> {
    const masterKey = await this.client.masterKey();
    const created = await this.createRaw(await buildCreateUserTaskInput(masterKey, await canonicalizeTaskCreateInput(this.client, input)));
    return toPublicTask(await decryptUserTask(created, masterKey));
  }

  async update(id: string, input: TaskPlainUpdateOptions, filters: TaskListFilters = {}): Promise<TaskRecord> {
    let task = await this.resolve(id, filters);
    const masterKey = await this.client.masterKey();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const updated = await this.updateRaw(task.taskId, await buildUpdateUserTaskInput(task, masterKey, await canonicalizeTaskUpdateInput(this.client, input, filters.teamId)), filters.teamId);
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

  async addToProject(id: string, projectId: string, options: { filters?: TaskListFilters } = {}): Promise<TaskRecord> {
    const task = await this.resolve(id, options.filters ?? {});
    const masterKey = await this.client.masterKey();
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId, options.filters?.teamId ? { teamId: options.filters.teamId } : { personal: true });
    const updated = await this.updateRaw(task.taskId, await buildUpdateUserTaskInput(task, masterKey, {
      projectIds: appendUniqueProjectId(task.linkedProjectIds, resolvedProjectId),
    }), options.filters?.teamId);
    return toPublicTask(await decryptUserTask(updated, masterKey));
  }

  async removeFromProject(id: string, projectId: string, options: { filters?: TaskListFilters } = {}): Promise<TaskRecord> {
    const task = await this.resolve(id, options.filters ?? {});
    const masterKey = await this.client.masterKey();
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId, options.filters?.teamId ? { teamId: options.filters.teamId } : { personal: true });
    const updated = await this.updateRaw(task.taskId, await buildUpdateUserTaskInput(task, masterKey, {
      projectIds: removeProjectId(task.linkedProjectIds, resolvedProjectId),
    }), options.filters?.teamId);
    return toPublicTask(await decryptUserTask(updated, masterKey));
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
          team_id: filters.teamId,
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
        return await this.client.delete<{ deleted?: boolean; task_id?: string }>(withQuery(`/v1/user-tasks/${encodeURIComponent(task.taskId)}`, {
          version: task.version,
          team_id: options.filters?.teamId,
        }));
      } catch (error) {
        if (attempt > 0 || !isTaskVersionConflict(error)) throw error;
        await delay(1000);
        task = await this.resolve(id, options.filters ?? {});
      }
    }
    throw new OpenMatesConfigError("Task delete retry failed unexpectedly");
  }

  async deleteById(id: string, options: ConfirmedMutationOptions & { filters?: TaskListFilters } = {}): Promise<{ deleted?: boolean; task_id?: string }> {
    return this.delete(id, options);
  }

  async done(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.actionById(id, "complete", {}, filters);
  }

  async complete(id: string, filters: TaskListFilters = {}): Promise<TaskRecord> {
    return this.done(id, filters);
  }

  async block(id: string, reason: string, options: TaskBlockOptions = {}): Promise<TaskRecord> {
    const { reasonText, ...filters } = options;
    const task = await this.resolve(id, filters);
    const action = await buildBlockUserTaskInput(task, await this.client.masterKey(), { reasonCode: reason, reasonText });
    return this.actionById(id, "block", action, filters);
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
          team_id: filters.teamId,
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
    const canonicalFilters = await canonicalizeTaskFilters(this.client, filters);
    const masterKey = filters.labels || filters.tags || filters.externalChat ? await this.client.masterKey() : undefined;
    const response = await this.client.get<{ tasks?: UserTaskRecord[] }>(withQuery("/v1/user-tasks", {
      status: canonicalFilters.status,
      chat_id: canonicalFilters.chatId,
      project_id: canonicalFilters.projectId,
      plan_id: canonicalFilters.planId,
      label_hash: masterKey ? labelHashes(masterKey, normalizeLabels(filters.labels ?? filters.tags ?? [])) : undefined,
      external_chat_provider: canonicalFilters.externalChat?.provider,
      external_chat_lookup_hash: masterKey && canonicalFilters.externalChat
        ? externalChatLookupHash(masterKey, canonicalFilters.externalChat)
        : undefined,
      priority: normalizeTaskPriority(canonicalFilters.priority),
      team_id: canonicalFilters.teamId,
    }));
    return response.tasks ?? [];
  }

  private async createRaw(input: UserTaskCreateInput): Promise<UserTaskRecord> {
    const response = await this.client.request<{ task?: UserTaskRecord }>("/v1/user-tasks", input);
    if (!response.task) throw new OpenMatesApiError(500, { detail: "User task response missing task" });
    return response.task;
  }

  private async updateRaw(taskId: string, input: UserTaskUpdateInput, teamId?: string): Promise<UserTaskRecord> {
    const response = await this.client.patch<{ task?: UserTaskRecord }>(withQuery(`/v1/user-tasks/${encodeURIComponent(taskId)}`, { team_id: teamId }), input);
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
        const updated = await this.actionRaw(task.taskId, action, { version: task.version, team_id: filters.teamId, ...patch });
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

type PlanTextSectionFacade = {
  add: (planId: string, value: string) => Promise<PlanRecord>;
  update: (planId: string, value: string) => Promise<PlanRecord>;
  remove: (planId: string) => Promise<PlanRecord>;
};

export type PlanCriterionRecord = Omit<PlanCriterionCreateOptions, "criterionId"> & {
  criterionId: string;
  createdAt: number | null;
  updatedAt: number | null;
};

export type PlanCriterionUpdateOptions = Partial<Omit<PlanCriterionCreateOptions, "criterionId" | "text">> & {
  evidence?: string;
  coverageNote?: string;
  waiverReason?: string;
};

export interface PlanAssumptionCreateOptions {
  assumptionId?: string;
  text: string;
  category?: string;
  status?: string;
  requiredBefore?: string;
  linkedSubChatId?: string | null;
  linkedTaskId?: string | null;
  linkedCriterionIds?: string[];
  sourceCount?: number;
  correctedText?: string;
  evidenceSummary?: string;
  blockerReason?: string;
  waiverReason?: string;
  sources?: string;
  proofInputs?: PlanAssumptionProofInput[];
}

export type WorkDependencyTarget = { kind: "plan" | "task"; id: string };
export type PlanAssumptionProofInput =
  | { kind: "embed"; embedId: string; startLine?: number; endLine?: number }
  | { kind: "file"; path: string; startLine?: number; endLine?: number }
  | { kind: "url"; url: string };

export type PlanAssumptionUpdateOptions = Partial<Omit<PlanAssumptionCreateOptions, "assumptionId" | "text">>;

export type PlanAssumptionRecord = Omit<PlanAssumptionCreateOptions, "assumptionId"> & {
  assumptionId: string;
  createdAt: number | null;
  updatedAt: number | null;
};

export interface PlanReferencePatternCreateOptions {
  patternId?: string;
  title: string;
  description?: string;
  category?: string;
  status?: string;
  requiredBefore?: string;
  sourceCount?: number;
  linkedTaskIds?: string[];
  linkedCheckIds?: string[];
  sources?: string;
  matchRules?: string;
  antiPatterns?: string;
  evidenceSummary?: string;
  waiverReason?: string;
}

export type PlanReferencePatternUpdateOptions = Partial<Omit<PlanReferencePatternCreateOptions, "patternId" | "title">>;

export type PlanReferencePatternRecord = Omit<PlanReferencePatternCreateOptions, "patternId"> & {
  patternId: string;
  createdAt: number | null;
  updatedAt: number | null;
};

export type PlanVerificationRecord = Omit<PlanVerificationCreateOptions, "verificationId"> & {
  verificationId: string;
  sourceHash: string | null;
  lifecycleStatus: string | null;
  linkedSubChatId: string | null;
  sourceEmbedId: string | null;
  runnerKind: string | null;
  description: string;
  evaluatorInstructions: string;
  sourcePath: string;
  redPhaseReason: string;
  resultSummary: string;
  requiredFixes: string;
  createdAt: number | null;
  updatedAt: number | null;
};

export type PlanLearningRecord = Omit<DecryptedPlanLearning, "encrypted">;

export class OpenMatesPlans {
  private readonly client: OpenMates;
  readonly goal: { set: (planId: string, value: string) => Promise<PlanRecord> };
  readonly successCriteria: {
    add: (planId: string, input: PlanCriterionCreateOptions) => Promise<PlanCriterionRecord>;
    update: (planId: string, criterionId: string, input: PlanCriterionUpdateOptions) => Promise<PlanCriterionRecord>;
    remove: (planId: string, criterionId: string) => Promise<Record<string, unknown>>;
  };
  readonly tasks: {
    list: (planId: string) => Promise<unknown[]>;
    add: (planId: string, input: TaskCreateOptions) => Promise<Record<string, unknown>>;
    update: (planId: string, taskId: string, input: TaskUpdateOptions) => Promise<Record<string, unknown>>;
    remove: (planId: string, taskId: string) => Promise<Record<string, unknown>>;
  };
  readonly userFlows: {
    set: (planId: string, value: UserPlanFlow[]) => Promise<PlanRecord>;
    clear: (planId: string) => Promise<PlanRecord>;
  };
  readonly scopeIn: PlanTextSectionFacade;
  readonly scopeOut: PlanTextSectionFacade;
  readonly openQuestions: PlanTextSectionFacade & {
    answer: (planId: string, value: string) => Promise<PlanRecord>;
  };
  readonly constraints: PlanTextSectionFacade;
  readonly decisions: PlanTextSectionFacade & {
    supersede: (planId: string, value: string) => Promise<PlanRecord>;
  };
  readonly risks: PlanTextSectionFacade;
  readonly checks: {
    add: (planId: string, input: PlanVerificationCreateOptions) => Promise<PlanVerificationRecord>;
    update: (planId: string, checkId: string, input: PlanVerificationUpdateOptions) => Promise<PlanVerificationRecord>;
    remove: (planId: string, checkId: string) => Promise<Record<string, unknown>>;
    addEvidence: (planId: string, checkId: string, input: PlanVerificationEvidenceOptions) => Promise<PlanVerificationRecord>;
    getRun: (planId: string, checkId: string, runId: string) => Promise<Record<string, unknown>>;
  };
  readonly assumptions: {
    add: (planId: string, input: PlanAssumptionCreateOptions) => Promise<PlanAssumptionRecord>;
    update: (planId: string, assumptionId: string, input: PlanAssumptionUpdateOptions) => Promise<PlanAssumptionRecord>;
    check: (planId: string, assumptionId: string, input?: PlanAssumptionUpdateOptions) => Promise<PlanAssumptionRecord>;
    waive: (planId: string, assumptionId: string, input: PlanAssumptionUpdateOptions) => Promise<PlanAssumptionRecord>;
    remove: (planId: string, assumptionId: string) => Promise<Record<string, unknown>>;
  };
  readonly referencePatterns: {
    add: (planId: string, input: PlanReferencePatternCreateOptions) => Promise<PlanReferencePatternRecord>;
    update: (planId: string, patternId: string, input: PlanReferencePatternUpdateOptions) => Promise<PlanReferencePatternRecord>;
    inspect: (planId: string, patternId: string, input?: PlanReferencePatternUpdateOptions) => Promise<PlanReferencePatternRecord>;
    waive: (planId: string, patternId: string, input: PlanReferencePatternUpdateOptions) => Promise<PlanReferencePatternRecord>;
    remove: (planId: string, patternId: string) => Promise<Record<string, unknown>>;
  };
  readonly learnings: {
    list: (planId: string) => Promise<PlanLearningRecord[]>;
    show: (planId: string, learningId: string) => Promise<PlanLearningRecord>;
    create: (planId: string, input: PlanLearningCreateOptions) => Promise<PlanLearningRecord>;
    update: (planId: string, learningId: string, input: PlanLearningUpdateOptions) => Promise<PlanLearningRecord>;
    remove: (planId: string, learningId: string) => Promise<Record<string, unknown>>;
    createTasks: (planId: string, input: UserPlanLearningCreateTasksInput) => Promise<UserPlanLearningCreateTasksResult>;
  };
  readonly context: { artifacts: PlanTextSectionFacade };
  readonly activity: { list: (planId: string, options?: { limit?: number }) => Promise<Record<string, unknown>[]> };
  readonly dependencies: { add: (planId: string, target: WorkDependencyTarget) => Promise<Record<string, unknown>>; remove: (planId: string, target: WorkDependencyTarget) => Promise<Record<string, unknown>>; list: (planId: string) => Promise<{ dependencies: Record<string, unknown>[]; blockers: Record<string, unknown>[] }> };
  readonly revisions: { create: (planId: string) => Promise<Record<string, unknown>>; list: (planId: string) => Promise<Record<string, unknown>[]> };
  readonly review: { submit: (planId: string) => Promise<{ revision: Record<string, unknown>; reviewUrl: string }> };
  readonly approval: { status: (planId: string) => Promise<PlanRecord> };

  constructor(client: OpenMates) {
    this.client = client;
    this.goal = { set: (planId, value) => this.update(planId, { goal: value }) };
    this.successCriteria = {
      add: (planId, input) => this.createCriterion(planId, input),
      update: (planId, criterionId, input) => this.updateCriterion(planId, criterionId, input),
      remove: (planId, criterionId) => this.deleteCriterion(planId, criterionId),
    };
    this.tasks = {
      list: async (planId) => this.client.tasks.list({ planId } as Record<string, unknown>),
      add: async (planId, input) => this.client.tasks.create({ ...input, planId }),
      update: async (planId, taskId, input) => this.client.tasks.update(taskId, input, { planId }),
      remove: async (planId, taskId) => this.client.tasks.delete(taskId, { confirmed: true, filters: { planId } }),
    };
    this.userFlows = {
      set: (planId, value) => this.update(planId, { userFlows: value }),
      clear: (planId) => this.update(planId, { userFlows: [] }),
    };
    this.scopeIn = this.textSectionFacade("scopeIn");
    this.scopeOut = this.textSectionFacade("scopeOut");
    this.openQuestions = {
      ...this.textSectionFacade("openQuestions"),
      answer: (planId, value) => this.update(planId, { openQuestions: value }),
    };
    this.constraints = this.textSectionFacade("constraints");
    this.decisions = {
      ...this.textSectionFacade("decisions"),
      supersede: (planId, value) => this.update(planId, { decisions: value }),
    };
    this.risks = this.textSectionFacade("risks");
    this.checks = {
      add: (planId, input) => this.createVerification(planId, input),
      update: (planId, checkId, input) => this.updateVerification(planId, checkId, input),
      remove: (planId, checkId) => this.deleteVerification(planId, checkId),
      addEvidence: (planId, checkId, input) => this.addVerificationEvidence(planId, checkId, input),
      getRun: (planId, checkId, runId) => this.getVerificationRun(planId, checkId, runId),
    };
    this.assumptions = {
      add: (planId, input) => this.createAssumption(planId, input),
      update: (planId, assumptionId, input) => this.updateAssumption(planId, assumptionId, input),
      check: (planId, assumptionId, input = {}) => this.updateAssumption(planId, assumptionId, { ...input, status: input.status ?? "checking" }),
      waive: (planId, assumptionId, input) => this.updateAssumption(planId, assumptionId, { ...input, status: "waived" }),
      remove: (planId, assumptionId) => this.deleteAssumption(planId, assumptionId),
    };
    this.referencePatterns = {
      add: (planId, input) => this.createReferencePattern(planId, input),
      update: (planId, patternId, input) => this.updateReferencePattern(planId, patternId, input),
      inspect: (planId, patternId, input = {}) => this.updateReferencePattern(planId, patternId, { ...input, status: input.status ?? "inspected" }),
      waive: (planId, patternId, input) => this.updateReferencePattern(planId, patternId, { ...input, status: "waived" }),
      remove: (planId, patternId) => this.deleteReferencePattern(planId, patternId),
    };
    this.learnings = {
      list: (planId) => this.listLearnings(planId),
      show: async (planId, learningId) => {
        const learning = (await this.listLearnings(planId)).find((candidate) => candidate.learningId === learningId);
        if (!learning) throw new OpenMatesApiError(404, { detail: "Plan learning not found" });
        return learning;
      },
      create: (planId, input) => this.createLearning(planId, input),
      update: (planId, learningId, input) => this.updateLearning(planId, learningId, input),
      remove: (planId, learningId) => this.deleteLearning(planId, learningId),
      createTasks: (planId, input) => this.createLearningTasks(planId, input),
    };
    this.context = { artifacts: this.textSectionFacade("context") };
    this.activity = { list: (planId, options = {}) => this.history(planId, options) };
    this.dependencies = {
      add: (planId, target) => this.addDependency(planId, target),
      remove: (planId, target) => this.removeDependency(planId, target),
      list: (planId) => this.listDependencies(planId),
    };
    this.revisions = {
      create: (planId) => this.createRevision(planId),
      list: (planId) => this.listRevisions(planId),
    };
    this.review = { submit: (planId) => this.submitForReview(planId) };
    this.approval = { status: (planId) => this.show(planId) };
  }

  private textSectionFacade(field: keyof PlanUpdateOptions): PlanTextSectionFacade {
    return {
      add: (planId, value) => this.update(planId, { [field]: value }),
      update: (planId, value) => this.update(planId, { [field]: value }),
      remove: (planId) => this.update(planId, { [field]: "" }),
    };
  }

  async list(filters: { status?: UserPlanStatus; chatId?: string; projectId?: string; activeOnly?: boolean } = {}): Promise<PlanRecord[]> {
    return (await decryptUserPlans(await this.listRaw(filters), await this.client.masterKey())).map(toPublicPlan);
  }

  private async listRaw(filters: { status?: UserPlanStatus; chatId?: string; projectId?: string; activeOnly?: boolean } = {}): Promise<UserPlanRecord[]> {
    return listSdkRawPlans(this.client, filters);
  }

  async create(input: PlanCreateOptions): Promise<PlanRecord> {
    const payload = await buildCreateUserPlanInput(await this.client.masterKey(), input);
    const response = await this.client.request<{ plan?: UserPlanRecord }>("/v1/user-plans", payload);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return toPublicPlan(await decryptUserPlan(response.plan, await this.client.masterKey()));
  }

  async show(planId: string): Promise<PlanRecord> {
    return toPublicPlan(await decryptUserPlan(await this.getRawPlan(planId), await this.client.masterKey()));
  }

  async update(planId: string, input: PlanUpdateOptions): Promise<PlanRecord> {
    const masterKey = await this.client.masterKey();
    const existing = await decryptUserPlan(await this.getRawPlan(planId), masterKey);
    const payload = await buildUpdateUserPlanInput(existing, masterKey, input);
    const response = await this.client.patch<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(existing.planId)}`, payload);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return toPublicPlan(await decryptUserPlan(response.plan, masterKey));
  }

  async addToProject(planId: string, projectId: string): Promise<PlanRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await decryptUserPlan(await this.getRawPlan(planId), masterKey);
    const { record, projectKey } = await resolveSdkProject(this.client, projectId);
    const linkedProjectIds = appendUniqueProjectId(plan.linkedProjectIds, record.project_id);
    const projectLinks = await resolveSdkPlanProjectLinks(this.client, linkedProjectIds);
    const response = await this.client.patch<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}`, await buildUpdateUserPlanInput(plan, masterKey, {
      primaryChatId: plan.primaryChatId,
      primaryChatKey: plan.primaryChatId ? await resolveSdkChatKey(this.client, plan.primaryChatId) : null,
      linkedProjectIds,
      linkedProjectKeys: projectLinks.linkedProjectKeys ?? [{ projectId: record.project_id, projectKey }],
    }));
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return toPublicPlan(await decryptUserPlan(response.plan, masterKey));
  }

  async removeFromProject(planId: string, projectId: string): Promise<PlanRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await decryptUserPlan(await this.getRawPlan(planId), masterKey);
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId);
    const linkedProjectIds = removeProjectId(plan.linkedProjectIds, resolvedProjectId);
    const projectLinks = await resolveSdkPlanProjectLinks(this.client, linkedProjectIds);
    const response = await this.client.patch<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}`, await buildUpdateUserPlanInput(plan, masterKey, {
      primaryChatId: plan.primaryChatId,
      primaryChatKey: plan.primaryChatId ? await resolveSdkChatKey(this.client, plan.primaryChatId) : null,
      linkedProjectIds,
      linkedProjectKeys: projectLinks.linkedProjectKeys,
    }));
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return toPublicPlan(await decryptUserPlan(response.plan, masterKey));
  }

  async history(planId: string, options: { limit?: number } = {}): Promise<Record<string, unknown>[]> {
    const resolvedPlanId = await resolveSdkPlanId(this.client, planId);
    const query = options.limit ? `?limit=${encodeURIComponent(String(options.limit))}` : "";
    const response = await this.client.get<{ entries?: Record<string, unknown>[] }>(`/v1/user-plans/${encodeURIComponent(resolvedPlanId)}/history${query}`);
    return response.entries ?? [];
  }

  private async getRawPlan(planId: string): Promise<UserPlanRecord> {
    if (!CANONICAL_UUID_PATTERN.test(planId)) {
      return (await this.resolveDecryptedPlan(planId, await this.client.masterKey())).encrypted;
    }
    try {
      const response = await this.client.get<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}`);
      if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
      return response.plan;
    } catch (error) {
      if (!(error instanceof OpenMatesApiError) || error.status !== 404) throw error;
    }
    return (await this.resolveDecryptedPlan(planId, await this.client.masterKey())).encrypted;
  }

  async restore(planId: string, options: { entryId: string; state?: "before" | "after" }): Promise<Record<string, unknown>> {
    const resolvedPlanId = await resolveSdkPlanId(this.client, planId);
    return await this.client.request<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(resolvedPlanId)}/restore`, {
      entry_id: options.entryId,
      state: options.state ?? "after",
    });
  }

  async ask(instruction: string, options: {
    create?: PlanCreateOptions;
    update?: { planId: string; patch: PlanUpdateOptions };
    updates?: Array<{ planId: string; patch: PlanUpdateOptions }>;
  } = {}): Promise<Record<string, unknown>> {
    const masterKey = await this.client.masterKey();
    const plannedCreate = !options.create && !options.update && !options.updates?.length
      ? (await this.client.request<{ proposed_plan?: PlanCreateOptions }>("/v1/user-plans/ask/plan", { instruction })).proposed_plan
      : undefined;
    const encryptedUpdates = options.updates
      ? await Promise.all(options.updates.map(async (update) => {
        const plan = await this.resolveDecryptedPlan(update.planId, masterKey);
        return { plan_id: plan.planId, patch: await buildUpdateUserPlanInput(plan, masterKey, update.patch) };
      }))
      : undefined;
    const response = await this.client.request<Record<string, unknown>>("/v1/user-plans/ask", {
      instruction,
      ...(options.create || plannedCreate ? { encrypted_create: await buildCreateUserPlanInput(masterKey, options.create ?? plannedCreate ?? { title: instruction, goal: instruction }) } : {}),
      ...(options.update ? await this.buildAskUpdate(options.update, masterKey) : {}),
      ...(encryptedUpdates ? { encrypted_updates: encryptedUpdates } : {}),
    });
    const records = Array.isArray(response.plans) ? response.plans as UserPlanRecord[] : response.plan ? [response.plan as UserPlanRecord] : [];
    return publicPlanAskResponse(response, (await decryptUserPlans(records, masterKey)).map(toPublicPlan));
  }

  async activate(planId: string, input: { chatId?: string | null } = {}): Promise<PlanRecord> {
    const resolvedChatId = input.chatId === undefined || input.chatId === null ? input.chatId : await resolveSdkChatId(this.client, input.chatId);
    const payload: Record<string, unknown> = { ...(input.chatId !== undefined ? { chat_id: resolvedChatId } : {}) };
    const existing = await this.getRawPlan(planId);
    if (typeof payload.chat_id === "string") {
      const decrypted = await decryptUserPlan(existing, await this.client.masterKey());
      payload.key_wrappers = await buildSdkPlanKeyWrappers(this.client, existing, {
        primaryChatId: payload.chat_id,
        linkedProjectIds: decrypted.linkedProjectIds,
        createdAt: typeof payload.updated_at === "number" ? payload.updated_at : undefined,
      });
    }
    const response = await this.client.request<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(existing.plan_id)}/activate`, payload);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    const record = response.plan.primary_chat_id || typeof payload.chat_id !== "string"
      ? response.plan
      : { ...response.plan, primary_chat_id: payload.chat_id };
    return toPublicPlan(await decryptUserPlan(record, await this.client.masterKey()));
  }

  async attach(planId: string, input: { chatId?: string | null } = {}): Promise<PlanRecord> {
    return this.activate(planId, input);
  }

  async start(planId: string): Promise<PlanRecord> {
    return this.update(planId, { status: "executing" });
  }

  async resume(planId: string): Promise<PlanRecord> {
    return this.update(planId, { status: "active" });
  }

  async complete(planId: string): Promise<PlanRecord> {
    const existing = await this.getRawPlan(planId);
    const response = await this.client.request<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(existing.plan_id)}/complete`, { version: existing.version });
    return toPublicPlan(await decryptUserPlan(response.plan ?? await this.getRawPlan(planId), await this.client.masterKey()));
  }

  async delete(planId: string, options: ConfirmedMutationOptions = {}): Promise<Record<string, unknown>> {
    requireConfirmed(options, "Plan deletion");
    const plan = await this.getRawPlan(planId);
    return this.client.delete(`/v1/user-plans/${encodeURIComponent(plan.plan_id)}?version=${encodeURIComponent(String(plan.version))}`);
  }

  private async addDependency(planId: string, target: WorkDependencyTarget): Promise<Record<string, unknown>> {
    const plan = await this.getRawPlan(planId);
    return this.client.request(`/v1/user-plans/${encodeURIComponent(plan.plan_id)}/dependencies`, { target_ref: `${target.kind}:${target.id}` });
  }

  private async removeDependency(planId: string, target: WorkDependencyTarget): Promise<Record<string, unknown>> {
    const plan = await this.getRawPlan(planId);
    return this.client.delete(`/v1/user-plans/${encodeURIComponent(plan.plan_id)}/dependencies/${target.kind}/${encodeURIComponent(target.id)}`);
  }

  private async listDependencies(planId: string): Promise<{ dependencies: Record<string, unknown>[]; blockers: Record<string, unknown>[] }> {
    const plan = await this.getRawPlan(planId);
    const response = await this.client.get<{ dependencies?: Record<string, unknown>[]; blockers?: Record<string, unknown>[] }>(`/v1/user-plans/${encodeURIComponent(plan.plan_id)}/dependencies`);
    return { dependencies: response.dependencies ?? [], blockers: response.blockers ?? [] };
  }

  private async listRevisions(planId: string): Promise<Record<string, unknown>[]> {
    const plan = await this.getRawPlan(planId);
    const response = await this.client.get<{ revisions?: Record<string, unknown>[] }>(`/v1/user-plans/${encodeURIComponent(plan.plan_id)}/revisions`);
    return response.revisions ?? [];
  }

  private async createRevision(planId: string): Promise<Record<string, unknown>> {
    const plan = await this.show(planId);
    const canonical = JSON.stringify(plan, Object.keys(plan).sort());
    const masterKey = await this.client.masterKey();
    const fingerprint = createHmac("sha256", masterKey).update(canonical).digest("hex");
    const raw = await this.getRawPlan(planId);
    const planKey = await planKeyFromRecord(raw, masterKey);
    const encryptedSnapshot = await encryptWithAesGcmCombined(canonical, planKey);
    return this.client.request(`/v1/user-plans/${encodeURIComponent(raw.plan_id)}/revisions`, {
      fingerprint,
      encrypted_snapshot: encryptedSnapshot,
      created_at: Math.floor(Date.now() / 1000),
    });
  }

  private async submitForReview(planId: string): Promise<{ revision: Record<string, unknown>; reviewUrl: string }> {
    const response = await this.createRevision(planId);
    const revision = response.revision as Record<string, unknown> | undefined;
    if (!revision?.revision_id) throw new OpenMatesApiError(500, { detail: "Plan revision response missing revision" });
    const plan = await this.getRawPlan(planId);
    return { revision, reviewUrl: `${this.client.webOrigin()}/plans/${encodeURIComponent(plan.plan_id)}/review?revision=${encodeURIComponent(String(revision.revision_id))}` };
  }

  private async decryptedPlanForChildren(planId: string, masterKey: Uint8Array): Promise<DecryptedUserPlan> {
    return this.resolveDecryptedPlan(planId, masterKey);
  }

  private async resolveDecryptedPlan(planId: string, masterKey: Uint8Array): Promise<DecryptedUserPlan> {
    if (!CANONICAL_UUID_PATTERN.test(planId)) {
      return findPlan(await decryptUserPlans(await this.listRaw({ activeOnly: false }), masterKey), planId);
    }
    try {
      return await decryptUserPlan(await this.getRawPlanById(planId), masterKey);
    } catch (error) {
      if (!(error instanceof OpenMatesApiError) || error.status !== 404) throw error;
    }
    return findPlan(await decryptUserPlans(await this.listRaw({ activeOnly: false }), masterKey), planId);
  }

  private async getRawPlanById(planId: string): Promise<UserPlanRecord> {
    const response = await this.client.get<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}`);
    if (!response.plan) throw new OpenMatesApiError(500, { detail: "User plan response missing plan" });
    return response.plan;
  }

  private async buildAskUpdate(
    update: { planId: string; patch: PlanUpdateOptions },
    masterKey: Uint8Array,
  ): Promise<{ encrypted_update: { plan_id: string; patch: UserPlanUpdateInput } }> {
    const plan = await this.resolveDecryptedPlan(update.planId, masterKey);
    return { encrypted_update: { plan_id: plan.planId, patch: await buildUpdateUserPlanInput(plan, masterKey, update.patch) } };
  }

  private async planKeyForChildren(plan: DecryptedUserPlan, masterKey: Uint8Array): Promise<Uint8Array> {
    return planKeyFromRecord(plan.encrypted, masterKey);
  }

  async createCriterion(planId: string, input: PlanCriterionCreateOptions): Promise<PlanCriterionRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ criterion?: UserPlanCriterionRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/criteria`, await buildCreatePlanCriterionInput(plan, masterKey, input));
    if (!response.criterion) throw new OpenMatesApiError(500, { detail: "User plan criterion response missing criterion" });
    return toPublicPlanCriterion(response.criterion, await this.planKeyForChildren(plan, masterKey));
  }

  async updateCriterion(planId: string, criterionId: string, input: PlanCriterionUpdateOptions): Promise<PlanCriterionRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const planKey = await this.planKeyForChildren(plan, masterKey);
    const payload: Partial<UserPlanCriterionRecord> = { updated_at: Math.floor(Date.now() / 1000) };
    if (input.status !== undefined) payload.status = input.status as UserPlanCriterionRecord["status"];
    if (input.required !== undefined) payload.required = input.required;
    if (input.linkedTaskIds !== undefined) payload.linked_task_ids = input.linkedTaskIds;
    if (input.verificationIds !== undefined) payload.verification_ids = input.verificationIds;
    if (input.evidence !== undefined) (payload as Record<string, unknown>).encrypted_evidence = await encryptWithAesGcmCombined(input.evidence, planKey);
    if (input.coverageNote !== undefined) (payload as Record<string, unknown>).encrypted_coverage_note = await encryptWithAesGcmCombined(input.coverageNote, planKey);
    if (input.waiverReason !== undefined) (payload as Record<string, unknown>).encrypted_waiver_reason = await encryptWithAesGcmCombined(input.waiverReason, planKey);
    const response = await this.client.patch<{ criterion?: UserPlanCriterionRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/criteria/${encodeURIComponent(criterionId)}`, payload);
    if (!response.criterion) throw new OpenMatesApiError(500, { detail: "User plan criterion response missing criterion" });
    return toPublicPlanCriterion(response.criterion, planKey);
  }

  async deleteCriterion(planId: string, criterionId: string): Promise<Record<string, unknown>> {
    return await this.client.delete<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/criteria/${encodeURIComponent(criterionId)}`);
  }

  async listCriteria(planId: string): Promise<PlanCriterionRecord[]> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const planKey = await this.planKeyForChildren(plan, masterKey);
    const response = await this.client.get<{ criteria?: UserPlanCriterionRecord[] }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/criteria`);
    return Promise.all((response.criteria ?? []).map((criterion) => toPublicPlanCriterion(criterion, planKey)));
  }

  async createVerification(planId: string, input: PlanVerificationCreateOptions): Promise<PlanVerificationRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/verification`, await buildCreatePlanVerificationInput(plan, masterKey, input));
    if (!response.verification) throw new OpenMatesApiError(500, { detail: "User plan verification response missing verification" });
    return toPublicPlanVerification(response.verification, await this.planKeyForChildren(plan, masterKey));
  }

  async updateVerification(planId: string, verificationId: string, input: PlanVerificationUpdateOptions): Promise<PlanVerificationRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.patch<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/verification/${encodeURIComponent(verificationId)}`, await buildUpdatePlanVerificationInput(plan, masterKey, input));
    if (!response.verification) throw new OpenMatesApiError(500, { detail: "User plan verification response missing verification" });
    return toPublicPlanVerification(response.verification, await this.planKeyForChildren(plan, masterKey));
  }

  async deleteVerification(planId: string, verificationId: string): Promise<Record<string, unknown>> {
    return await this.client.delete<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/verification/${encodeURIComponent(verificationId)}`);
  }

  async listVerifications(planId: string): Promise<PlanVerificationRecord[]> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const planKey = await this.planKeyForChildren(plan, masterKey);
    const response = await this.client.get<{ verifications?: UserPlanVerificationRecord[] }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/verification`);
    return Promise.all((response.verifications ?? []).map((verification) => toPublicPlanVerification(verification, planKey)));
  }

  async createAssumption(planId: string, input: PlanAssumptionCreateOptions): Promise<PlanAssumptionRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ assumption?: UserPlanAssumptionRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/assumptions`, await buildPlanAssumptionCreateInput(plan, masterKey, input));
    if (!response.assumption) throw new OpenMatesApiError(500, { detail: "User plan assumption response missing assumption" });
    return toPublicPlanAssumption(response.assumption, await this.planKeyForChildren(plan, masterKey));
  }

  async listAssumptions(planId: string): Promise<PlanAssumptionRecord[]> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const planKey = await this.planKeyForChildren(plan, masterKey);
    const response = await this.client.get<{ assumptions?: UserPlanAssumptionRecord[] }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/assumptions`);
    return Promise.all((response.assumptions ?? []).map((assumption) => toPublicPlanAssumption(assumption, planKey)));
  }

  async updateAssumption(planId: string, assumptionId: string, input: PlanAssumptionUpdateOptions): Promise<PlanAssumptionRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.patch<{ assumption?: UserPlanAssumptionRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/assumptions/${encodeURIComponent(assumptionId)}`, await buildPlanAssumptionUpdateInput(plan, masterKey, input));
    if (!response.assumption) throw new OpenMatesApiError(500, { detail: "User plan assumption response missing assumption" });
    return toPublicPlanAssumption(response.assumption, await this.planKeyForChildren(plan, masterKey));
  }

  async deleteAssumption(planId: string, assumptionId: string): Promise<Record<string, unknown>> {
    return await this.client.delete<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/assumptions/${encodeURIComponent(assumptionId)}`);
  }

  async createReferencePattern(planId: string, input: PlanReferencePatternCreateOptions): Promise<PlanReferencePatternRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ reference_pattern?: UserPlanReferencePatternRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/reference-patterns`, await buildPlanReferencePatternCreateInput(plan, masterKey, input));
    if (!response.reference_pattern) throw new OpenMatesApiError(500, { detail: "User plan reference pattern response missing reference_pattern" });
    return toPublicPlanReferencePattern(response.reference_pattern, await this.planKeyForChildren(plan, masterKey));
  }

  async listReferencePatterns(planId: string): Promise<PlanReferencePatternRecord[]> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const planKey = await this.planKeyForChildren(plan, masterKey);
    const response = await this.client.get<{ reference_patterns?: UserPlanReferencePatternRecord[] }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/reference-patterns`);
    return Promise.all((response.reference_patterns ?? []).map((pattern) => toPublicPlanReferencePattern(pattern, planKey)));
  }

  async updateReferencePattern(planId: string, patternId: string, input: PlanReferencePatternUpdateOptions): Promise<PlanReferencePatternRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.patch<{ reference_pattern?: UserPlanReferencePatternRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/reference-patterns/${encodeURIComponent(patternId)}`, await buildPlanReferencePatternUpdateInput(plan, masterKey, input));
    if (!response.reference_pattern) throw new OpenMatesApiError(500, { detail: "User plan reference pattern response missing reference_pattern" });
    return toPublicPlanReferencePattern(response.reference_pattern, await this.planKeyForChildren(plan, masterKey));
  }

  async deleteReferencePattern(planId: string, patternId: string): Promise<Record<string, unknown>> {
    return await this.client.delete<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/reference-patterns/${encodeURIComponent(patternId)}`);
  }

  async createLearning(planId: string, input: PlanLearningCreateOptions): Promise<PlanLearningRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ learning?: UserPlanLearningRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/learnings`, await buildCreatePlanLearningInput(plan, masterKey, input));
    if (!response.learning) throw new OpenMatesApiError(500, { detail: "User plan learning response missing learning" });
    return withoutEncryptedLearning(await decryptPlanLearning(plan, response.learning, masterKey));
  }

  async listLearnings(planId: string): Promise<PlanLearningRecord[]> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.get<{ learnings?: UserPlanLearningRecord[] }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/learnings`);
    return Promise.all((response.learnings ?? []).map(async (learning) => withoutEncryptedLearning(await decryptPlanLearning(plan, learning, masterKey))));
  }

  async updateLearning(planId: string, learningId: string, input: PlanLearningUpdateOptions): Promise<PlanLearningRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.patch<{ learning?: UserPlanLearningRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/learnings/${encodeURIComponent(learningId)}`, await buildUpdatePlanLearningInput(plan, masterKey, input));
    if (!response.learning) throw new OpenMatesApiError(500, { detail: "User plan learning response missing learning" });
    return withoutEncryptedLearning(await decryptPlanLearning(plan, response.learning, masterKey));
  }

  async deleteLearning(planId: string, learningId: string): Promise<Record<string, unknown>> {
    return await this.client.delete<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/learnings/${encodeURIComponent(learningId)}`);
  }

  async createLearningTasks(planId: string, input: UserPlanLearningCreateTasksInput): Promise<UserPlanLearningCreateTasksResult> {
    return await this.client.request<UserPlanLearningCreateTasksResult>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/learnings/create-tasks`, input);
  }

  async addVerificationEvidence(planId: string, verificationId: string, input: PlanVerificationEvidenceOptions): Promise<PlanVerificationRecord> {
    const masterKey = await this.client.masterKey();
    const plan = await this.decryptedPlanForChildren(planId, masterKey);
    const response = await this.client.request<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(plan.planId)}/verification/${encodeURIComponent(verificationId)}/evidence`, await buildPlanVerificationEvidenceInput(plan, masterKey, input));
    if (!response.verification) throw new OpenMatesApiError(500, { detail: "User plan verification response missing verification" });
    return toPublicPlanVerification(response.verification, await this.planKeyForChildren(plan, masterKey));
  }

  async getVerificationRun(planId: string, verificationId: string, runId: string): Promise<Record<string, unknown>> {
    return await this.client.get<Record<string, unknown>>(`/v1/user-plans/${encodeURIComponent(await resolveSdkPlanId(this.client, planId))}/verification/${encodeURIComponent(verificationId)}/runs/${encodeURIComponent(runId)}`);
  }
}

export class OpenMatesWorkflows {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async list(): Promise<WorkflowSummary[]> {
    const response = await this.client.get<{ workflows?: WorkflowSummary[] }>("/v1/workflows");
    return this.decryptWorkflowSlugs(response.workflows ?? []);
  }

  private async decryptWorkflowSlugs<T extends WorkflowSummary>(workflows: T[]): Promise<T[]> {
    const masterKey = await this.client.masterKey();
    return Promise.all(workflows.map((workflow) => this.decryptWorkflowSlug(workflow, masterKey)));
  }

  private async decryptWorkflowSlug<T extends WorkflowSummary>(workflow: T, masterKey?: Uint8Array): Promise<T> {
    const { encrypted_slug: encryptedSlug, slug_lookup_hash: _slugLookupHash, ...publicWorkflow } = workflow;
    if (!encryptedSlug) return publicWorkflow as T;
    return { ...publicWorkflow, slug: await decryptObjectSlug(encryptedSlug, masterKey ?? await this.client.masterKey()) } as T;
  }

  private async resolveId(workflowId: string): Promise<string> {
    if (CANONICAL_UUID_PATTERN.test(workflowId)) return workflowId;
    const workflows = await this.list();
    const exact = workflows.find((workflow) => workflow.id === workflowId);
    if (exact) return exact.id;
    const lower = workflowId.toLowerCase();
    const prefixMatches = workflowId.length >= 8 ? workflows.filter((workflow) => workflow.id.toLowerCase().startsWith(lower)) : [];
    if (prefixMatches.length > 1) throw new OpenMatesConfigError(`Workflow '${workflowId}' is ambiguous. Use the full workflow ID.`);
    if (prefixMatches.length === 1) return prefixMatches[0].id;
    const slugMatches = workflows.filter((workflow) => objectSlugMatches(workflow.slug, workflowId));
    if (slugMatches.length > 1) throw new OpenMatesConfigError(`Workflow slug '${workflowId}' is ambiguous. Use the full workflow ID.`);
    if (slugMatches.length === 1) return slugMatches[0].id;
    const normalizedTitle = workflowId.trim().toLowerCase().replace(/\s+/g, " ");
    const titleMatches = workflows.filter((workflow) => workflow.title.trim().toLowerCase().replace(/\s+/g, " ") === normalizedTitle);
    if (titleMatches.length > 1) throw new OpenMatesConfigError(`Workflow '${workflowId}' is ambiguous. Use the full workflow ID.`);
    if (titleMatches.length === 1) return titleMatches[0].id;
    throw new OpenMatesConfigError(`Workflow '${workflowId}' was not found.`);
  }

  async addToProject(workflowId: string, projectId: string, options: { folder?: string } = {}): Promise<ProjectItemRecord> {
    const { record, projectKey } = await resolveSdkProject(this.client, projectId);
    const workflow = await this.get(workflowId);
    return createSdkProjectItem(this.client, record.project_id, projectKey, {
      itemType: "workflow",
      targetId: workflow.id,
      displayName: workflow.title,
      folder: options.folder,
      metadata: { storage: "save_only_in_openmates", source: "sdk_add_to_project" },
    });
  }

  async removeFromProject(workflowId: string, projectId: string): Promise<{ deleted: boolean; deletedCount: number }> {
    const resolvedProjectId = await resolveSdkProjectId(this.client, projectId);
    const workflow = await this.get(workflowId);
    return deleteSdkProjectItemByTarget(this.client, resolvedProjectId, "workflow", workflow.id);
  }

  async temporary(): Promise<WorkflowSummary[]> {
    const response = await this.client.get<{ workflows?: WorkflowSummary[] }>("/v1/workflows/temporary");
    return this.decryptWorkflowSlugs(response.workflows ?? []);
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
    return { workflow: await this.decryptWorkflowSlug(response.workflow), validation: response.validation };
  }

  async updateFromYaml(workflowId: string, source: string): Promise<{ workflow: WorkflowDetail; validation: Record<string, unknown> }> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ workflow?: WorkflowDetail; validation?: Record<string, unknown> }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/yaml`, { source });
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing workflow" });
    if (!response.validation) throw new OpenMatesApiError(500, { detail: "Workflow YAML response missing validation" });
    return { workflow: await this.decryptWorkflowSlug(response.workflow), validation: response.validation };
  }

  async history(workflowId: string, options: { limit?: number } = {}): Promise<Record<string, unknown>[]> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const query = options.limit ? `?limit=${encodeURIComponent(String(options.limit))}` : "";
    const response = await this.client.get<{ entries?: Record<string, unknown>[] }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/history${query}`);
    return response.entries ?? [];
  }

  async restore(workflowId: string, options: { entryId: string; state?: "before" | "after" }): Promise<Record<string, unknown>> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return await this.client.request<Record<string, unknown>>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/restore`, {
      entry_id: options.entryId,
      state: options.state ?? "after",
    });
  }

  async ask(input: {
    instruction: string;
    create?: Record<string, unknown>;
    exactUpdate?: Record<string, unknown>;
    exactAction?: Record<string, unknown>;
    selectedObjectId?: string | null;
  }): Promise<Record<string, unknown>> {
    const selectedObjectId = typeof input.selectedObjectId === "string" && input.selectedObjectId
      ? await this.resolveId(input.selectedObjectId)
      : input.selectedObjectId;
    return await this.client.request<Record<string, unknown>>("/v1/workflows/ask", {
      instruction: input.instruction,
      ...(input.create ? { create: input.create } : {}),
      ...(input.exactUpdate ? { exact_update: input.exactUpdate } : {}),
      ...(input.exactAction ? { exact_action: input.exactAction } : {}),
      ...(input.selectedObjectId !== undefined ? { selected_object_id: selectedObjectId } : {}),
    });
  }

  async startInput(params: WorkflowInputStartParams): Promise<WorkflowInputSessionResult> {
    const selectedWorkflowId = typeof params.selectedWorkflowId === "string" && params.selectedWorkflowId
      ? await this.resolveId(params.selectedWorkflowId)
      : params.selectedWorkflowId;
    const selectedProjectId = typeof params.selectedProjectId === "string" && params.selectedProjectId
      ? await resolveSdkProjectId(this.client, params.selectedProjectId)
      : params.selectedProjectId;
    const response = await this.client.request<{ session?: WorkflowInputSessionResult }>("/v1/workflows/input", {
      ...(params.text !== undefined ? { text: params.text } : {}),
      input_type: params.inputType ?? "text",
      ...(params.audioRef !== undefined ? { audio_ref: params.audioRef } : {}),
      ...(params.selectedWorkflowId !== undefined ? { selected_workflow_id: selectedWorkflowId } : {}),
      ...(params.selectedProjectId !== undefined ? { selected_project_id: selectedProjectId } : {}),
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
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.get<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}`);
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow);
  }

  async create(params: {
    title: string;
    slug?: string;
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
    const resolvedSourceChatId = typeof params.sourceChatId === "string" && params.sourceChatId
      ? await resolveSdkChatId(this.client, params.sourceChatId)
      : params.sourceChatId;
    const masterKey = await this.client.masterKey();
    const slugMetadata = await buildEncryptedObjectSlugMetadata({
      value: params.slug ?? params.title,
      encryptionKey: masterKey,
      lookupKey: masterKey,
    });
    const response = await this.client.request<{ workflow?: WorkflowDetail }>("/v1/workflows", {
      title: params.title,
      encrypted_slug: slugMetadata.encrypted_slug,
      slug_lookup_hash: slugMetadata.slug_lookup_hash,
      ...(params.description !== undefined ? { description: params.description } : {}),
      graph: params.graph,
      enabled: params.enabled ?? false,
      run_content_retention: params.runContentRetention ?? "last_5",
      ...(params.lifecycle ? { lifecycle: params.lifecycle } : {}),
      ...(params.source ? { source: params.source } : {}),
      ...(params.sourceChatId !== undefined ? { source_chat_id: resolvedSourceChatId } : {}),
      ...(params.createdByAssistant !== undefined ? { created_by_assistant: params.createdByAssistant } : {}),
      ...(params.autoDeleteAt !== undefined ? { auto_delete_at: params.autoDeleteAt } : {}),
    });
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow, masterKey);
  }

  async update(
    workflowId: string,
    params: { title?: string; slug?: string; description?: string | null; graph?: WorkflowGraph; enabled?: boolean; runContentRetention?: WorkflowRunContentRetention },
  ): Promise<WorkflowDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const payload: Record<string, unknown> = {};
    if (params.title !== undefined) payload.title = params.title;
    if (params.description !== undefined) payload.description = params.description;
    if (params.graph !== undefined) payload.graph = params.graph;
    if (params.slug !== undefined) {
      const masterKey = await this.client.masterKey();
      const slugMetadata = await buildEncryptedObjectSlugMetadata({
        value: params.slug,
        encryptionKey: masterKey,
        lookupKey: masterKey,
      });
      payload.encrypted_slug = slugMetadata.encrypted_slug;
      payload.slug_lookup_hash = slugMetadata.slug_lookup_hash;
    }
    if (params.enabled !== undefined) payload.enabled = params.enabled;
    if (params.runContentRetention !== undefined) payload.run_content_retention = params.runContentRetention;
    const response = await this.client.patch<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}`, payload);
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow);
  }

  async enable(workflowId: string): Promise<WorkflowDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/enable`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow);
  }

  async disable(workflowId: string): Promise<WorkflowDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/disable`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow);
  }

  async delete(workflowId: string, options: ConfirmedMutationOptions = {}): Promise<{ deleted: boolean }> {
    requireConfirmed(options, "Deleting a workflow");
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return this.client.delete<{ deleted: boolean }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}`);
  }

  async keep(workflowId: string): Promise<WorkflowDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ workflow?: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/keep`, {});
    if (!response.workflow) throw new OpenMatesApiError(500, { detail: "Workflow response missing workflow" });
    return this.decryptWorkflowSlug(response.workflow);
  }

  async run(
    workflowId: string,
    params: { idempotencyKey: string; mode?: "manual" | "test"; input?: Record<string, unknown> },
  ): Promise<WorkflowRunDetail> {
    if (!params.idempotencyKey.trim()) throw new OpenMatesConfigError("Workflow run requires a stable idempotencyKey");
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/run`, {
      mode: params.mode ?? "manual",
      input: params.input ?? {},
    }, undefined, { "Idempotency-Key": params.idempotencyKey });
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async runs(workflowId: string): Promise<WorkflowRunDetail[]> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.get<{ runs?: WorkflowRunDetail[] }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/runs`);
    return response.runs ?? [];
  }

  async runDetail(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.get<{ run?: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/runs/${encodeURIComponent(runId)}`);
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async stepTest(
    workflowId: string,
    stepId: string,
    params: { input?: Record<string, unknown>; confirmed?: boolean } = {},
  ): Promise<WorkflowRunDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/steps/${encodeURIComponent(stepId)}/test`,
      { input: params.input ?? {}, confirmed: params.confirmed === true },
    );
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async cancelRun(workflowId: string, runId: string): Promise<WorkflowRunCancellationResult> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const result = await this.client.request<WorkflowRunCancellationResult>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/runs/${encodeURIComponent(runId)}/cancel`,
      {},
    );
    if (result.status !== "cancellation_requested" && result.status !== "cancelled") {
      throw new OpenMatesApiError(500, { detail: "Workflow response has invalid cancellation status" });
    }
    return result;
  }

  async respond(workflowId: string, runId: string, stepId: string, input: Record<string, unknown>): Promise<WorkflowRunDetail> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    const response = await this.client.request<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/runs/${encodeURIComponent(runId)}/respond`,
      { step_id: stepId, input },
    );
    if (!response.run) throw new OpenMatesApiError(500, { detail: "Workflow response missing run" });
    return response.run;
  }

  async upsertTemplateProjection(
    workflowId: string,
    params: WorkflowTemplateProjectionUpsertParams,
  ): Promise<WorkflowTemplateProjectionResult> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return this.client.put<WorkflowTemplateProjectionResult>(`/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/template-projection`, {
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
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return this.client.request<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/template-projection/revoke`,
      {},
    );
  }

  async unrevokeTemplateProjection(workflowId: string): Promise<WorkflowTemplateProjectionRevocationResult> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return this.client.request<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/template-projection/unrevoke`,
      {},
    );
  }

  async completeImportedBinding(
    workflowId: string,
    params: WorkflowTemplateBindingCompletionParams,
  ): Promise<WorkflowTemplateBindingCompletionResult> {
    const resolvedWorkflowId = await this.resolveId(workflowId);
    return this.client.request<WorkflowTemplateBindingCompletionResult>(
      `/v1/workflows/${encodeURIComponent(resolvedWorkflowId)}/binding-requirements/complete`,
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
    return this.decryptWorkflowSlug(response.workflow);
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

export class OpenMatesWikipedia {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async search(query: string, options: { language?: string; limit?: number } = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/wikipedia/search", {
      query,
      language: options.language ?? "en",
      limit: options.limit,
    }));
  }

  async summary(title: string, options: { language?: string } = {}): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(withQuery("/v1/wikipedia/summary", {
      title,
      language: options.language ?? "en",
    }));
  }
}

export class OpenMatesEmbeds {
  readonly preview: OpenMatesEmbedPreview;
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
    this.preview = new OpenMatesEmbedPreview(client);
  }

  async show(embedId: string): Promise<Record<string, unknown>> { return this.client.get<Record<string, unknown>>(`/v1/sdk/embeds/${encodeURIComponent(embedId)}`); }
  async addToProject(embedId: string, projectId: string, options: { folder?: string } = {}): Promise<ProjectItemRecord> {
    const { record, projectKey } = await resolveSdkProject(this.client, projectId);
    return createSdkProjectItem(this.client, record.project_id, projectKey, {
      itemType: "embed",
      targetId: embedId,
      displayName: embedId,
      folder: options.folder,
      metadata: { storage: "save_only_in_openmates", source: "sdk_add_to_project" },
    });
  }
  async removeFromProject(embedId: string, projectId: string): Promise<{ deleted: boolean; deletedCount: number }> {
    return deleteSdkProjectItemByTarget(this.client, await resolveSdkProjectId(this.client, projectId), "embed", embedId);
  }
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

  async createPlain(input: TeamPlainCreateOptions): Promise<Record<string, unknown>> {
    const generatedProfile = generatedTeamProfileImageMetadata(input.profile);
    const created = await buildTeamPlainCreatePayload(this.client, input);
    const result = await this.client.request<{ team?: Record<string, unknown> }>("/v1/teams", created);
    return { ...(result.team ?? result), profile_image_metadata: generatedProfile };
  }

  async update(teamId: string, input: Record<string, unknown>): Promise<Record<string, unknown>> {
    const result = await this.client.patch<{ team?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}`, input);
    return result.team ?? result;
  }

  async updateGeneratedProfileImage(teamId: string, input: TeamGeneratedProfileImageOptions = {}): Promise<Record<string, unknown>> {
    const profile = generatedTeamProfileImageMetadata(input);
    const current = await this.get(teamId);
    const teamKey = await teamKeyForRecord(this.client, current);
    const result = await this.client.patch<{ team?: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(teamId)}`, {
      encrypted_profile_image_metadata: await encryptWithAesGcmCombined(JSON.stringify(profile), teamKey),
      updated_at: Math.floor(Date.now() / 1000),
    });
    return { ...(result.team ?? result), profile_image_metadata: profile };
  }

  async getProfileImage(teamId: string): Promise<{ contentType: string; filename?: string; data: ArrayBuffer }> {
    return this.client.getRaw(`/v1/teams/${encodeURIComponent(teamId)}/profile-image`);
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

  async usage(teamId: string, memberUserId?: string): Promise<Record<string, unknown>[]> {
    const query = memberUserId ? `?member_user_id=${encodeURIComponent(memberUserId)}` : "";
    const result = await this.client.get<{ usage?: Record<string, unknown>[] }>(`/v1/teams/${encodeURIComponent(teamId)}/billing/usage${query}`);
    return result.usage ?? [];
  }

  async createBankTransferOrder(teamId: string, credits: number, options: BankTransferOrderOptions = {}): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(
      `/v1/teams/${encodeURIComponent(teamId)}/billing/bank-transfer-orders`,
      { credits_amount: credits, currency: "eur", email_encryption_key: options.emailEncryptionKey },
    );
  }

  async bankTransferStatus(teamId: string, orderId: string): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}/billing/bank-transfer-orders/${encodeURIComponent(orderId)}`);
  }

  async listBankTransferOrders(teamId: string): Promise<Record<string, unknown>> {
    return this.client.get<Record<string, unknown>>(`/v1/teams/${encodeURIComponent(teamId)}/billing/bank-transfer-orders`);
  }

  async memories(teamId: string): Promise<Record<string, unknown>[]> {
    const result = await this.client.get<{ memories?: Record<string, unknown>[] }>(`/v1/teams/${encodeURIComponent(teamId)}/memories`);
    return result.memories ?? [];
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

export class OpenMatesFinance {
  private readonly client: OpenMates;

  constructor(client: OpenMates) {
    this.client = client;
  }

  async checkAccounts(
    input: FinanceCheckAccountsInput,
    options: ConnectedAccountSkillRunOptions = {},
  ): Promise<Record<string, unknown>> {
    return this.client.runConnectedAccountSkill<Record<string, unknown>>(
      "finance",
      "check_accounts",
      input,
      options,
    );
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
