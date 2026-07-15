/*
 * OpenMates CLI SDK client.
 *
 * Purpose: expose pair-auth, chat, app-skill, settings, and memories operations.
 * Architecture: REST for auth/settings/apps + WebSocket for chat and memory ops.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: pair-auth only for account login; no terminal credential prompts.
 * Tests: frontend/packages/openmates-cli/tests/
 */

import { randomUUID } from "node:crypto";
import { arch, platform, release } from "node:os";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import qrcode from "qrcode-terminal";

import {
  decryptBundle,
  decryptWithAesGcmCombined,
  decryptBytesWithAesGcm,
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  deriveEmbedKeyFromChatKey,
  deriveEmailEncryptionKeyB64,
  encryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  base64ToBytes,
  hashItemKey,
  createRecoveryKeyMaterial,
  createApiKeyCryptoMaterial,
  createSignupCryptoMaterial,
  hashEmail,
  type RecoveryKeyMaterial,
  type ApiKeyCryptoMaterial,
  type ChatCompletionRecoveryEnvelope,
  type SignupCryptoMaterial,
} from "./crypto.js";
import { OpenMatesHttpClient } from "./http.js";
import {
  type OpenMatesSession,
  type SyncCache,
  type CachedChat,
  loadSession,
  saveSession,
  clearSession,
  loadSyncCache,
  saveSyncCache,
  clearSyncCache,
  isSyncCacheFresh,
  loadAnonymousId,
  saveAnonymousId,
} from "./storage.js";
import { loadServerConfig } from "./serverConfig.js";
import {
  OpenMatesWsClient,
  type AppSettingsMemoriesRequestEvent,
  type SendEmbedDataFrame,
  type SubChatEvent,
  type TaskEventFrame,
  type PendingTaskUpdateJobFrame,
  type TaskProposalEvent,
  type TaskUpdateProposalEvent,
} from "./ws.js";
import type { MentionContext, AppInfo, MemoryEntryInfo } from "./mentions.js";
import { CHAT_MODELS } from "./mentions.js";
import type { EncryptedEmbed, EmbedKeyWrapper, PreparedEmbed } from "./embedCreator.js";
import { computeSHA256, encryptEmbed } from "./embedCreator.js";
import {
  generateChatShareBlob,
  generateEmbedShareBlob,
  deriveWebOrigin,
  buildChatShareUrl,
  buildEmbedShareUrl,
  type ShareDuration,
} from "./shareEncryption.js";
import {
  buildEncryptedConnectedAccountImportRow,
  decryptConnectedAccountCliTransferPayload,
  type ConnectedAccountCliTransferPayload,
  type EncryptedConnectedAccountImportRow,
} from "./connectedAccountImport.js";
import { containsCredentialLikeField, type ProtonLocalConnectorRegistration } from "./protonBridgeConnector.js";
import {
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptUserTasks,
  findTask,
  type DecryptedUserTask,
} from "./tasksCli.js";

function normalizeUnixSeconds(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  return value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value);
}

export function getClientMessagesVersionForSync(cached: CachedChat): number {
  if (cached.messages.length === 0) return 0;
  return typeof cached.details.messages_v === "number" ? cached.details.messages_v : 0;
}

interface PendingAIResponseFrame {
  chat_id?: string;
  message_id?: string;
  content?: string;
  fired_at?: number;
  model_name?: string;
  category?: string;
}

export interface CliSubChatRequest {
  id?: string;
  chat_id?: string;
  user_message_id?: string;
  message_id?: string;
  prompt?: string;
  wait_for_completion?: boolean;
}

export interface SubChatEncryptedMetadataPayload {
  chat_id: string;
  parent_id: string;
  is_sub_chat: true;
  message_id: string;
  encrypted_content: string;
  encrypted_sender_name: string;
  encrypted_title: string;
  created_at: number;
  encrypted_chat_key?: string | null;
  versions: {
    messages_v: number;
    title_v: number;
    last_edited_overall_timestamp: number;
  };
}

export interface SubChatApprovalRequest {
  chatId: string;
  taskId: string;
  subChats: CliSubChatRequest[];
  maxAutoSubChats: number | null;
  maxDirectSubChats: number | null;
  existingSubChats: number | null;
  remainingSubChats: number | null;
}

export interface ConnectedAccountDirectoryEntry {
  connected_account_id: string;
  app_id: string;
  account_ref: string;
  label: string;
  capabilities: string[];
  runtime_modes?: Record<string, string>;
}

export interface ConnectedAccountTurnTokenRefInput {
  connected_account_id: string;
  app_id: string;
  allowed_actions: string[];
  refresh_token_envelope: Record<string, unknown>;
  action_scope?: Record<string, unknown>;
}

export interface ConnectedAccountTurnTokenRef {
  connected_account_id: string;
  app_id: string;
  turn_token_ref: string;
  allowed_actions: string[];
  action_scope?: Record<string, unknown>;
  expires_at: number;
}

export interface ConnectedAccountImportValidationResult {
  valid: boolean;
  provider_id: string;
  app_id: string;
  checked_at: number;
}

export interface ConnectedAccountImportResult {
  id: string;
  providerId: string;
  appId: string;
  label: string;
  validation: ConnectedAccountImportValidationResult;
}

export type LearningModeAgeGroup = "under_10" | "10_12" | "13_15" | "16_18" | "adult";

export interface LearningModeStatus {
  enabled: boolean;
  age_group: LearningModeAgeGroup | null;
  failed_attempts: number;
  deactivation_blocked_until: number | null;
}

export interface LearningModeContext {
  enabled: boolean;
  ageGroup?: LearningModeAgeGroup | null;
  source?: "anonymous_session";
}

export type WorkflowNodeType =
  | "schedule_trigger"
  | "manual_trigger"
  | "webhook_trigger"
  | "app_skill_action"
  | "decision"
  | "repeat"
  | "create_chat_report"
  | "send_notification"
  | "send_email_notification"
  | "ask_user"
  | "custom_code"
  | "end";

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  title?: string | null;
  config?: Record<string, unknown>;
  input_mapping?: Record<string, unknown>;
  ui?: Record<string, unknown>;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  branch?: string | null;
}

export interface WorkflowGraph {
  version: number;
  trigger_node_id: string;
  nodes: WorkflowNode[];
  edges?: WorkflowEdge[];
  variables?: Record<string, unknown>;
  limits?: Record<string, unknown>;
  ui_layout?: Record<string, unknown>;
}

export type WorkflowRunContentRetention = "last_5" | "none";
export type WorkflowRunContentStorage = "durable" | "ephemeral" | "deleted";
export type WorkflowLifecycle = "persisted" | "temporary";

export interface WorkflowSummary {
  id: string;
  title: string;
  description?: string | null;
  status: "draft" | "active" | "disabled" | "error" | "deleted";
  enabled: boolean;
  lifecycle?: WorkflowLifecycle;
  source?: string;
  source_chat_id?: string | null;
  created_by_assistant?: boolean;
  auto_delete_at?: number | null;
  kept_at?: number | null;
  trigger_summary?: string | null;
  next_run_at?: number | null;
  last_run_status?: "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled" | null;
  run_content_retention?: WorkflowRunContentRetention;
  current_version_id: string;
  created_at: number;
  updated_at: number;
}

export interface WorkflowDetail extends WorkflowSummary {
  graph: WorkflowGraph;
}

export interface WorkflowNodeRun {
  id: string;
  run_id: string;
  workflow_id: string;
  node_id: string;
  node_type: WorkflowNodeType;
  status: "queued" | "running" | "completed" | "skipped" | "failed";
  started_at?: number | null;
  finished_at?: number | null;
  skipped_reason?: string | null;
  error_code?: string | null;
  error_summary?: string | null;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  credit_cost?: number;
}

export type UserTaskStatus = "backlog" | "todo" | "in_progress" | "blocked" | "done";
export type UserTaskAssigneeType = "ai" | "user";

export type ProjectSourceType = "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
export type ProjectSourceCapability = "read" | "search" | "import" | "write_request";
export type ProjectSourceStatus = "connected" | "offline" | "permission_required" | "revoked";

export interface ProjectSourceRecord {
  source_id: string;
  source_type: ProjectSourceType;
  encrypted_display_name: string;
  encrypted_metadata: string;
  capabilities?: ProjectSourceCapability[];
  status?: ProjectSourceStatus;
  created_at?: number;
  updated_at?: number;
  last_indexed_at?: number | null;
  [key: string]: unknown;
}

export type ProjectSourceCreateInput = ProjectSourceRecord;

export interface UserTaskRecord {
  task_id: string;
  source?: string | null;
  title?: string | null;
  read_only?: boolean | null;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  run_status?: string | null;
  blocked_reason?: string | null;
  blocked_message?: string | null;
  short_id?: string | null;
  short_id_prefix?: string | null;
  encrypted_task_key?: string | null;
  encrypted_title: string;
  encrypted_description?: string | null;
  encrypted_tags?: string | null;
  encrypted_linked_project_ids?: string | null;
  encrypted_activity_summary?: string | null;
  encrypted_latest_instruction?: string | null;
  status: UserTaskStatus;
  assignee_type: UserTaskAssigneeType;
  assignee_hash?: string | null;
  primary_chat_id?: string | null;
  linked_project_ids?: string[] | null;
  parent_task_id?: string | null;
  plan_id?: string | null;
  plan_step_id?: string | null;
  task_type?: "work" | "verification" | null;
  verification_id?: string | null;
  due_at?: number | null;
  priority?: number;
  position?: number;
  queue_state?: "none" | "waiting" | "active" | "skipped" | "waiting_for_user" | string | null;
  version?: number;
  created_at?: number;
  updated_at?: number;
  started_at?: number | null;
  completed_at?: number | null;
  blocked_reason_code?: string | null;
  ai_execution_state?: string | null;
}

export interface UserTaskProposalRecord {
  title: string;
  description?: string | null;
  status?: UserTaskStatus;
  assignee_type?: UserTaskAssigneeType;
}

export type UserTaskCreateInput = Omit<UserTaskRecord, "version" | "started_at" | "completed_at" | "blocked_reason_code" | "ai_execution_state"> & { version: number };

export type UserTaskUpdateInput = Partial<Omit<UserTaskRecord, "task_id" | "created_at" | "version">> & { version: number };

export type UserTaskStartAIInput = UserTaskUpdateInput & {
  plaintext_title?: string;
  plaintext_description?: string;
  plaintext_latest_instruction?: string;
  plaintext_chat_title?: string;
};

export type UserTaskActionInput = { version: number; blocked_reason_code?: string | null };
export type UserTaskReorderInput = {
  moves: Array<{
    task_id: string;
    version: number;
    before_task_id?: string | null;
    after_task_id?: string | null;
    status?: UserTaskStatus | null;
    position?: number | null;
  }>;
};

export type UserPlanStatus = "draft" | "awaiting_confirmation" | "active" | "executing" | "blocked" | "completed" | "archived";
export type UserPlanCriterionStatus = "pending" | "satisfied" | "failed" | "waived";
export type UserPlanVerificationStatus = "pending" | "passed" | "failed" | "passed_unexpectedly" | "skipped" | "waived";

export interface UserPlanRecord {
  plan_id: string;
  encrypted_plan_key?: string | null;
  encrypted_title: string;
  encrypted_summary?: string | null;
  encrypted_goal?: string | null;
  encrypted_scope_in?: string | null;
  encrypted_scope_out?: string | null;
  encrypted_assumptions?: string | null;
  encrypted_open_questions?: string | null;
  encrypted_constraints?: string | null;
  encrypted_decisions?: string | null;
  encrypted_risks?: string | null;
  status: UserPlanStatus;
  primary_chat_id?: string | null;
  linked_project_ids?: string[] | null;
  current_phase_id?: string | null;
  current_step_id?: string | null;
  current_task_id?: string | null;
  planner_focus_id?: string | null;
  version?: number;
  created_at?: number;
  updated_at?: number;
  completed_at?: number | null;
}

export type UserPlanCreateInput = Omit<UserPlanRecord, "version" | "completed_at"> & { version?: number };
export type UserPlanUpdateInput = Partial<Omit<UserPlanRecord, "plan_id" | "created_at">> & { version?: number };

export interface UserPlanCriterionRecord {
  criterion_id: string;
  encrypted_text: string;
  type?: string;
  status?: UserPlanCriterionStatus;
  required?: boolean;
  linked_step_ids?: string[];
  linked_task_ids?: string[];
  verification_ids?: string[];
  created_at?: number;
  updated_at?: number;
}

export interface UserPlanVerificationRecord {
  verification_id: string;
  kind: string;
  phase?: string;
  status?: UserPlanVerificationStatus;
  required_for_done?: boolean;
  covers?: string[];
  threshold?: number | null;
  score?: number | null;
  confidence?: string | null;
  linked_task_id?: string | null;
  run_id?: string | null;
  created_at?: number;
  updated_at?: number;
  encrypted_command?: string | null;
  encrypted_evaluation_prompt?: string | null;
  encrypted_expected_result?: string | null;
  encrypted_result_summary?: string | null;
  encrypted_required_fixes?: string | null;
}

export interface WorkflowRunDetail {
  id: string;
  workflow_id: string;
  version_id: string;
  trigger_type: string;
  status: "queued" | "running" | "waiting" | "cancellation_requested" | "completed" | "failed" | "cancelled";
  started_at?: number | null;
  finished_at?: number | null;
  error_summary?: string | null;
  cost_summary?: Record<string, unknown>;
  content_retention_mode?: WorkflowRunContentRetention;
  content_available?: boolean;
  content_storage?: WorkflowRunContentStorage | null;
  content_expires_at?: number | null;
  encrypted_content_ref?: string | null;
  encrypted_content_checksum?: string | null;
  node_runs?: WorkflowNodeRun[];
  output_summary?: Record<string, unknown>;
}

export interface WorkflowRunCancellationResult {
  run_id: string;
  status: "cancellation_requested" | "cancelled";
}

export type WorkflowInputType = "text" | "audio";

export interface WorkflowInputStartParams {
  text?: string | null;
  inputType?: WorkflowInputType;
  audioRef?: Record<string, unknown> | null;
  selectedWorkflowId?: string | null;
  selectedProjectId?: string | null;
}

export interface WorkflowInputEvent {
  id: string;
  session_id: string;
  event_id: number;
  type: string;
  status: string;
  redacted_summary: string;
  payload?: Record<string, unknown>;
  created_at: number;
}

export interface WorkflowInputSessionResult {
  session_id: string;
  status: string;
  event_cursor: number;
  message?: string | null;
  error?: string | null;
  workflow?: WorkflowDetail | null;
  project_item?: Record<string, unknown> | null;
  undo_available: boolean;
}

export interface WorkflowInputSessionDetail extends WorkflowInputSessionResult {
  events: WorkflowInputEvent[];
  draft_graph?: Record<string, unknown> | null;
  mutations?: Array<Record<string, unknown>>;
}

export interface WorkflowCapability {
  type: "node" | "app_skill" | "workflow";
  id: string;
  title: string;
  enabled: boolean;
  reason?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorkflowTemplateProjectionUpsertParams {
  templateId: string;
  sourceVersion: number;
  ciphertext: string;
  ciphertextChecksum: string;
  ownerWrappedKey: string;
  projectionSchemaVersion: number;
}

export interface WorkflowTemplateProjectionResult {
  template_id: string;
  source_version: number;
  updated_at: number;
}

export interface PublicWorkflowTemplateProjection {
  template_id: string;
  ciphertext: string;
  ciphertext_checksum: string;
  projection_schema_version: number;
}

export interface WorkflowTemplateProjectionRevocationResult {
  template_id: string;
  revoked_at: number | null;
}

export interface WorkflowTemplateBindingCompletionParams {
  type: string;
  nodeId: string;
}

export interface WorkflowTemplateBindingCompletionResult {
  workflow_id: string;
  binding_requirement: Record<string, unknown>;
  completed: boolean;
}

export interface WorkflowTemplateImportPayload {
  template_version: number;
  title: string;
  description?: string | null;
  trigger_template: Record<string, unknown>;
  node_templates?: Array<Record<string, unknown>>;
  edge_templates?: Array<Record<string, unknown>>;
  variables_schema?: Record<string, unknown>;
  required_capabilities?: string[];
  binding_requirements?: Array<Record<string, unknown>>;
}

export interface ImportedWorkflowTemplate extends WorkflowDetail {
  binding_requirements: Array<Record<string, unknown>>;
}

export interface WorkflowTemplateShortUrlParams {
  token: string;
  encryptedUrl: string;
  templateId: string;
  ttlSeconds?: number | null;
  passwordProtected?: boolean;
}

export interface WorkflowTemplateShortUrlResult {
  success: boolean;
  expires_at?: number | null;
}

export interface ShortUrlRevokeResult {
  success: boolean;
  revoked_at?: number | null;
}

export type InterestTagId =
  | "software_development"
  | "business_development"
  | "life_coach_psychology"
  | "medical_health"
  | "legal_law"
  | "finance"
  | "design"
  | "marketing_sales"
  | "science"
  | "history"
  | "cooking_food"
  | "electrical_engineering"
  | "maker_prototyping"
  | "movies_tv"
  | "activism"
  | "general_knowledge"
  | "find_events"
  | "find_restaurant"
  | "find_doctor_appointments"
  | "plot_charts"
  | "video_tutorials"
  | "find_apartments"
  | "build_electronics"
  | "diy_projects"
  | "create_videos"
  | "find_travel_connections"
  | "plan_trips"
  | "discuss_news"
  | "discuss_videos"
  | "run_code"
  | "privacy"
  | "learning"
  | "writing";

export interface TopicPreferencesPayload {
  version: 1;
  selectedTagIds: InterestTagId[];
  updatedAt: string;
}

export const INTEREST_TAG_IDS: InterestTagId[] = [
  "software_development",
  "business_development",
  "life_coach_psychology",
  "medical_health",
  "legal_law",
  "finance",
  "design",
  "marketing_sales",
  "science",
  "history",
  "cooking_food",
  "electrical_engineering",
  "maker_prototyping",
  "movies_tv",
  "activism",
  "general_knowledge",
  "find_events",
  "find_restaurant",
  "find_doctor_appointments",
  "plot_charts",
  "video_tutorials",
  "find_apartments",
  "build_electronics",
  "diy_projects",
  "create_videos",
  "find_travel_connections",
  "plan_trips",
  "discuss_news",
  "discuss_videos",
  "run_code",
  "privacy",
  "learning",
  "writing",
];

const TOPIC_PREFERENCES_SETTINGS_KEY = "topic_preferences";

export function normalizeInterestTagIds(values: readonly string[]): InterestTagId[] {
  const validIds = new Set<InterestTagId>(INTEREST_TAG_IDS);
  const normalized: InterestTagId[] = [];
  for (const value of values) {
    if (!validIds.has(value as InterestTagId)) {
      throw new Error(
        `Unknown interest tag '${value}'. Use one of: ${INTEREST_TAG_IDS.join(", ")}`,
      );
    }
    if (!normalized.includes(value as InterestTagId)) {
      normalized.push(value as InterestTagId);
    }
  }
  return normalized;
}

function normalizeTopicPreferencesPayload(value: unknown): TopicPreferencesPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const candidate = value as Partial<TopicPreferencesPayload>;
  if (candidate.version !== 1 || !Array.isArray(candidate.selectedTagIds)) {
    return null;
  }
  const validIds = new Set<InterestTagId>(INTEREST_TAG_IDS);
  const selectedTagIds: InterestTagId[] = [];
  for (const value of candidate.selectedTagIds) {
    if (validIds.has(value as InterestTagId) && !selectedTagIds.includes(value as InterestTagId)) {
      selectedTagIds.push(value as InterestTagId);
    }
  }
  return {
    version: 1,
    selectedTagIds,
    updatedAt:
      typeof candidate.updatedAt === "string"
        ? candidate.updatedAt
        : new Date(0).toISOString(),
  };
}

export interface AppSettingsMemorySystemMessage {
  message_id: string;
  role: "system";
  content: string;
  created_at: number;
  user_message_id: string;
}

type AppSettingsMemoryResponseCategory = {
  appId: string;
  itemType: string;
  entryCount: number;
};

export function buildSubChatConfirmationPayload(params: {
  chatId: string;
  taskId: string;
  approved: boolean;
  approveCount?: number;
}): {
  chat_id: string;
  task_id: string;
  action: "approve" | "cancel";
  approve_count: number | null;
} {
  return {
    chat_id: params.chatId,
    task_id: params.taskId,
    action: params.approved ? "approve" : "cancel",
    approve_count: params.approved ? params.approveCount ?? null : null,
  };
}

export function assertNoConnectedAccountSecretLeak(value: unknown): void {
  const serialized = JSON.stringify(value ?? {});
  const forbidden = [
    "refresh_token",
    "access_token",
    "provider_email",
    "account_email",
    "provider_account_id",
    "bridge_password",
    "imap_password",
    "smtp_password",
    "proton_password",
    "password",
  ];
  for (const key of forbidden) {
    if (serialized.includes(`"${key}"`)) {
      throw new Error(`Connected account payload contains forbidden field: ${key}`);
    }
  }
  if (containsCredentialLikeField(value)) {
    throw new Error("Connected account payload contains credential-like fields.");
  }
}

export function buildConnectedAccountDirectoryPayload(
  entries: ConnectedAccountDirectoryEntry[] | undefined,
): ConnectedAccountDirectoryEntry[] | undefined {
  if (!entries || entries.length === 0) return undefined;
  assertNoConnectedAccountSecretLeak(entries);
  return entries.map((entry) => ({ ...entry, capabilities: [...entry.capabilities] }));
}

export function buildTurnTokenRefsRequestPayload(params: {
  chatId: string;
  messageId: string;
  refs: ConnectedAccountTurnTokenRefInput[];
}): {
  chat_id: string;
  message_id: string;
  refs: ConnectedAccountTurnTokenRefInput[];
} {
  return {
    chat_id: params.chatId,
    message_id: params.messageId,
    refs: params.refs.map((ref) => ({ ...ref })),
  };
}

function categoryFromMemoryKey(key: string): { appId: string; itemType: string } | null {
  const separator = key.indexOf("-");
  if (separator <= 0 || separator === key.length - 1) return null;
  return {
    appId: key.slice(0, separator),
    itemType: key.slice(separator + 1),
  };
}

export function buildAppSettingsMemoryRequestSystemMessage(params: {
  userMessageId: string;
  requestId: string;
  requestedKeys: string[];
  createdAt: number;
}): AppSettingsMemorySystemMessage {
  const seen = new Set<string>();
  const categories: Array<{ appId: string; itemType: string; entryCount: number }> = [];
  for (const key of params.requestedKeys) {
    if (seen.has(key)) continue;
    seen.add(key);
    const parsed = categoryFromMemoryKey(key);
    if (!parsed) continue;
    categories.push({
      ...parsed,
      entryCount: 0,
    });
  }

  return {
    message_id: params.requestId,
    role: "system",
    content: JSON.stringify({
      type: "app_settings_memories_request",
      user_message_id: params.userMessageId,
      request_id: params.requestId,
      requested_keys: params.requestedKeys,
      categories,
    }),
    created_at: params.createdAt,
    user_message_id: params.userMessageId,
  };
}

export function buildAppSettingsMemoryResponseSystemMessage(params: {
  userMessageId: string;
  messageId: string;
  action: "included" | "rejected";
  categories?: AppSettingsMemoryResponseCategory[];
  createdAt: number;
}): AppSettingsMemorySystemMessage {
  return {
    message_id: params.messageId,
    role: "system",
    content: JSON.stringify({
      type: "app_settings_memories_response",
      user_message_id: params.userMessageId,
      action: params.action,
      categories: params.action === "included" ? params.categories : undefined,
    }),
    created_at: params.createdAt,
    user_message_id: params.userMessageId,
  };
}

export async function buildTaskEventSystemMessage(params: {
  chatKey: Uint8Array;
  userMessageId: string;
  event: TaskEventFrame;
}): Promise<{
  message_id: string;
  role: "system";
  encrypted_content: string;
  created_at: number;
  user_message_id: string;
  task_update_job_id?: string;
}> {
  const content = formatTaskEventSystemContent(params.event);
  const message: {
    message_id: string;
    role: "system";
    encrypted_content: string;
    created_at: number;
    user_message_id: string;
    task_update_job_id?: string;
  } = {
    message_id: `task-event-${params.event.event_id}`,
    role: "system",
    encrypted_content: await encryptWithAesGcmCombined(content, params.chatKey),
    created_at: params.event.created_at ?? Math.floor(Date.now() / 1000),
    user_message_id: params.userMessageId,
  };
  if (params.event.task_update_job_id) message.task_update_job_id = params.event.task_update_job_id;
  return message;
}

export function taskUpdateJobBelongsToActiveTurn(
  job: PendingTaskUpdateJobFrame,
  activeChatId: string,
  taskEvents: TaskEventFrame[],
): boolean {
  void activeChatId;
  return taskEvents.some((event) => event.task_update_job_id === job.job_id);
}

export function buildTaskUpdateJobPersistPayload(params: {
  jobId: string;
  leaseToken: string;
  leaseGeneration: number;
  expectedTaskVersion: number;
  encryptedTaskPayload: Record<string, unknown>;
  encryptedTaskEventMessage?: string | null;
}): {
  protocol_version: 1;
  job_id: string;
  lease_token?: string | null;
  lease_generation?: number | null;
  expected_task_version: number;
  encrypted_task_payload: Record<string, unknown>;
  encrypted_task_event_message?: string | null;
} {
  const encryptedTaskPayload = pruneAbsentTaskPersistFields(params.encryptedTaskPayload);
  assertTaskPersistPayloadEncrypted(encryptedTaskPayload);
  return {
    protocol_version: 1,
    job_id: params.jobId,
    lease_token: params.leaseToken,
    lease_generation: params.leaseGeneration,
    expected_task_version: params.expectedTaskVersion,
    encrypted_task_payload: encryptedTaskPayload,
    encrypted_task_event_message: params.encryptedTaskEventMessage ?? null,
  };
}

function pruneAbsentTaskPersistFields(payload: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined && value !== null),
  );
}

function formatTaskEventSystemContent(event: TaskEventFrame): string {
  const taskLabel = event.short_id || event.task_id;
  const title = event.title ? ` "${event.title}"` : "";
  const status = event.status ? ` (${event.status})` : "";
  const reason = event.reason ? `: ${event.reason}` : "";
  switch (event.event_type) {
    case "created":
      return `${taskLabel} created${title}${status}`;
    case "updated":
      return `${taskLabel} updated${title}${status}`;
    case "blocked":
      return `${taskLabel} blocked${reason}`;
    case "completed":
      return `${taskLabel} completed${title}`;
    case "unblocked":
      return `${taskLabel} unblocked`;
    default:
      return `${taskLabel} ${event.event_type}${title}${status}${reason}`;
  }
}

function assertTaskPersistPayloadEncrypted(payload: Record<string, unknown>): void {
  const allowedSafeKeys = new Set([
    "assignee_hash",
    "assignee_type",
    "blocked_reason_code",
    "created_at",
    "key_wrappers",
    "linked_project_ids",
    "position",
    "primary_chat_id",
    "priority",
    "status",
    "task_id",
    "updated_at",
    "version",
  ]);
  for (const key of Object.keys(payload)) {
    if (key.startsWith("encrypted_") || allowedSafeKeys.has(key)) {
      continue;
    }
    throw new Error("Task update job payload contains plaintext or unsupported field");
  }
}

interface TaskUpdateJobClaimPayload {
  job_id: string;
  task_id: string;
  chat_id?: string | null;
  source_task_chat_id?: string | null;
  message_id?: string | null;
  operation?: string | null;
  state?: string | null;
  lease_token: string;
  lease_generation: number;
  expected_task_version: number;
  private_patch?: Record<string, unknown>;
  safe_metadata?: Record<string, unknown>;
}

export async function buildSubChatEncryptedMetadataPayloads(params: {
  parentChatId: string;
  parentChatKey: Uint8Array;
  encryptedParentChatKey: string | null;
  subChats: CliSubChatRequest[];
  createdAt?: number;
}): Promise<SubChatEncryptedMetadataPayload[]> {
  const createdAt = params.createdAt ?? Math.floor(Date.now() / 1000);
  const payloads: SubChatEncryptedMetadataPayload[] = [];

  for (const subChat of params.subChats) {
    const chatId = subChat.id || subChat.chat_id;
    const messageId = subChat.user_message_id || subChat.message_id;
    const prompt = subChat.prompt || "";
    if (!chatId || !messageId) continue;

    const title = prompt.substring(0, 30);
    payloads.push({
      chat_id: chatId,
      parent_id: params.parentChatId,
      is_sub_chat: true,
      message_id: messageId,
      encrypted_content: await encryptWithAesGcmCombined(prompt, params.parentChatKey),
      encrypted_sender_name: await encryptWithAesGcmCombined("User", params.parentChatKey),
      encrypted_title: await encryptWithAesGcmCombined(title, params.parentChatKey),
      created_at: createdAt,
      encrypted_chat_key: params.encryptedParentChatKey,
      versions: {
        messages_v: 1,
        title_v: 0,
        last_edited_overall_timestamp: createdAt,
      },
    });
  }

  return payloads;
}

// ---------------------------------------------------------------------------
// Memory type registry — mirrors all production-stage entries from app.yml files.
// Used for schema validation when creating/updating memories.
// ---------------------------------------------------------------------------

/** A single field definition within a memory type schema. */
export interface MemoryFieldDef {
  type: string;
  description?: string;
  enum?: string[];
  auto_generated?: boolean;
}

/** Schema definition for one memory type. */
export interface MemoryTypeDef {
  appId: string;
  itemType: string;
  entryType: "single" | "list";
  required: string[];
  properties: Record<string, MemoryFieldDef>;
}

/**
 * Registry of all production-stage memory types across all apps.
 * Keys are `${appId}/${itemType}`.
 *
 * Keep in sync with backend/apps/{app}/app.yml memory sections.
 * Auto-generated fields (added_date etc.) are excluded from user-visible fields.
 */
export const MEMORY_TYPE_REGISTRY: Record<string, MemoryTypeDef> = {
  "ai/communication_style": {
    appId: "ai",
    itemType: "communication_style",
    entryType: "single",
    required: ["title", "tone", "verbosity"],
    properties: {
      title: { type: "string" },
      tone: {
        type: "string",
        enum: ["formal", "casual", "friendly", "professional", "conversational"],
      },
      verbosity: { type: "string", enum: ["concise", "balanced", "detailed", "very_detailed"] },
    },
  },
  "ai/learning_preferences": {
    appId: "ai",
    itemType: "learning_preferences",
    entryType: "list",
    required: ["title", "learning_type", "preference_strength"],
    properties: {
      title: { type: "string" },
      learning_type: {
        type: "string",
        enum: ["visual", "auditory", "reading", "hands-on", "video", "interactive", "written", "discussion"],
      },
      preference_strength: {
        type: "string",
        enum: ["strongly_prefer", "prefer", "neutral", "avoid"],
      },
      notes: { type: "string" },
    },
  },
  "books/favorite_books": {
    appId: "books",
    itemType: "favorite_books",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      author: { type: "string" },
      genre: { type: "string" },
      rating: { type: "number" },
      notes: { type: "string" },
    },
  },
  "books/currently_reading": {
    appId: "books",
    itemType: "currently_reading",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      author: { type: "string" },
      started_date: { type: "string" },
      notes: { type: "string" },
    },
  },
  "books/to_read_list": {
    appId: "books",
    itemType: "to_read_list",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      author: { type: "string" },
      genre: { type: "string" },
      notes: { type: "string" },
    },
  },
  "code/preferred_tech": {
    appId: "code",
    itemType: "preferred_tech",
    entryType: "list",
    required: ["name"],
    properties: {
      name: { type: "string" },
      proficiency: {
        type: "string",
        enum: ["beginner", "intermediate", "advanced", "expert"],
      },
    },
  },
  "code/projects": {
    appId: "code",
    itemType: "projects",
    entryType: "list",
    required: ["name"],
    properties: {
      name: { type: "string" },
      status: {
        type: "string",
        enum: ["active", "planned", "completed"],
      },
      description: { type: "string" },
      git_repo_url: { type: "string" },
    },
  },
  "code/want_to_learn": {
    appId: "code",
    itemType: "want_to_learn",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" } },
  },
  "code/coding_setup": {
    appId: "code",
    itemType: "coding_setup",
    entryType: "list",
    required: ["workspace", "ai_level", "input_style"],
    properties: {
      workspace: {
        type: "string",
        enum: ["ide", "terminal", "web_ui", "mixed"],
      },
      ai_level: { type: "string", enum: ["off", "low", "medium", "high"] },
      input_style: {
        type: "string",
        enum: ["guided_choices", "free_text", "mixed"],
      },
      notes: { type: "string" },
    },
  },
  "docs/writing_style": {
    appId: "docs",
    itemType: "writing_style",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" }, description: { type: "string" } },
  },
  "events/saved_events": {
    appId: "events",
    itemType: "saved_events",
    entryType: "list",
    required: ["title"],
    properties: {
      embed_id: { type: "string" },
      title: { type: "string" },
      provider: { type: "string" },
      url: { type: "string" },
      date_start: { type: "string" },
      date_end: { type: "string" },
      location: { type: "string" },
      notes: { type: "string" },
    },
  },
  "health/appointments": {
    appId: "health",
    itemType: "appointments",
    entryType: "list",
    required: ["appointment_type", "date"],
    properties: {
      embed_id: { type: "string" },
      title: { type: "string" },
      appointment_type: { type: "string" },
      where: { type: "string" },
      date: { type: "string" },
      notes: { type: "string" },
    },
  },
  "health/medical_history": {
    appId: "health",
    itemType: "medical_history",
    entryType: "list",
    required: ["condition_type", "name", "date"],
    properties: {
      condition_type: {
        type: "string",
        enum: [
          "surgery",
          "chronic_condition",
          "allergy",
          "medication",
          "vaccination",
          "injury",
          "other",
        ],
      },
      name: { type: "string" },
      date: { type: "string" },
      details: { type: "string" },
    },
  },
  "home/saved_listings": {
    appId: "home",
    itemType: "saved_listings",
    entryType: "list",
    required: ["title"],
    properties: {
      embed_id: { type: "string" },
      title: { type: "string" },
      url: { type: "string" },
      provider: { type: "string" },
      price_label: { type: "string" },
      address: { type: "string" },
      available_from: { type: "string" },
      notes: { type: "string" },
    },
  },
  "images/preferred_styles": {
    appId: "images",
    itemType: "preferred_styles",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" }, description: { type: "string" } },
  },
  "mail/writing_styles": {
    appId: "mail",
    itemType: "writing_styles",
    entryType: "list",
    required: ["title", "description"],
    properties: {
      title: { type: "string" },
      description: { type: "string" },
      when_to_use: { type: "string" },
      footer: { type: "string" },
    },
  },
  "reminder/saved_item_reminder_defaults": {
    appId: "reminder",
    itemType: "saved_item_reminder_defaults",
    entryType: "list",
    required: ["item_kind", "offsets_minutes"],
    properties: {
      item_kind: { type: "string", enum: ["event", "travel_connection", "travel_stay", "home_listing", "health_appointment"] },
      offsets_minutes: { type: "string" },
      notes: { type: "string" },
    },
  },
  "study/learning_goals": {
    appId: "study",
    itemType: "learning_goals",
    entryType: "list",
    required: ["topic", "difficulty_level"],
    properties: {
      topic: { type: "string" },
      difficulty_level: {
        type: "string",
        enum: ["beginner", "intermediate", "advanced"],
      },
      deadline: { type: "string" },
      notes: { type: "string" },
    },
  },
  "travel/trips": {
    appId: "travel",
    itemType: "trips",
    entryType: "list",
    required: ["destination"],
    properties: {
      destination: { type: "string" },
      start_date: { type: "string" },
      end_date: { type: "string" },
      notes: { type: "string" },
    },
  },
  "travel/saved_connections": {
    appId: "travel",
    itemType: "saved_connections",
    entryType: "list",
    required: ["title"],
    properties: {
      embed_id: { type: "string" },
      title: { type: "string" },
      transport_method: { type: "string" },
      origin: { type: "string" },
      destination: { type: "string" },
      departure: { type: "string" },
      arrival: { type: "string" },
      booking_url: { type: "string" },
      provider: { type: "string" },
      notes: { type: "string" },
    },
  },
  "travel/saved_stays": {
    appId: "travel",
    itemType: "saved_stays",
    entryType: "list",
    required: ["name"],
    properties: {
      embed_id: { type: "string" },
      name: { type: "string" },
      property_type: { type: "string" },
      url: { type: "string" },
      price: { type: "string" },
      rating: { type: "number" },
      location: { type: "string" },
      notes: { type: "string" },
    },
  },
  "travel/preferred_airlines": {
    appId: "travel",
    itemType: "preferred_airlines",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" } },
  },
  "travel/preferred_transport_methods": {
    appId: "travel",
    itemType: "preferred_transport_methods",
    entryType: "list",
    required: ["method"],
    properties: {
      method: { type: "string", enum: ["bike", "public_transport", "train", "plane", "car", "walking"] },
    },
  },
  "travel/preferred_activities": {
    appId: "travel",
    itemType: "preferred_activities",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" } },
  },
  "tv/watched_movies": {
    appId: "tv",
    itemType: "watched_movies",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      year: { type: "integer" },
      director: { type: "string" },
      rating: { type: "number" },
      tmdb_id: { type: "integer" },
      notes: { type: "string" },
      genre: { type: "array" },
    },
  },
  "tv/watched_tv_shows": {
    appId: "tv",
    itemType: "watched_tv_shows",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      year: { type: "integer" },
      tmdb_id: { type: "integer" },
      status: {
        type: "string",
        enum: ["watching", "completed", "on_hold", "dropped"],
      },
      seasons_watched: { type: "integer" },
      latest_episode: { type: "string" },
      rating: { type: "number" },
      notes: { type: "string" },
      genre: { type: "array" },
    },
  },
  "tv/to_watch_list": {
    appId: "tv",
    itemType: "to_watch_list",
    entryType: "list",
    required: ["title", "type"],
    properties: {
      title: { type: "string" },
      year: { type: "integer" },
      type: { type: "string", enum: ["movie", "tv_show"] },
      tmdb_id: { type: "integer" },
      director: { type: "string" },
      priority: { type: "string", enum: ["high", "medium", "low"] },
      genre: { type: "array" },
      reason: { type: "string" },
    },
  },
  "videos/to_watch_list": {
    appId: "videos",
    itemType: "to_watch_list",
    entryType: "list",
    required: ["name", "url"],
    properties: {
      name: { type: "string" },
      url: { type: "string" },
      channel: { type: "string" },
    },
  },
  "web/bookmarks": {
    appId: "web",
    itemType: "bookmarks",
    entryType: "list",
    required: ["url"],
    properties: { url: { type: "string" } },
  },
  "web/read_later": {
    appId: "web",
    itemType: "read_later",
    entryType: "list",
    required: ["url"],
    properties: { url: { type: "string" }, notes: { type: "string" } },
  },
};

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

interface PairBundle {
  lookup_hash: string;
  hashed_email: string;
  user_email_salt: string;
  master_key_exported: string;
}

export interface ChatListItem {
  id: string;
  shortId: string;
  title: string | null;
  summary: string | null;
  updatedAt: number | null;
  category: string | null;
  mateName: string | null;
  source?: "example";
}

/** A single parameter extracted from the OpenAPI skill schema. */
export interface SkillParam {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
  inputShape?: "requests" | "flat";
}

export interface ChatListPage {
  chats: ChatListItem[];
  total: number;
  page: number;
  limit: number;
  hasMore: boolean;
}

export interface EncryptedDraft {
  chatId: string;
  encryptedDraftMd: string;
  encryptedDraftPreview: string | null;
  draftV: number;
}

export interface DecryptedDraft extends EncryptedDraft {
  markdown: string;
  preview: string | null;
}

export interface AuthoritativeChatReconciliation {
  authoritative: boolean;
  authoritative_chat_ids?: string[];
  deleted_chat_ids?: string[];
}

export function reconcileAuthoritativeChats(
  chats: CachedChat[],
  evidence: AuthoritativeChatReconciliation,
): CachedChat[] {
  const deletedIds = new Set(evidence.deleted_chat_ids ?? []);
  const authoritativeIds = evidence.authoritative && evidence.authoritative_chat_ids
    ? new Set(evidence.authoritative_chat_ids)
    : null;
  if (!authoritativeIds && deletedIds.size === 0) return chats;
  return chats.filter((chat) => {
    const chatId = String(chat.details.id ?? "");
    return (!authoritativeIds || authoritativeIds.has(chatId)) && !deletedIds.has(chatId);
  });
}

export interface BenchmarkMetadata {
  source: "benchmark";
  benchmark_run_id: string;
  benchmark_suite: string;
  benchmark_case: string;
  benchmark_target_model: string;
  benchmark_judge_model?: string;
}

export interface BenchmarkHistoryMessage {
  message_id: string;
  role: "user" | "assistant" | "system";
  sender_name: string;
  content: string;
  created_at: number;
  chat_id?: string;
  category?: string | null;
}

/** Decrypted message for display */
export interface DecryptedMessage {
  id: string;
  chatId: string;
  role: string;
  content: string;
  senderName: string | null;
  category: string | null;
  modelName: string | null;
  createdAt: number;
  embedIds: string[];
}

/** Decrypted embed summary for display */
export interface DecryptedEmbed {
  id: string;
  embedId: string;
  type: string | null;
  textPreview: string | null;
  content: Record<string, unknown> | null;
  appId: string | null;
  skillId: string | null;
  createdAt: number | null;
}

export interface EmbedVersionMeta {
  version_number: number;
  created_at: number;
  has_snapshot: boolean;
  has_patch: boolean;
  encrypted_snapshot?: string | null;
  encrypted_patch?: string | null;
}

export interface EmbedVersionsResponse {
  embed_id: string;
  current_version: number;
  versions: EmbedVersionMeta[];
  readonly: boolean;
}

export interface EmbedVersionContentResponse {
  embed_id: string;
  version_number: number;
  current_version: number;
  content?: string;
  rows?: EmbedVersionMeta[];
  readonly: boolean;
}

export interface EmbedVersionRestoreResponse {
  embed_id: string;
  restored_from_version: number;
  version_number: number;
  content: string;
  content_hash: string;
}

export interface ApplicationPreviewStartParams {
  embedId: string;
  chatId: string;
  sharedContext?: string;
  requestedRuntime?: string;
  sourceMessageId?: string;
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

/** Video metadata attached to a daily inspiration. */
export interface DailyInspirationVideo {
  youtube_id: string;
  title: string;
  thumbnail_url: string;
  channel_name: string | null;
  view_count: number | null;
  duration_seconds: number | null;
  published_at: string | null;
}

/**
 * A daily inspiration as returned by the CLI.
 *
 * Public inspirations (unauthenticated) come cleartext from
 * GET /v1/default-inspirations.
 *
 * Authenticated inspirations come encrypted from
 * GET /v1/daily-inspirations and are decrypted with the master key.
 */
export interface DailyInspiration {
  id: string;
  phrase: string;
  title: string;
  assistant_response: string;
  category: string;
  content_type: string;
  video: DailyInspirationVideo | null;
  generated_at: number;
  follow_up_suggestions: string[];
  /** Whether the user has already opened this inspiration into a chat. */
  is_opened?: boolean;
}

/**
 * English mate names by category — matches the web app's i18n mates.* keys.
 * The CLI ships without the full i18n system, so we hardcode English names.
 */
export const MATE_NAMES: Record<string, string> = {
  software_development: "Sophia",
  business_development: "Burton",
  life_coach_psychology: "Lisa",
  medical_health: "Melvin",
  legal_law: "Leon",
  finance: "Finn",
  design: "Denise",
  marketing_sales: "Mark",
  science: "Scarlett",
  history: "Hiro",
  cooking_food: "Colin",
  electrical_engineering: "Elton",
  maker_prototyping: "Makani",
  movies_tv: "Monika",
  activism: "Ace",
  general_knowledge: "George",
  onboarding_support: "Suki",
};

/**
 * A decrypted new-chat suggestion as returned to CLI callers.
 *
 * Mirrors the format used by NewChatSuggestions.svelte in the web app.
 * The `body` text is the plain text to insert into the message input.
 */
export interface DecryptedNewChatSuggestion {
  id: string;
  chatId: string | null;
  body: string;
  createdAt: number;
}

function stripLegacySuggestionPrefix(text: string): string {
  return text.replace(/^\s*\[[^\]]+\]\s*/, "").trim();
}

/** A decrypted memory entry as returned to CLI callers. */
export interface DecryptedMemoryEntry {
  id: string;
  app_id: string;
  item_type: string;
  item_key_hash: string;
  item_version: number;
  created_at: number;
  updated_at: number;
  /** Decrypted item_value fields including _original_item_key. */
  data: Record<string, unknown>;
}

export interface OpenMatesClientOptions {
  apiUrl?: string;
  session?: OpenMatesSession;
}

export interface InvoiceListItem {
  id: string;
  order_id?: string | null;
  date: string;
  amount: string;
  credits_purchased: number;
  filename: string;
  is_gift_card?: boolean;
  refunded_at?: string | null;
  refund_status?: string | null;
  currency?: string | null;
  provider?: string | null;
  bank_transfer_reference?: string | null;
  transaction_status?: string | null;
  document_status?: string | null;
}

export interface DownloadedDocument {
  filename: string;
  data: Uint8Array;
}

export interface BankTransferOrderDetails {
  order_id: string;
  reference: string;
  iban: string;
  bic: string;
  bank_name: string;
  account_holder_name: string;
  account_holder_address_line1?: string;
  account_holder_address_line2?: string;
  account_holder_postal_code?: string;
  account_holder_city?: string;
  account_holder_country?: string;
  amount_eur: string;
  credits_amount: number;
  expires_at: string;
}

export interface BankTransferStatus {
  order_id: string;
  status: string;
  credits_amount: number;
  amount_eur: string;
  reference: string;
  expires_at: string;
  created_at?: string;
}

export interface GiftCardBankTransferStatus extends BankTransferStatus {
  gift_card_code?: string | null;
}

export interface ApiKeyCreateOptions {
  name: string;
  fullAccess?: boolean;
  scopes?: Record<string, unknown>;
  creditLimit?: Record<string, unknown> | null;
  expiresAt?: string | null;
}

export interface CreatedApiKeyResult {
  api_key: string;
  key: unknown;
  crypto: ApiKeyCryptoMaterial;
}

export interface AuthMethodsStatus {
  has_passkey?: boolean;
  has_2fa?: boolean;
  has_password?: boolean;
  has_recovery_key?: boolean;
}

export interface CliSignupResult {
  success: boolean;
  message: string;
  user?: Record<string, unknown>;
  crypto: SignupCryptoMaterial;
}

export interface TotpSetupStartResult {
  success: boolean;
  message: string;
  secret?: string | null;
  otpauth_url?: string | null;
}

export interface BackupCodesResult {
  success: boolean;
  message: string;
  backup_codes: string[];
}

interface TaskStatusResponse {
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed" | string;
  result?: unknown;
  error?: string | null;
}

export interface AnonymousFreeUsageStatus {
  active: boolean;
  reason: string | null;
  resetAt: string | null;
  cta: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CLOUD_API_URL = "https://api.openmates.org";
const DEFAULT_API_URL = process.env.OPENMATES_API_URL ?? CLOUD_API_URL;
const SETTINGS_GET_RATE_LIMIT_RETRY_MS = 61_000;
const SKILL_TASK_POLL_INTERVAL_MS = 2_000;
const SKILL_TASK_POLL_TIMEOUT_MS = 1_200_000;
const SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS = 500;

function normalizeOrigin(url: URL): string {
  url.pathname = "";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function isLocalHost(hostname: string): boolean {
  return ["localhost", "127.0.0.1", "::1"].includes(hostname);
}

function loadDefaultServerApiUrl(): string | null {
  const config = loadServerConfig();
  return config?.apiUrl?.replace(/\/$/, "") ?? null;
}

/**
 * Derive the web app URL from the API URL so the pair token is always looked
 * up on the same backend the CLI created it on.
 * Override with OPENMATES_APP_URL when using a custom setup.
 */
export function deriveAppUrl(apiUrl: string): string {
  if (process.env.OPENMATES_APP_URL) {
    return process.env.OPENMATES_APP_URL.replace(/\/$/, "");
  }

  const serverAppUrl = loadServerConfig()?.appUrl;
  if (serverAppUrl && apiUrl.replace(/\/$/, "") === loadDefaultServerApiUrl()) {
    return serverAppUrl.replace(/\/$/, "");
  }

  try {
    const url = new URL(apiUrl);
    if (url.hostname === "api.dev.openmates.org") {
      return "https://app.dev.openmates.org";
    }
    if (url.hostname === "api.openmates.org") {
      return "https://openmates.org";
    }
    if (isLocalHost(url.hostname)) {
      return "http://localhost:5173";
    }
    if (url.hostname.startsWith("api.")) {
      url.hostname = `app.${url.hostname.slice(4)}`;
    }
    return normalizeOrigin(url);
  } catch {
    return "https://openmates.org";
  }
}

const CLI_DEVICE_NAME_PREFIX = "OpenMates CLI";

/** Settings POST/DELETE paths that must never be executed from the CLI. */
const BLOCKED_SETTINGS_MUTATE_PATHS = new Set<string>([
  "/v1/settings/api-keys",
  "/v1/settings/update-password",
  "/v1/auth/setup_password",
  "/v1/auth/2fa/setup/initiate",
  "/v1/auth/2fa/setup/provider",
  "/v1/auth/2fa/setup/verify-signup",
  "/v1/settings/delete-account",
  "/v1/settings/request-action-verification",
  "/v1/settings/verify-action-code",
  "/v1/settings/user/disable-2fa",
]);

function applyUnifiedDiffForEmbedVersion(content: string, patch: string): string {
  const contentLines = content.split("\n");
  const lines = patch.split("\n");
  const hunks: Array<{ start: number; oldLines: string[]; newLines: string[] }> = [];
  let current: { start: number; oldLines: string[]; newLines: string[] } | null = null;

  for (const line of lines) {
    const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (match) {
      if (current) hunks.push(current);
      current = { start: Number(match[1]) - 1, oldLines: [], newLines: [] };
      continue;
    }
    if (!current) continue;
    if (line.startsWith(" ")) {
      current.oldLines.push(line.slice(1));
      current.newLines.push(line.slice(1));
    } else if (line.startsWith("-")) {
      current.oldLines.push(line.slice(1));
    } else if (line.startsWith("+")) {
      current.newLines.push(line.slice(1));
    }
  }
  if (current) hunks.push(current);

  for (const hunk of hunks.sort((a, b) => b.start - a.start)) {
    const actual = contentLines.slice(hunk.start, hunk.start + hunk.oldLines.length);
    if (actual.join("\n") !== hunk.oldLines.join("\n")) {
      throw new Error("Version patch context does not match local content");
    }
    contentLines.splice(hunk.start, hunk.oldLines.length, ...hunk.newLines);
  }

  return contentLines.join("\n");
}

function buildUnifiedDiffForEmbedRestore(
  currentContent: string,
  restoredContent: string,
  currentVersion: number,
  newVersion: number,
): string {
  const currentLines = currentContent.split("\n");
  const restoredLines = restoredContent.split("\n");
  return [
    `--- v${currentVersion}`,
    `+++ v${newVersion}`,
    `@@ -1,${Math.max(1, currentLines.length)} +1,${Math.max(1, restoredLines.length)} @@`,
    ...currentLines.map((line) => `-${line}`),
    ...restoredLines.map((line) => `+${line}`),
  ].join("\n");
}

function parseEmbedContentObject(rawContent: string): Record<string, unknown> {
  try {
    return JSON.parse(rawContent) as Record<string, unknown>;
  } catch {
    return parseYamlLikeContent(rawContent);
  }
}

async function encodeEmbedContentObject(content: Record<string, unknown>): Promise<string> {
  try {
    const { encode } = await import("@toon-format/toon");
    return encode(content);
  } catch {
    return JSON.stringify(content);
  }
}

function extractVersionedEmbedContent(content: Record<string, unknown>): string {
  if (typeof content.receiver === "string" || typeof content.subject === "string") {
    return [
      `To: ${typeof content.receiver === "string" ? content.receiver : ""}`,
      `Subject: ${typeof content.subject === "string" ? content.subject : ""}`,
      "",
      typeof content.content === "string" ? content.content : "",
      typeof content.footer === "string" ? content.footer : "",
    ].join("\n").trim();
  }
  if (typeof content.remotion_source === "string") return content.remotion_source;
  if (typeof content.code === "string") return content.code;
  if (typeof content.html === "string") return content.html;
  if (typeof content.table === "string") return content.table;
  if (content.docx_model) return JSON.stringify(content.docx_model, null, 2);
  if (typeof content.content === "string") return content.content;
  throw new Error("Unsupported embed content shape for version restore.");
}

function buildRestoredEmbedContentObject(
  current: Record<string, unknown>,
  restoredContent: string,
  newVersion: number,
): Record<string, unknown> {
  const restored = { ...current, version_number: newVersion };
  if (typeof current.receiver === "string" || typeof current.subject === "string") {
    return { ...restored, ...parseMailVersionContent(restoredContent) };
  }
  if (typeof current.remotion_source === "string") {
    return { ...restored, remotion_source: restoredContent, current_source_version: newVersion };
  }
  if (typeof current.code === "string") return { ...restored, code: restoredContent };
  if (typeof current.html === "string") return { ...restored, html: restoredContent };
  if (typeof current.table === "string") return { ...restored, table: restoredContent };
  if (current.docx_model) {
    try {
      return { ...restored, docx_model: JSON.parse(restoredContent) };
    } catch {
      return { ...restored, content: restoredContent };
    }
  }
  if (typeof current.content === "string") return { ...restored, content: restoredContent };
  throw new Error("Unsupported embed content shape for version restore.");
}

function parseMailVersionContent(versionContent: string): Record<string, string> {
  const lines = versionContent.split("\n");
  let receiver = "";
  let subject = "";
  const bodyLines: string[] = [];
  for (const line of lines) {
    if (line.toLowerCase().startsWith("to:")) {
      receiver = line.slice(3).trim();
    } else if (line.toLowerCase().startsWith("subject:")) {
      subject = line.slice(8).trim();
    } else {
      bodyLines.push(line);
    }
  }
  return {
    receiver,
    subject,
    content: bodyLines.join("\n").trim(),
    footer: "",
  };
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class OpenMatesClient {
  readonly apiUrl: string;
  private session: OpenMatesSession | null;
  private readonly http: OpenMatesHttpClient;

  constructor(options: OpenMatesClientOptions = {}) {
    const diskSession = options.session ?? this.getValidSessionFromDisk();
    this.apiUrl = (
      options.apiUrl ??
      process.env.OPENMATES_API_URL ??
      diskSession?.apiUrl ??
      loadDefaultServerApiUrl() ??
      DEFAULT_API_URL
    ).replace(/\/$/, "");
    this.session = diskSession;
    this.http = new OpenMatesHttpClient({
      apiUrl: this.apiUrl,
      cookies: diskSession?.cookies,
    });
  }

  static load(options: OpenMatesClientOptions = {}): OpenMatesClient {
    return new OpenMatesClient(options);
  }

  hasSession(): boolean {
    return this.session !== null;
  }

  async getAnonymousFreeUsageStatus(): Promise<AnonymousFreeUsageStatus> {
    const response = await this.http.get<{
      active?: boolean;
      reason?: string | null;
      reset_at?: string | null;
      cta?: string | null;
      detail?: { code?: string; message?: string } | string;
    }>("/v1/anonymous/free-usage/status");

    if (response.status === 404) {
      return {
        active: false,
        reason: "self_hosted",
        resetAt: null,
        cta: "Anonymous free chat is not available on this server.",
      };
    }

    if (!response.ok) {
      const detail = response.data.detail;
      const message = typeof detail === "object" && detail?.message
        ? detail.message
        : typeof detail === "string"
          ? detail
          : `Anonymous free usage status failed with HTTP ${response.status}`;
      throw new Error(message);
    }

    return {
      active: response.data.active === true,
      reason: response.data.reason ?? null,
      resetAt: response.data.reset_at ?? null,
      cta: response.data.cta ?? null,
    };
  }

  async sendAnonymousMessage(params: {
    message: string;
    learningMode?: LearningModeContext;
    messageHistory?: BenchmarkHistoryMessage[];
  }): Promise<{
    status: "completed";
    chatId: string;
    messageId: string;
    assistant: string;
    category: string | null;
    modelName: string | null;
    mateName: string | null;
    followUpSuggestions: string[];
    taskProposals: TaskProposalEvent[];
    taskUpdateProposals: TaskUpdateProposalEvent[];
    subChatEvents: SubChatEvent[];
    appSettingsMemoryRequests: Array<{
      requestId: string | null;
      requestedKeys: string[];
      approvedKeys: string[];
      entryCount: number;
    }>;
  }> {
    const availability = await this.getAnonymousFreeUsageStatus();
    if (!availability.active) {
      throw new Error(availability.cta ?? "Create an account to keep using OpenMates.");
    }

    let anonymousId = loadAnonymousId();
    if (!anonymousId) {
      anonymousId = randomUUID();
      saveAnonymousId(anonymousId);
    }
    const chatId = `anonymous-${randomUUID()}`;
    const messageId = `anonymous-message-${randomUUID()}`;
    const requestBody: Record<string, unknown> = {
      anonymous_id: anonymousId,
      client_chat_id: chatId,
      client_message_id: messageId,
      plaintext_message: params.message,
      message_history: (params.messageHistory ?? []).map((message) => ({
        role: message.role,
        content: message.content,
        created_at: message.created_at,
        sender_name: message.sender_name ?? message.role,
      })),
    };
    if (params.learningMode?.enabled === true) {
      requestBody.learning_mode = {
        enabled: true,
        age_group: params.learningMode.ageGroup ?? null,
        source: params.learningMode.source ?? "anonymous_session",
      };
    }

    const response = await this.http.post<{
      status?: string;
      chatId?: string;
      messageId?: string;
      assistant?: string;
      category?: string | null;
      modelName?: string | null;
      followUpSuggestions?: string[];
      detail?: { code?: string; message?: string } | string;
    }>("/v1/anonymous/chat/stream", requestBody);
    if (!response.ok) {
      const detail = response.data.detail;
      const message = typeof detail === "object" && detail?.message
        ? detail.message
        : typeof detail === "string"
          ? detail
          : `Anonymous chat failed with HTTP ${response.status}`;
      throw new Error(message);
    }
    return {
      status: "completed",
      chatId: response.data.chatId ?? chatId,
      messageId: response.data.messageId ?? messageId,
      assistant: response.data.assistant ?? "",
      category: response.data.category ?? null,
      modelName: response.data.modelName ?? null,
      mateName: null,
      followUpSuggestions: response.data.followUpSuggestions ?? [],
      taskProposals: [],
      taskUpdateProposals: [],
      subChatEvents: [],
      appSettingsMemoryRequests: [],
    };
  }

  async createTurnTokenRefs(params: {
    chatId: string;
    messageId: string;
    refs: ConnectedAccountTurnTokenRefInput[];
  }): Promise<ConnectedAccountTurnTokenRef[]> {
    if (params.refs.length === 0) return [];
    const response = await this.http.post<{
      refs?: Array<{
        connected_account_id: string;
        app_id: string;
        turn_token_ref: string;
        expires_at: number;
      }>;
    }>(
      "/v1/token-broker/turn-token-refs",
      buildTurnTokenRefsRequestPayload(params),
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !Array.isArray(response.data.refs)) {
      throw new Error(`Failed to create connected-account token refs (HTTP ${response.status})`);
    }
    return response.data.refs.map((ref) => {
      const input = params.refs.find(
        (item) => item.connected_account_id === ref.connected_account_id && item.app_id === ref.app_id,
      );
      return {
        connected_account_id: ref.connected_account_id,
        app_id: ref.app_id,
        turn_token_ref: ref.turn_token_ref,
        expires_at: ref.expires_at,
        allowed_actions: input?.allowed_actions ?? [],
        action_scope: input?.action_scope,
      };
    });
  }

  async importConnectedAccountFromCliPayload(params: {
    encryptedPayload: string;
    passcode: string;
  }): Promise<ConnectedAccountImportResult> {
    this.requireSession();
    const payload = await decryptConnectedAccountCliTransferPayload(params.encryptedPayload, params.passcode);
    const validation = await this.validateConnectedAccountImportPayload(payload);
    const user = await this.whoAmI();
    const userId = typeof user.id === "string"
      ? user.id
      : typeof user.user_id === "string"
        ? user.user_id
        : "";
    if (!userId) {
      throw new Error("Could not resolve current user id for connected account import.");
    }
    const row = await buildEncryptedConnectedAccountImportRow({
      payload,
      userId,
      masterKey: this.getMasterKeyBytes(),
    });
    const stored = await this.createConnectedAccountImportRow(row);
    return {
      id: stored.id,
      providerId: payload.provider_id,
      appId: payload.app_id,
      label: payload.label,
      validation,
    };
  }

  async validateConnectedAccountImportPayload(
    payload: ConnectedAccountCliTransferPayload,
  ): Promise<ConnectedAccountImportValidationResult> {
    this.requireSession();
    const response = await this.http.post<ConnectedAccountImportValidationResult>(
      "/v1/connected-accounts/validate-import",
      {
        provider_id: payload.provider_id,
        app_id: payload.app_id,
        capabilities: payload.capabilities,
        refresh_token_envelope: payload.refresh_token_bundle,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || response.data.valid !== true) {
      throw new Error(`Connected account validation failed (HTTP ${response.status})`);
    }
    assertNoConnectedAccountSecretLeak(response.data);
    return response.data;
  }

  private async createConnectedAccountImportRow(
    row: EncryptedConnectedAccountImportRow,
  ): Promise<{ id: string; sync_version: number }> {
    assertNoConnectedAccountSecretLeak(row);
    const response = await this.http.post<{ id: string; sync_version: number }>(
      "/v1/connected-accounts",
      row,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.id) {
      throw new Error(`Failed to store connected account import (HTTP ${response.status})`);
    }
    return response.data;
  }

  async registerLocalConnectedAccountConnector(
    input: ProtonLocalConnectorRegistration,
  ): Promise<{ connected_account_id: string; connector_session_id: string; heartbeat_interval_ms?: number }> {
    assertNoConnectedAccountSecretLeak(input);
    const user = await this.whoAmI();
    const userId = typeof user.id === "string"
      ? user.id
      : typeof user.user_id === "string"
        ? user.user_id
        : "";
    if (!userId) {
      throw new Error("Could not resolve current user id for local connected-account connector.");
    }
    const { createHash } = await import("node:crypto");
    const accountId = randomUUID();
    const masterKey = this.getMasterKeyBytes();
    const encryptLocalConnectorValue = async (value: unknown): Promise<string> => {
      const plaintext = typeof value === "string" ? value : JSON.stringify(value);
      return encryptWithAesGcmCombined(plaintext, masterKey);
    };
    const payload = {
      id: accountId,
      hashed_user_id: createHash("sha256").update(userId).digest("hex"),
      encrypted_provider_type: await encryptLocalConnectorValue(input.provider_id),
      provider_type_hash: createHash("sha256").update(input.provider_id).digest("hex"),
      encrypted_account_label: await encryptLocalConnectorValue(input.label),
      encrypted_capabilities: await encryptLocalConnectorValue(input.capabilities),
      encrypted_app_permissions: await encryptLocalConnectorValue({
        app_id: input.app_id,
        allowed_actions: input.capabilities.includes("write") ? ["read", "write"] : ["read"],
        runtime_modes: Object.fromEntries(input.capabilities.map((capability) => [capability, capability === "read" ? "allow_automatically" : "always_ask"])),
      }),
      encrypted_account_directory_hint: await encryptLocalConnectorValue({
        label: input.label,
        app_id: input.app_id,
        runtime: "local_connector",
      }),
      execution_mode: "local_connector",
      connector_provider_id: input.provider_id,
      connector_instance_id: input.connector_instance_id,
      connector_status: input.status,
      connector_public_metadata: input.metadata,
    };
    assertNoConnectedAccountSecretLeak(payload);
    const response = await this.http.post<{
      connected_account_id?: string;
      connector_session_id?: string;
      heartbeat_interval_ms?: number;
    }>(
      "/v1/connected-accounts/local-connectors",
      payload,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.connected_account_id || !response.data.connector_session_id) {
      throw new Error(`Failed to register local connected-account connector (HTTP ${response.status})`);
    }
    assertNoConnectedAccountSecretLeak(response.data);
    return {
      connected_account_id: response.data.connected_account_id,
      connector_session_id: response.data.connector_session_id,
      heartbeat_interval_ms: response.data.heartbeat_interval_ms,
    };
  }

  async sendLocalConnectedAccountConnectorHeartbeat(input: {
    connector_session_id: string;
    connected_account_id: string;
    status: "online" | "offline";
    capabilities: string[];
    health_summary?: Record<string, unknown>;
  }): Promise<Record<string, unknown>> {
    assertNoConnectedAccountSecretLeak(input);
    const response = await this.http.post<Record<string, unknown>>(
      `/v1/connected-accounts/local-connectors/${encodeURIComponent(input.connector_session_id)}/heartbeat`,
      {
        connected_account_id: input.connected_account_id,
        status: input.status,
        capabilities: input.capabilities,
        health_summary: input.health_summary ?? {},
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to send local connected-account connector heartbeat (HTTP ${response.status})`);
    }
    assertNoConnectedAccountSecretLeak(response.data);
    return response.data;
  }

  async completeLocalConnectedAccountConnectorRequest(input: {
    connector_session_id: string;
    connected_account_id: string;
    request_id: string;
    status: "ok" | "error" | "cancelled";
    result?: Record<string, unknown>;
    error_code?: string;
    error_message?: string;
  }): Promise<Record<string, unknown>> {
    assertNoConnectedAccountSecretLeak(input);
    const response = await this.http.post<Record<string, unknown>>(
      `/v1/connected-accounts/local-connectors/${encodeURIComponent(input.connector_session_id)}/complete-request`,
      {
        connected_account_id: input.connected_account_id,
        request_id: input.request_id,
        status: input.status,
        result: input.result ?? {},
        error_code: input.error_code,
        error_message: input.error_message,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to complete local connected-account connector request (HTTP ${response.status})`);
    }
    assertNoConnectedAccountSecretLeak(response.data);
    return response.data;
  }

  async openLocalConnectorWebSocket(): Promise<OpenMatesWsClient> {
    const { ws } = await this.openWsClient();
    return ws;
  }

  async cancelConnectedAccountAction(params: {
    actionId: string;
    chatId: string;
    messageId: string;
  }): Promise<Record<string, unknown>> {
    const response = await this.http.post<Record<string, unknown>>(
      `/v1/connected-accounts/actions/${encodeURIComponent(params.actionId)}/cancel`,
      {
        chat_id: params.chatId,
        message_id: params.messageId,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to cancel connected-account action (HTTP ${response.status})`);
    }
    return response.data;
  }

  async undoConnectedAccountAction(params: {
    actionId: string;
    chatId: string;
    messageId: string;
    turnTokenRef: string;
  }): Promise<Record<string, unknown>> {
    const response = await this.http.post<Record<string, unknown>>(
      `/v1/connected-accounts/actions/${encodeURIComponent(params.actionId)}/undo`,
      {
        chat_id: params.chatId,
        message_id: params.messageId,
        turn_token_ref: params.turnTokenRef,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to undo connected-account action (HTTP ${response.status})`);
    }
    return response.data;
  }

  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------

  async loginWithPairAuth(): Promise<void> {
    const localDeviceName = this.getLocalDeviceName();
    const initiate = await this.http.post<{ token?: string }>(
      "/v1/auth/pair/initiate",
      { device_hint: localDeviceName },
      this.getCliRequestHeaders(),
    );
    if (!initiate.ok || !initiate.data.token) {
      throw new Error("Failed to initiate pair login");
    }

    const token = initiate.data.token.toUpperCase();
    const appBase = deriveAppUrl(this.apiUrl);
    const loginUrl = `${appBase}/#pair=${token}`;

    stdout.write("\n");
    printLogo();
    stdout.write("\n");
    this.renderPairQrCode(loginUrl);
    stdout.write(`Open on your logged-in device: ${loginUrl}\n`);
    stdout.write(`Then enter the 6-char PIN shown on that device.\n\n`);
    stdout.write("Waiting for authorization...\n");
    stdout.write("Press E to cancel.\n");

    const pollResult = await this.waitForPairAuthorization(token);
    if (pollResult.authorizerDeviceName) {
      stdout.write(`Authorized by: ${pollResult.authorizerDeviceName}\n`);
    }

    const pin = await this.prompt("Enter 6-char pairing PIN: ");
    const complete = await this.http.post<{
      success?: boolean;
      encrypted_bundle?: string;
      iv?: string;
      message?: string;
      authorizer_device_name?: string | null;
      auto_logout_minutes?: number | null;
    }>(
      `/v1/auth/pair/complete/${token}`,
      { pin: pin.trim().toUpperCase() },
      this.getCliRequestHeaders(),
    );

    if (
      !complete.ok ||
      !complete.data.success ||
      !complete.data.encrypted_bundle ||
      !complete.data.iv
    ) {
      throw new Error(complete.data.message ?? "Pair completion failed");
    }

    const bundle = (await decryptBundle({
      encryptedBundleB64: complete.data.encrypted_bundle,
      ivB64: complete.data.iv,
      pin: pin.trim().toUpperCase(),
      token,
    })) as PairBundle;

    const sessionId = randomUUID();
    const login = await this.http.post<{
      success?: boolean;
      message?: string;
      ws_token?: string;
    }>(
      "/v1/auth/login",
      {
        hashed_email: bundle.hashed_email,
        lookup_hash: bundle.lookup_hash,
        session_id: sessionId,
        stay_logged_in: true,
        login_method: "pair",
      },
      this.getCliRequestHeaders(),
    );

    if (!login.ok || !login.data.success) {
      throw new Error(
        login.data.message ?? "Login failed after pair completion",
      );
    }

    const session: OpenMatesSession = {
      apiUrl: this.apiUrl,
      sessionId,
      wsToken: login.data.ws_token ?? null,
      cookies: this.http.getCookieMap(),
      masterKeyExportedB64: bundle.master_key_exported,
      hashedEmail: bundle.hashed_email,
      userEmailSalt: bundle.user_email_salt,
      createdAt: Date.now(),
      authorizerDeviceName: complete.data.authorizer_device_name ?? null,
      autoLogoutMinutes: complete.data.auto_logout_minutes ?? null,
    };

    await this.hydrateEmailEncryptionKey(session);

    saveSession(session);
  }

  async whoAmI(): Promise<Record<string, unknown>> {
    const session = this.requireSession();
    const response = await this.http.post<{
      success?: boolean;
      user?: Record<string, unknown>;
      ws_token?: string;
    }>(
      "/v1/auth/session",
      { session_id: session.sessionId },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.success) {
      throw new Error("Session is invalid. Please run `openmates login`.");
    }
    if (response.data.ws_token) {
      session.wsToken = response.data.ws_token;
    }
    session.cookies = this.http.getCookieMap();
    saveSession(session);
    return response.data.user ?? {};
  }

  async getTopicPreferences(): Promise<TopicPreferencesPayload | null> {
    const user = await this.whoAmI();
    return await this.decryptTopicPreferences(user.encrypted_settings);
  }

  async setTopicPreferences(
    selectedTagIds: readonly string[],
  ): Promise<TopicPreferencesPayload> {
    const user = await this.whoAmI();
    const settings = await this.decryptSettingsRecord(user.encrypted_settings);
    const payload: TopicPreferencesPayload = {
      version: 1,
      selectedTagIds: normalizeInterestTagIds(selectedTagIds),
      updatedAt: new Date().toISOString(),
    };

    settings[TOPIC_PREFERENCES_SETTINGS_KEY] = payload;
    const encryptedSettings = await encryptWithAesGcmCombined(
      JSON.stringify(settings),
      this.getMasterKeyBytes(),
    );
    await this.settingsPost("topic-preferences", {
      encrypted_settings: encryptedSettings,
    });
    return payload;
  }

  async clearTopicPreferences(): Promise<TopicPreferencesPayload> {
    return await this.setTopicPreferences([]);
  }

  async getLearningModeStatus(): Promise<LearningModeStatus> {
    this.requireSession();
    const response = await this.http.get<LearningModeStatus>(
      "/v1/learning-mode",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Learning Mode status failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async activateLearningMode(params: {
    ageGroup: LearningModeAgeGroup;
    passcode: string;
  }): Promise<LearningModeStatus> {
    this.requireSession();
    const response = await this.http.post<LearningModeStatus>(
      "/v1/learning-mode/activate",
      { age_group: params.ageGroup, passcode: params.passcode },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Learning Mode activation failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async deactivateLearningMode(passcode: string): Promise<LearningModeStatus> {
    this.requireSession();
    const response = await this.http.post<LearningModeStatus>(
      "/v1/learning-mode/deactivate",
      { passcode },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Learning Mode deactivation failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async logout(): Promise<void> {
    if (this.session) {
      await this.http
        .post("/v1/auth/logout", {}, this.getCliRequestHeaders())
        .catch(() => undefined);
    }
    clearSession();
  }

  async requestSignupEmailCode(params: {
    email: string;
    inviteCode?: string;
    language?: string;
    darkmode?: boolean;
  }): Promise<unknown> {
    const hashedEmail = await hashEmail(params.email.trim().toLowerCase());
    const response = await this.http.post(
      "/v1/auth/request_confirm_email_code",
      {
        email: params.email.trim().toLowerCase(),
        hashed_email: hashedEmail,
        invite_code: params.inviteCode ?? "",
        language: params.language ?? "en",
        darkmode: params.darkmode ?? false,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `Email code request failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async verifySignupEmailCode(params: {
    email: string;
    username: string;
    inviteCode?: string;
    code: string;
    language?: string;
    darkmode?: boolean;
  }): Promise<unknown> {
    const response = await this.http.post(
      "/v1/auth/check_confirm_email_code",
      {
        code: params.code,
        email: params.email.trim().toLowerCase(),
        username: params.username,
        invite_code: params.inviteCode ?? "",
        language: params.language ?? "en",
        darkmode: params.darkmode ?? false,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `Email code verification failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async setupPasswordAccount(params: {
    email: string;
    username: string;
    password: string;
    inviteCode?: string;
    language?: string;
    darkmode?: boolean;
  }): Promise<CliSignupResult> {
    const material = await createSignupCryptoMaterial(params.email, params.password);
    const response = await this.http.post<{ success?: boolean; message?: string; user?: Record<string, unknown> }>(
      "/v1/auth/setup_password",
      {
        hashed_email: material.hashedEmail,
        encrypted_email: material.encryptedEmail,
        user_email_salt: material.userEmailSaltB64,
        username: params.username,
        invite_code: params.inviteCode ?? "",
        encrypted_master_key: material.encryptedMasterKey,
        key_iv: material.keyIv,
        salt: material.saltB64,
        lookup_hash: material.lookupHash,
        language: params.language ?? "en",
        darkmode: params.darkmode ?? false,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.success) {
      throw new Error(response.data.message ?? `Password signup failed (HTTP ${response.status})`);
    }

    const session: OpenMatesSession = {
      apiUrl: this.apiUrl,
      sessionId: randomUUID(),
      wsToken: null,
      cookies: this.http.getCookieMap(),
      masterKeyExportedB64: material.masterKeyB64,
      emailEncryptionKeyB64: material.emailEncryptionKeyB64,
      hashedEmail: material.hashedEmail,
      userEmailSalt: material.userEmailSaltB64,
      createdAt: Date.now(),
      authorizerDeviceName: null,
      autoLogoutMinutes: null,
    };
    saveSession(session);
    this.session = session;
    return {
      success: true,
      message: response.data.message ?? "Account created.",
      user: response.data.user,
      crypto: material,
    };
  }

  async startTotpSetup(): Promise<TotpSetupStartResult> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post<TotpSetupStartResult>(
      "/v1/auth/2fa/setup/initiate",
      { email_encryption_key: emailEncryptionKey },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.success) {
      throw new Error(response.data.message ?? `2FA setup failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  renderTotpQrCode(otpauthUrl: string): void {
    qrcode.generate(otpauthUrl, { small: true });
  }

  async verifyTotpSetup(code: string): Promise<unknown> {
    this.requireSession();
    const response = await this.http.post(
      "/v1/auth/2fa/setup/verify-signup",
      { code },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `2FA verification failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async setTotpProvider(provider: string): Promise<unknown> {
    this.requireSession();
    const response = await this.http.post(
      "/v1/auth/2fa/setup/provider",
      { provider },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `2FA provider save failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async requestBackupCodes(): Promise<BackupCodesResult> {
    this.requireSession();
    const response = await this.http.get<BackupCodesResult>(
      "/v1/auth/2fa/setup/request-backup-codes",
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.success) {
      throw new Error(response.data.message ?? `Backup-code request failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async confirmBackupCodesStored(): Promise<unknown> {
    this.requireSession();
    const response = await this.http.post(
      "/v1/auth/2fa/setup/confirm-codes-stored",
      { confirmed: true },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `Backup-code confirmation failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async createAndConfirmRecoveryKey(): Promise<RecoveryKeyMaterial> {
    const session = this.requireSession();
    const material = await createRecoveryKeyMaterial(session.masterKeyExportedB64, session.userEmailSalt);
    const response = await this.http.post(
      "/v1/auth/recovery-key/confirm-stored",
      {
        confirmed: true,
        lookup_hash: material.lookupHash,
        wrapped_master_key: material.wrappedMasterKey,
        key_iv: material.keyIv,
        salt: material.saltB64,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data as { success?: boolean }).success === false) {
      throw new Error((response.data as { message?: string }).message ?? `Recovery-key confirmation failed (HTTP ${response.status})`);
    }
    return material;
  }

  // -------------------------------------------------------------------------
  // Chats
  // -------------------------------------------------------------------------

  /**
   * Decrypt a single chat's key using the master key.
   * Returns raw Uint8Array (32 bytes) — the AES-256 key used to
   * encrypt/decrypt the chat's title, category, messages, etc.
   */
  private async decryptChatKey(
    encryptedChatKey: string,
    masterKey: Uint8Array,
  ): Promise<Uint8Array | null> {
    return decryptBytesWithAesGcm(encryptedChatKey, masterKey);
  }

  /**
   * Decrypt a single chat record from the sync cache into a ChatListItem.
   */
  private async decryptChatListItem(
    cached: CachedChat,
    masterKey: Uint8Array,
  ): Promise<ChatListItem> {
    const d = cached.details;
    const id = String(d.id ?? "");
    const encKey =
      typeof d.encrypted_chat_key === "string" ? d.encrypted_chat_key : null;
    const chatKeyBytes = encKey
      ? await this.decryptChatKey(encKey, masterKey)
      : null;

    const title =
      typeof d.encrypted_title === "string" && chatKeyBytes
        ? await decryptWithAesGcmCombined(d.encrypted_title, chatKeyBytes)
        : null;
    const summary =
      typeof d.encrypted_chat_summary === "string" && chatKeyBytes
        ? await decryptWithAesGcmCombined(
            d.encrypted_chat_summary,
            chatKeyBytes,
          )
        : null;
    const category =
      typeof d.encrypted_category === "string" && chatKeyBytes
        ? await decryptWithAesGcmCombined(d.encrypted_category, chatKeyBytes)
        : null;

    return {
      id,
      shortId: id.slice(0, 8),
      title,
      summary,
      updatedAt:
        typeof d.last_edited_overall_timestamp === "number"
          ? d.last_edited_overall_timestamp
          : null,
      category,
      mateName: category ? (MATE_NAMES[category] ?? null) : null,
    };
  }

  async listChats(limit = 10, page = 1): Promise<ChatListPage> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const total = cache.chats.length;
    const offset = (page - 1) * limit;
    const slice = cache.chats.slice(offset, offset + limit);
    const output: ChatListItem[] = [];
    for (const chat of slice) {
      output.push(await this.decryptChatListItem(chat, masterKey));
    }
    return {
      chats: output,
      total,
      page,
      limit,
      hasMore: offset + limit < total,
    };
  }

  async saveDraft(params: {
    markdown: string;
    preview?: string | null;
    chatId?: string;
  }): Promise<DecryptedDraft> {
    const markdown = params.markdown.trim();
    if (!markdown) throw new Error("Draft markdown must not be empty.");
    const masterKey = this.getMasterKeyBytes();
    const encrypted = await this.saveEncryptedDraft({
      chatId: params.chatId ?? randomUUID(),
      encryptedDraftMd: await encryptWithAesGcmCombined(markdown, masterKey),
      encryptedDraftPreview: params.preview
        ? await encryptWithAesGcmCombined(params.preview, masterKey)
        : null,
    });
    return { ...encrypted, markdown, preview: params.preview ?? null };
  }

  async saveEncryptedDraft(params: {
    chatId: string;
    encryptedDraftMd: string;
    encryptedDraftPreview?: string | null;
  }): Promise<EncryptedDraft> {
    const { ws } = await this.openWsClient();
    try {
      const receipt = ws.waitForMessage(
        "draft_update_receipt",
        (payload) => (payload as Record<string, unknown>).chat_id === params.chatId,
      );
      await ws.sendAsync("update_draft", {
        chat_id: params.chatId,
        encrypted_draft_md: params.encryptedDraftMd,
        encrypted_draft_preview: params.encryptedDraftPreview ?? null,
      });
      const response = await receipt;
      const draftV = Number((response.payload as Record<string, unknown>).draft_v ?? 0);
      this.storeEncryptedDraft({
        chatId: params.chatId,
        encryptedDraftMd: params.encryptedDraftMd,
        encryptedDraftPreview: params.encryptedDraftPreview ?? null,
        draftV,
      });
      return {
        chatId: params.chatId,
        encryptedDraftMd: params.encryptedDraftMd,
        encryptedDraftPreview: params.encryptedDraftPreview ?? null,
        draftV,
      };
    } finally {
      ws.close();
    }
  }

  async listDrafts(forceRefresh = false): Promise<DecryptedDraft[]> {
    if (forceRefresh) await this.reconcileDraftVersions();
    const cache = await this.ensureSynced(forceRefresh);
    const drafts: DecryptedDraft[] = [];
    for (const chat of cache.chats) {
      const draft = await this.decryptCachedDraft(chat);
      if (draft) drafts.push(draft);
    }
    return drafts;
  }

  async getDraft(chatId: string, forceRefresh = false): Promise<DecryptedDraft | null> {
    if (forceRefresh) await this.reconcileDraftVersions();
    const cache = await this.ensureSynced(forceRefresh);
    const chat = cache.chats.find((entry) => String(entry.details.id ?? "") === chatId);
    return chat ? this.decryptCachedDraft(chat) : null;
  }

  async clearDraft(chatId: string): Promise<void> {
    const { ws } = await this.openWsClient();
    try {
      const receipt = ws.waitForMessage(
        "draft_delete_receipt",
        (payload) => (payload as Record<string, unknown>).chat_id === chatId,
      );
      await ws.sendAsync("delete_draft", { chat_id: chatId });
      await receipt;
    } finally {
      ws.close();
    }
    const cache = loadSyncCache();
    if (!cache) return;
    const chat = cache.chats.find((entry) => String(entry.details.id ?? "") === chatId);
    if (chat) {
      delete chat.details.encrypted_draft_md;
      delete chat.details.encrypted_draft_preview;
      chat.details.draft_v = 0;
      if (chat.messages.length === 0 && !chat.details.encrypted_chat_key) {
        cache.chats = cache.chats.filter((entry) => entry !== chat);
      }
      saveSyncCache(cache);
    }
  }

  async reconcileDraftVersions(): Promise<Record<string, number>> {
    const cache = loadSyncCache();
    const drafts = (cache?.chats ?? []).filter(
      (chat) => typeof chat.details.encrypted_draft_md === "string",
    );
    if (drafts.length === 0) return {};
    const { ws } = await this.openWsClient();
    try {
      const response = ws.waitForMessage("draft_versions_response");
      await ws.sendAsync("get_draft_versions", {
        chats: drafts.map((chat) => ({
          chat_id: String(chat.details.id),
          client_draft_v: Number(chat.details.draft_v ?? 0),
        })),
      });
      const frame = await response;
      const versions = (frame.payload as { versions?: Record<string, number> }).versions ?? {};
      for (const chat of drafts) {
        const chatId = String(chat.details.id);
        if (versions[chatId] === 0) {
          delete chat.details.encrypted_draft_md;
          delete chat.details.encrypted_draft_preview;
          chat.details.draft_v = 0;
        }
      }
      if (cache) saveSyncCache(cache);
      return versions;
    } finally {
      ws.close();
    }
  }

  private storeEncryptedDraft(draft: EncryptedDraft): void {
    const cache = loadSyncCache() ?? {
      syncedAt: 0,
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };
    let chat = cache.chats.find((entry) => String(entry.details.id ?? "") === draft.chatId);
    if (!chat) {
      chat = { details: { id: draft.chatId }, messages: [] };
      cache.chats.unshift(chat);
    }
    chat.details.encrypted_draft_md = draft.encryptedDraftMd;
    chat.details.encrypted_draft_preview = draft.encryptedDraftPreview;
    chat.details.draft_v = draft.draftV;
    cache.syncedAt = Date.now();
    cache.loadedChatCount = cache.chats.length;
    saveSyncCache(cache);
  }

  private async decryptCachedDraft(chat: CachedChat): Promise<DecryptedDraft | null> {
    const encryptedDraftMd = chat.details.encrypted_draft_md;
    if (typeof encryptedDraftMd !== "string") return null;
    const encryptedPreview = typeof chat.details.encrypted_draft_preview === "string"
      ? chat.details.encrypted_draft_preview
      : null;
    const masterKey = this.getMasterKeyBytes();
    const markdown = await decryptWithAesGcmCombined(encryptedDraftMd, masterKey);
    if (markdown === null) throw new Error("Failed to decrypt draft markdown.");
    const preview = encryptedPreview
      ? await decryptWithAesGcmCombined(encryptedPreview, masterKey)
      : markdown.slice(0, 160);
    return {
      chatId: String(chat.details.id ?? ""),
      encryptedDraftMd,
      encryptedDraftPreview: encryptedPreview,
      draftV: Number(chat.details.draft_v ?? 0),
      markdown,
      preview,
    };
  }

  async searchChats(query: string): Promise<ChatListItem[]> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const normalized = query.trim().toLowerCase();
    const results: ChatListItem[] = [];
    for (const cached of cache.chats) {
      const item = await this.decryptChatListItem(cached, masterKey);
      const title = (item.title ?? "").toLowerCase();
      const summary = (item.summary ?? "").toLowerCase();
      const cat = (item.category ?? "").toLowerCase();
      const mate = (item.mateName ?? "").toLowerCase();
      if (
        title.includes(normalized) ||
        summary.includes(normalized) ||
        item.id.includes(normalized) ||
        cat.includes(normalized) ||
        mate.includes(normalized)
      ) {
        results.push(item);
      }
    }
    return results;
  }

  /**
   * Get the decrypted messages for a specific chat.
   *
   * Lookup order (most-recent-first for all title matches):
   * 1. Exact full UUID match
   * 2. Short 8-char prefix match
   * 3. Exact title match (case-insensitive, most recent first)
   * 4. Partial title match (case-insensitive, most recent first)
   *
   * @param query Full UUID, 8-char short ID, or chat title.
   */
  async getChatMessages(query: string): Promise<{
    chat: ChatListItem;
    messages: DecryptedMessage[];
  }> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const normalized = query.trim().toLowerCase();

    // "last" / "__last__" → most recently modified chat (cache is sorted desc by timestamp)
    let found: (typeof cache.chats)[0] | undefined;
    if (query === "__last__" || query.toLowerCase() === "last") {
      if (cache.chats.length === 0) {
        throw new Error(
          "No chats found in local cache. Run 'openmates chats list' to sync.",
        );
      }
      found = cache.chats[0];
    }

    // Pass 1: fast ID match (no decryption needed)
    if (!found) {
      found = cache.chats.find(
        (c) =>
          String(c.details.id) === query ||
          String(c.details.id).startsWith(query),
      );
    }

    // Pass 2: title match — decrypt all chats and match by title.
    // The cache is already sorted most-recent-first, so the first match wins.
    if (!found) {
      for (const cached of cache.chats) {
        const item = await this.decryptChatListItem(cached, masterKey);
        const title = (item.title ?? "").toLowerCase();
        if (title === normalized) {
          found = cached;
          break;
        }
      }
    }

    // Pass 3: partial title match (most recent first)
    if (!found) {
      for (const cached of cache.chats) {
        const item = await this.decryptChatListItem(cached, masterKey);
        const title = (item.title ?? "").toLowerCase();
        if (title.includes(normalized)) {
          found = cached;
          break;
        }
      }
    }

    if (!found) {
      throw new Error(
        `Chat '${query}' not found. Try 'openmates chats search "${query}"' to browse matches.`,
      );
    }

    const chatItem = await this.decryptChatListItem(found, masterKey);
    const encKey =
      typeof found.details.encrypted_chat_key === "string"
        ? found.details.encrypted_chat_key
        : null;
    const chatKeyBytes = encKey
      ? await this.decryptChatKey(encKey, masterKey)
      : null;

    const messages: DecryptedMessage[] = [];
    for (const raw of found.messages) {
      const m =
        typeof raw === "string"
          ? (JSON.parse(raw) as Record<string, unknown>)
          : (raw as Record<string, unknown>);
      const content =
        typeof m.encrypted_content === "string" && chatKeyBytes
          ? await decryptWithAesGcmCombined(m.encrypted_content, chatKeyBytes)
          : null;
      const senderName =
        typeof m.encrypted_sender_name === "string" && chatKeyBytes
          ? await decryptWithAesGcmCombined(
              m.encrypted_sender_name,
              chatKeyBytes,
            )
          : null;
      const msgCategory =
        typeof m.encrypted_category === "string" && chatKeyBytes
          ? await decryptWithAesGcmCombined(m.encrypted_category, chatKeyBytes)
          : null;
      const modelName =
        typeof m.encrypted_model_name === "string" && chatKeyBytes
          ? await decryptWithAesGcmCombined(
              m.encrypted_model_name,
              chatKeyBytes,
            )
          : null;

      // Resolve embed IDs for this message.
      // The WS payload doesn't include embed_ids in messages; instead each embed
      // record carries hashed_message_id = SHA-256(client_message_id).
      // We match on that to find embeds belonging to this message.
      const clientMsgId = String(
        m.client_message_id ?? m.id ?? m.message_id ?? "",
      );
      let msgEmbedIds: string[] = [];
      if (clientMsgId && cache.embeds.length > 0) {
        const { createHash } = await import("node:crypto");
        const hashed = createHash("sha256").update(clientMsgId).digest("hex");
        msgEmbedIds = cache.embeds
          .filter(
            (e) =>
              e.hashed_message_id === hashed &&
              // Only include parent embeds (no parent_embed_id).
              // Child embeds inherit the parent's key and are loaded
              // via the parent's embed_ids — showing them separately
              // causes confusing duplicates under the user message.
              !e.parent_embed_id,
          )
          .map((e) => String(e.embed_id ?? e.id ?? ""))
          .filter(Boolean);
      }

      messages.push({
        id: String(m.id ?? m.message_id ?? ""),
        chatId: String(m.chat_id ?? chatItem.id),
        role: String(m.role ?? "unknown"),
        content: content ?? "",
        senderName,
        category: msgCategory,
        modelName,
        createdAt: typeof m.created_at === "number" ? m.created_at : 0,
        embedIds: msgEmbedIds,
      });
    }
    messages.sort((a, b) => a.createdAt - b.createdAt);
    return { chat: chatItem, messages };
  }

  /**
   * Get a decrypted embed by embed_id (full UUID or short 8-char prefix).
   *
   * Key unwrapping strategy (in priority order):
   * 1. Find embed key with key_type="master" for this embed →
   *    unwrap with master key directly (simplest, no chat needed).
   * 2. Find embed key with key_type="chat" for this embed →
   *    find the chat, decrypt chat key with master key, unwrap embed key.
   *
   * hashed_embed_id in the key table = SHA-256(embed.embed_id).
   */
  async getEmbed(embedIdOrShort: string): Promise<DecryptedEmbed> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();

    const embed = cache.embeds.find(
      (e) =>
        String(e.embed_id ?? "").startsWith(embedIdOrShort) ||
        String(e.id ?? "").startsWith(embedIdOrShort),
    );
    if (!embed) {
      throw new Error(
        `Embed '${embedIdOrShort}' not found in local cache. Run 'openmates chats list' to sync first.`,
      );
    }

    const embedId = String(embed.embed_id ?? embed.id ?? "");

    // Compute hashed_embed_id = SHA-256(embed.embed_id) — must match server computation.
    // Server always hashes embed_id (UUID), never the short id. Use the same value
    // used for embedId above so they stay consistent.
    const { createHash } = await import("node:crypto");
    const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");

    const embedKeyBytes = await this.resolveEmbedKey(
      cache,
      masterKey,
      embed,
      embedId,
      hashedEmbedId,
    );

    const decryptField = async (field: string): Promise<string | null> => {
      const val = embed[field];
      if (typeof val !== "string" || !embedKeyBytes) return null;
      return decryptWithAesGcmCombined(val, embedKeyBytes);
    };

    const type = await decryptField("encrypted_type");
    const textPreview = await decryptField("encrypted_text_preview");
    let content: Record<string, unknown> | null = null;
    const rawContent = await decryptField("encrypted_content");
    if (rawContent) {
      try {
        content = JSON.parse(rawContent) as Record<string, unknown>;
      } catch {
        // Content stored as YAML-like key:value lines (common for skill embeds).
        // Parse into an object so per-type renderers can use standard field names.
        content = parseYamlLikeContent(rawContent);
      }
    }
    content = await this.refreshRemotionVideoCreateContent(embedId, content);

    // Derive type/appId/skillId from content if not on the embed record itself
    const strVal = (v: unknown) =>
      typeof v === "string" && v.trim() ? v.trim() : null;
    const resolvedType = type ?? strVal(content?.type) ?? null;
    const resolvedAppId =
      typeof embed.app_id === "string"
        ? embed.app_id
        : (strVal(content?.app_id) ?? null);
    const resolvedSkillId =
      typeof embed.skill_id === "string"
        ? embed.skill_id
        : (strVal(content?.skill_id) ?? null);

    return {
      id: embedId,
      embedId,
      type: resolvedType,
      textPreview,
      content,
      appId: resolvedAppId,
      skillId: resolvedSkillId,
      createdAt: typeof embed.created_at === "number" ? embed.created_at : null,
    };
  }

  private async refreshRemotionVideoCreateContent(
    embedId: string,
    content: Record<string, unknown> | null,
  ): Promise<Record<string, unknown> | null> {
    if (!content || content.app_id !== "videos" || content.skill_id !== "create") {
      return content;
    }
    const status = typeof content.status === "string" ? content.status : "";
    if (!["processing", "rendering", "needs_rerender"].includes(status)) {
      return content;
    }

    const response = await this.http.get<{
      content?: Record<string, unknown>;
      status?: string;
    }>(`/v1/videos/remotion/${encodeURIComponent(embedId)}`, this.getCliRequestHeaders());
    if (!response.ok || !response.data?.content) {
      return content;
    }
    const refreshed = response.data.content;
    if (refreshed.app_id !== "videos" || refreshed.skill_id !== "create") {
      return content;
    }
    return refreshed;
  }

  /**
   * Build a slug → DecryptedEmbed index for child embeds of specific parents.
   *
   * Child embeds store an `embed_ref` slug in their encrypted content (e.g.
   * "youtube.com-p3f", "marineinsight.com-wrP"). This method only decrypts
   * child embeds whose parent_embed_id is in the provided set, keeping it
   * fast even when the cache has thousands of embeds.
   *
   * @param parentEmbedIds - Set of parent embed IDs to resolve children for.
   *   Pass the embed IDs extracted from the chat's message JSON blocks.
   *
   * Mirrors the web app's embedStore.embedRefToIdIndex (in-memory only).
   */
  async buildEmbedRefIndex(
    parentEmbedIds: Set<string>,
  ): Promise<Map<string, DecryptedEmbed>> {
    if (parentEmbedIds.size === 0) return new Map();

    const cache = await this.ensureSynced();
    const index = new Map<string, DecryptedEmbed>();

    // Only decrypt child embeds whose parent is in the target set
    const childEmbeds = cache.embeds.filter((e) => {
      const parentId = String(
        (e as Record<string, unknown>).parent_embed_id ?? "",
      );
      return parentId && parentEmbedIds.has(parentId);
    });

    for (const rawEmbed of childEmbeds) {
      const embedId = String(rawEmbed.embed_id ?? rawEmbed.id ?? "");
      if (!embedId) continue;

      try {
        const decrypted = await this.getEmbed(embedId);
        const ref =
          typeof decrypted.content?.embed_ref === "string"
            ? decrypted.content.embed_ref
            : null;
        if (ref) {
          index.set(ref, decrypted);
        }
      } catch {
        // Embed decryption failed — skip silently (key mismatch, etc.)
      }
    }

    return index;
  }

  /**
   * Resolve the embed decryption key for a given embed.
   *
   * Strategy:
   * 1. Master key type — decrypt embed key with master key directly
   * 2. Chat key type — unwrap via chat key → then decrypt embed key
   * 3. Parent key fallback — child embeds inherit the parent's embed key.
   *    If the embed has a parent_embed_id, resolve the parent's key and
   *    reuse it (matching the web app's embedStore.getEmbedKey pattern).
   */
  private async resolveEmbedKey(
    cache: SyncCache,
    masterKey: Uint8Array,
    embed: Record<string, unknown>,
    embedId: string,
    hashedEmbedId: string,
    visited: Set<string> = new Set(),
  ): Promise<Uint8Array | null> {
    if (visited.has(embedId)) return null; // prevent cycles
    visited.add(embedId);

    const { createHash } = await import("node:crypto");

    // Strategy 1: master key type
    const masterKeyEntry = cache.embedKeys.find(
      (ek) =>
        ek.hashed_embed_id === hashedEmbedId &&
        String(ek.key_type) === "master",
    );
    if (
      masterKeyEntry &&
      typeof masterKeyEntry.encrypted_embed_key === "string"
    ) {
      const key = await decryptBytesWithAesGcm(
        masterKeyEntry.encrypted_embed_key as string,
        masterKey,
      );
      if (key) return key;
    }

    // Strategy 2: chat key type
    const chatKeyEntry = cache.embedKeys.find(
      (ek) =>
        ek.hashed_embed_id === hashedEmbedId && String(ek.key_type) === "chat",
    );
    if (chatKeyEntry && typeof chatKeyEntry.encrypted_embed_key === "string") {
      const hashedChatId = String(chatKeyEntry.hashed_chat_id ?? "");
      const owningChat = cache.chats.find((c) => {
        const chatHash = createHash("sha256")
          .update(String(c.details.id ?? ""))
          .digest("hex");
        return chatHash === hashedChatId;
      });
      if (owningChat) {
        const encChatKey =
          typeof owningChat.details.encrypted_chat_key === "string"
            ? owningChat.details.encrypted_chat_key
            : null;
        if (encChatKey) {
          const chatKeyBytes = await decryptBytesWithAesGcm(
            encChatKey,
            masterKey,
          );
          if (chatKeyBytes) {
            const key = await decryptBytesWithAesGcm(
              chatKeyEntry.encrypted_embed_key as string,
              chatKeyBytes,
            );
            if (key) return key;
          }
        }
      }
    }

    // Strategy 3: parent key fallback — child embeds inherit parent's key.
    // The embed record has parent_embed_id; resolve the parent's key and reuse it.
    const parentEmbedId =
      typeof embed.parent_embed_id === "string" ? embed.parent_embed_id : null;
    if (parentEmbedId && parentEmbedId !== embedId) {
      const parentEmbed = cache.embeds.find(
        (e) => String(e.embed_id ?? e.id ?? "") === parentEmbedId,
      );
      if (parentEmbed) {
        const parentFullId = String(
          parentEmbed.embed_id ?? parentEmbed.id ?? "",
        );
        const parentHashedId = createHash("sha256")
          .update(parentFullId)
          .digest("hex");
        const parentKey = await this.resolveEmbedKey(
          cache,
          masterKey,
          parentEmbed as Record<string, unknown>,
          parentFullId,
          parentHashedId,
          visited,
        );
        if (parentKey) return parentKey;
      }
    }

    return null;
  }

  /**
   * Resolve a short chat ID (first 8 chars) or partial title to a full UUID.
   * Accepts full UUIDs unchanged. Returns undefined if no match found.
   */
  async resolveFullChatId(idOrShort: string): Promise<string | undefined> {
    // Try stale cache first — chat IDs don't change, so any cached version
    // is sufficient for short-ID resolution. Only sync if the cache is empty
    // or the ID wasn't found (possibly a newly created chat).
    const staleCache = loadSyncCache();
    const lower = idOrShort.toLowerCase();

    if (staleCache) {
      for (const chat of staleCache.chats) {
        const fullId = String(chat.details.id ?? "");
        if (fullId === idOrShort) return fullId;
        if (fullId.toLowerCase().startsWith(lower)) return fullId;
      }
    }

    // Not found in stale cache (or no cache) — force a fresh sync
    const freshCache = await this.ensureSynced(/* forceRefresh */ true);
    for (const chat of freshCache.chats) {
      const fullId = String(chat.details.id ?? "");
      if (fullId === idOrShort) return fullId;
      if (fullId.toLowerCase().startsWith(lower)) return fullId;
    }
    return undefined;
  }

  /**
   * List new-chat suggestions from the local sync cache, decrypted.
   *
   * These are the same suggestions shown in the "What would you like to do?" row
   * on the web app's home screen. They are generated by the AI post-processor
   * after each conversation and stored encrypted in Directus.
   *
   * Mirrors: NewChatSuggestions.svelte + newChatSuggestions.ts (web app)
   *
   * @param limit Maximum number of suggestions to return (default: 10)
   */
  async listNewChatSuggestions(
    limit = 10,
  ): Promise<DecryptedNewChatSuggestion[]> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const rawSuggestions = cache.newChatSuggestions ?? [];

    const results: DecryptedNewChatSuggestion[] = [];
    for (const raw of rawSuggestions) {
      const encryptedSuggestion =
        typeof raw.encrypted_suggestion === "string"
          ? raw.encrypted_suggestion
          : null;
      if (!encryptedSuggestion) continue;

      const plaintext = await decryptWithAesGcmCombined(
        encryptedSuggestion,
        masterKey,
      );
      if (!plaintext) continue; // skip suggestions we can't decrypt

      results.push({
        id: typeof raw.id === "string" ? raw.id : String(raw.id ?? ""),
        chatId: typeof raw.chat_id === "string" ? raw.chat_id : null,
        body: stripLegacySuggestionPrefix(plaintext),
        createdAt: typeof raw.created_at === "number" ? raw.created_at : 0,
      });

      if (results.length >= limit) break;
    }

    // Sort newest first (created_at descending)
    results.sort((a, b) => b.createdAt - a.createdAt);
    return results;
  }

  /**
   * Decrypt the follow-up request suggestions for a chat.
   * Reads encrypted_follow_up_request_suggestions from the sync cache details.
   * Returns an empty array if not present or decryption fails.
   *
   * Mirrors: chat_actions_store.ts / FollowUpSuggestions.svelte (web app)
   */
  async getChatFollowUpSuggestions(chatId: string): Promise<string[]> {
    const cachedMatch = loadSyncCache()?.chats.find(
      (c) =>
        String(c.details.id ?? "") === chatId ||
        String(c.details.id ?? "").startsWith(chatId),
    );
    const refreshChatId = String(cachedMatch?.details.id ?? chatId);
    const cache = await this.ensureSynced(true, [refreshChatId]);
    const masterKey = this.getMasterKeyBytes();

    const found = cache.chats.find(
      (c) =>
        String(c.details.id ?? "") === chatId ||
        String(c.details.id ?? "").startsWith(chatId),
    );
    if (!found) return [];

    const encKey =
      typeof found.details.encrypted_chat_key === "string"
        ? found.details.encrypted_chat_key
        : null;
    if (!encKey) return [];

    const chatKeyBytes = await this.decryptChatKey(encKey, masterKey);
    if (!chatKeyBytes) return [];

    const encSuggestions =
      typeof found.details.encrypted_follow_up_request_suggestions === "string"
        ? found.details.encrypted_follow_up_request_suggestions
        : null;
    if (!encSuggestions) return [];

    const plaintext = await decryptWithAesGcmCombined(
      encSuggestions,
      chatKeyBytes,
    );
    if (!plaintext) return [];

    try {
      const parsed = JSON.parse(plaintext);
      if (Array.isArray(parsed)) {
        return (parsed as unknown[])
          .filter((s): s is string => typeof s === "string" && s.length > 0)
          .map(stripLegacySuggestionPrefix)
          .filter((s) => s.length > 0);
      }
    } catch {
      // Corrupted — silently return empty
    }
    return [];
  }

  async sendMessage(params: {
    message: string;
    chatId?: string;
    incognito?: boolean;
    /** Streaming callback — fires for typing, chunk, and done events. */
    onStream?: (event: import("./ws.js").StreamEvent) => void;
    /** Sub-chat lifecycle callback for progress/status output. */
    onSubChatEvent?: (event: SubChatEvent) => void;
    /** Approval callback used when the server asks before starting a large sub-chat batch. */
    onSubChatApprovalRequest?: (
      request: SubChatApprovalRequest,
    ) => boolean | Promise<boolean>;
    /** Explicit opt-in for automatic sub-chat approval in non-interactive runs. */
    autoApproveSubChats?: boolean;
    /** Explicit opt-in to approve server-requested memory categories in non-interactive runs. */
    autoApproveMemories?: boolean;
    /** Encrypted file embeds to attach to the message (code, images, PDFs). */
    encryptedEmbeds?: EncryptedEmbed[];
    /** Prepared embeds to encrypt after the real chat/message IDs are known. */
    preparedEmbeds?: PreparedEmbed[];
    /** Placeholder-to-original PII mappings created before sending the user message. */
    piiMappings?: Array<{ placeholder: string; original: string; type: string }>;
    /** Redacted connected-account directory for AI-visible account selection. */
    connectedAccountDirectory?: ConnectedAccountDirectoryEntry[];
    /** Refresh-token envelopes to convert into short-lived token refs before send. */
    connectedAccountTokenRefInputs?: ConnectedAccountTurnTokenRefInput[];
    /** Non-sensitive CLI benchmark labels for usage-source grouping. */
    benchmarkMetadata?: BenchmarkMetadata;
    /** Full plaintext history for incognito benchmark turns. */
    messageHistory?: BenchmarkHistoryMessage[];
    /** Account-wide Learning Mode context when already known by the caller. */
    learningMode?: LearningModeContext;
    /** Start collecting before send for latency-sensitive benchmark turns. */
    precollectResponse?: boolean;
    /** Override the WebSocket AI response collection timeout for long-running turns. */
    responseTimeoutMs?: number;
  }): Promise<{
    status: "completed" | "waiting_for_user";
    chatId: string;
    messageId: string | null;
    assistant: string;
    category: string | null;
    modelName: string | null;
    mateName: string | null;
    /** Follow-up suggestions from post-processing (may be empty for incognito chats). */
    followUpSuggestions: string[];
    /** Review-only task proposals from post-processing. */
    taskProposals: TaskProposalEvent[];
    /** Review-only task update proposals from post-processing. */
    taskUpdateProposals: TaskUpdateProposalEvent[];
    /** Main-processor task tool events observed during the turn. */
    taskEvents: TaskEventFrame[];
    /** Pending task update jobs awaiting client encryption/persistence. */
    pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[];
    /** Sub-chat lifecycle frames observed while collecting the parent response. */
    subChatEvents: SubChatEvent[];
    /** Memory permission requests observed and optionally approved while collecting the response. */
    appSettingsMemoryRequests: Array<{
      requestId: string | null;
      requestedKeys: string[];
      approvedKeys: string[];
      entryCount: number;
    }>;
  }> {
    // Resolve short IDs (8-char prefix) to full UUIDs via sync cache.
    // Full UUIDs and undefined (new chat) pass through unchanged.
    let chatId: string;
    if (!params.chatId) {
      chatId = randomUUID();
    } else if (params.chatId.length < 36) {
      // Short ID — resolve from sync cache
      const resolved = await this.resolveFullChatId(params.chatId);
      if (!resolved) {
        throw new Error(
          `Chat not found for '${params.chatId}'. Use a full UUID or the first 8 characters of an existing chat ID.`,
        );
      }
      chatId = resolved;
    } else {
      chatId = params.chatId;
    }

    let availableMemories: DecryptedMemoryEntry[] = [];
    let memoryMetadataKeys: string[] = [];
    if (!params.incognito) {
      try {
        availableMemories = await this.listMemories();
        memoryMetadataKeys = [
          ...new Set(
            availableMemories
              .filter((memory) => memory.app_id && memory.item_type)
              .map((memory) => `${memory.app_id}-${memory.item_type}`),
          ),
        ];
      } catch (error) {
        if (params.autoApproveMemories) {
          const message = error instanceof Error ? error.message : String(error);
          throw new Error(`Failed to load memories for auto-approval: ${message}`);
        }
      }
    }

    const { ws, session, ownerId } = await this.openWsClient();
    if (!params.incognito && !ownerId) {
      ws.close();
      throw new Error("Authenticated user identity is required for saved chat recovery.");
    }

    const messageId = randomUUID();
    const createdAt = Math.floor(Date.now() / 1000);
    const isNewChat = !params.chatId;
    // Mark this chat as active so the server streams incremental chunks
    // rather than sending a single background-completion event.
    ws.send("set_active_chat", { chat_id: chatId });

    const connectedAccountDirectory = buildConnectedAccountDirectoryPayload(
      params.connectedAccountDirectory,
    );
    const connectedAccountTokenRefs = params.connectedAccountTokenRefInputs?.length
      ? await this.createTurnTokenRefs({
          chatId,
          messageId,
          refs: params.connectedAccountTokenRefInputs,
        })
      : [];
    assertNoConnectedAccountSecretLeak(connectedAccountTokenRefs);

    const piiMappings = params.piiMappings ?? [];

    // Saved chats must resolve their immutable raw key before constructing the
    // inference request because preflight commits the matching encrypted row.
    let chatKeyBytes: Uint8Array | null = null;
    let encryptedChatKey: string | null = null;
    let baselineMessagesV = 0;
    let terminalExpectedMessagesV = 1;
    let savedTurnId: string | null = null;

    if (!params.incognito) {
      const masterKey = this.getMasterKeyBytes();

      if (isNewChat) {
        chatKeyBytes = globalThis.crypto
          ? new Uint8Array(globalThis.crypto.getRandomValues(new Uint8Array(32)))
          : new Uint8Array(
              (await import("node:crypto")).webcrypto.getRandomValues(
                new Uint8Array(32),
              ),
            );
        encryptedChatKey = await encryptBytesWithAesGcm(
          chatKeyBytes,
          masterKey,
        );
      } else {
        const cache = loadSyncCache() ?? (await this.ensureSynced());
        const chat = cache.chats.find(
          (c) =>
            String(c.details.id ?? "") === chatId ||
            String(c.details.id ?? "").startsWith(chatId),
        );
        if (chat) {
          baselineMessagesV =
            typeof chat.details.messages_v === "number"
              ? chat.details.messages_v
              : 0;
          const encKey =
            typeof chat.details.encrypted_chat_key === "string"
              ? chat.details.encrypted_chat_key
              : null;
          if (encKey) {
            chatKeyBytes = await decryptBytesWithAesGcm(encKey, masterKey);
            encryptedChatKey = encKey;
          }
        }
        if (!chatKeyBytes || !encryptedChatKey) {
          throw new Error(`Encrypted chat key not found for chat '${chatId}'. Sync and try again.`);
        }
      }
    }

    // ── Inference request ──
    // Mirrors: chatSyncServiceSenders.ts sendMessageToServer()

    const messagePayload: Record<string, unknown> = {
      chat_id: chatId,
      client_capabilities: ["task_update_jobs"],
      is_incognito: Boolean(params.incognito),
      message: {
        message_id: messageId,
        chat_id: chatId,
        role: "user",
        sender_name: "User",
        status: "sent",
        content: params.message,
        created_at: createdAt,
        chat_has_title: Boolean(params.chatId),
      },
    };

    if (isNewChat && encryptedChatKey) {
      messagePayload.encrypted_chat_key = encryptedChatKey;
    }

    if (memoryMetadataKeys.length > 0) {
      messagePayload.app_settings_memories_metadata = memoryMetadataKeys;
    }
    if (connectedAccountDirectory) {
      messagePayload.connected_account_directory = connectedAccountDirectory;
    }
    if (connectedAccountTokenRefs.length > 0) {
      messagePayload.connected_account_token_refs = connectedAccountTokenRefs;
    }
    if (params.benchmarkMetadata) {
      messagePayload.benchmark_metadata = params.benchmarkMetadata;
    }
    if (params.learningMode) {
      messagePayload.learning_mode = {
        enabled: params.learningMode.enabled,
        age_group: params.learningMode.ageGroup ?? null,
      };
    }
    if (params.incognito) {
      const providedHistory = (params.messageHistory ?? []).map((historyMessage) => ({
        ...historyMessage,
        chat_id: historyMessage.chat_id ?? chatId,
      }));
      messagePayload.message_history = [...providedHistory, {
        message_id: messageId,
        chat_id: chatId,
        role: "user",
        sender_name: "User",
        content: params.message,
        created_at: createdAt,
      }];
    } else if (isNewChat && params.messageHistory && params.messageHistory.length > 0) {
      messagePayload.message_history = params.messageHistory.map((historyMessage) => ({
        message_id: historyMessage.message_id,
        chat_id: chatId,
        role: historyMessage.role,
        sender_name: historyMessage.sender_name ?? historyMessage.role,
        content: historyMessage.content,
        created_at: historyMessage.created_at,
      }));
    }

    if (params.preparedEmbeds && params.preparedEmbeds.length > 0) {
      messagePayload.embeds = params.preparedEmbeds.map((embed) => ({
        embed_id: embed.embedId,
        type: embed.type,
        content: embed.content,
        status: embed.status,
        text_preview: embed.textPreview,
      }));
    }

    const encryptedEmbeds: EncryptedEmbed[] = [...(params.encryptedEmbeds ?? [])];
    if (!params.incognito && params.preparedEmbeds && params.preparedEmbeds.length > 0) {
      const masterKey = this.getMasterKeyBytes();
      for (const embed of params.preparedEmbeds) {
        const encrypted = await encryptEmbed(
          embed,
          masterKey,
          chatKeyBytes,
          chatId,
          messageId,
          session.hashedEmail,
        );
        if (encrypted) encryptedEmbeds.push(encrypted);
      }
    }

    // Attach encrypted client-created embeds if present.
    // Mirrors: chatSyncServiceSenders.ts encrypted_embeds array.
    if (encryptedEmbeds.length > 0) {
      messagePayload.encrypted_embeds = encryptedEmbeds;
    }

    let precollectedResponse = params.precollectResponse && params.incognito
      ? ws.collectAiResponse(messageId, chatId, { onStream: params.onStream, timeoutMs: params.responseTimeoutMs })
      : null;

    if (!params.incognito && chatKeyBytes && encryptedChatKey) {
      const protocolVersion = 1;
      const chatKeyVersion = 1;
      const turnId = randomUUID();
      savedTurnId = turnId;
      terminalExpectedMessagesV = baselineMessagesV + 1;
      const recoveryKeypair = await deriveChatCompletionRecoveryKeypair(
        Buffer.from(chatKeyBytes).toString("base64url"),
        chatId,
        chatKeyVersion,
      );
      const encryptedContent = await encryptWithAesGcmCombined(
        params.message,
        chatKeyBytes,
      );
      const encryptedUserMessage: Record<string, unknown> = {
        client_message_id: messageId,
        chat_id: chatId,
        encrypted_content: encryptedContent,
        role: "user",
        created_at: createdAt,
        updated_at: createdAt,
      };

      if (piiMappings.length > 0) {
        encryptedUserMessage.encrypted_pii_mappings = await encryptWithAesGcmCombined(
          JSON.stringify(piiMappings),
          chatKeyBytes,
        );
      }

      Object.assign(messagePayload, {
        turn_id: turnId,
        recovery_public_key: recoveryKeypair.publicKey,
        chat_key_version: chatKeyVersion,
      });
      const preflightPayload: Record<string, unknown> = {
        protocol_version: protocolVersion,
        chat_id: chatId,
        turn_id: turnId,
        message_id: messageId,
        chat_key_version: chatKeyVersion,
        encrypted_chat_key: encryptedChatKey,
        recovery_public_key: recoveryKeypair.publicKey,
        expected_messages_v: baselineMessagesV,
        encrypted_user_message: encryptedUserMessage,
        inference_request: messagePayload,
      };
      if (isNewChat) {
        preflightPayload.encrypted_chat_metadata = {
          encrypted_title: await encryptWithAesGcmCombined("", chatKeyBytes),
          encrypted_chat_key: encryptedChatKey,
          created_at: createdAt,
          updated_at: createdAt,
        };
      }

      const preflightAck = ws.waitForMessage(
        "chat_turn_preflight_ack",
        (payload) => (payload as Record<string, unknown>).turn_id === turnId,
      );
      let ackPayload: Record<string, unknown>;
      try {
        await ws.sendAsync("chat_turn_preflight", preflightPayload);
        ackPayload = (await preflightAck).payload as Record<string, unknown>;
      } catch (error) {
        ws.close();
        throw error;
      }
      if (typeof ackPayload.preflight_id !== "string" || !ackPayload.preflight_id) {
        ws.close();
        throw new Error("Encrypted chat preflight acknowledgement omitted preflight_id.");
      }
      Object.assign(messagePayload, {
        protocol_version: protocolVersion,
        preflight_id: ackPayload.preflight_id,
      });
      if (typeof ackPayload.committed_messages_v === "number" && Number.isSafeInteger(ackPayload.committed_messages_v)) {
        terminalExpectedMessagesV = ackPayload.committed_messages_v;
      }
    }
    if (params.precollectResponse && !params.incognito) {
      precollectedResponse = ws.collectAiResponse(messageId, chatId, {
        onStream: params.onStream,
        timeoutMs: params.responseTimeoutMs,
        recoveryTurnId: savedTurnId,
      });
    }
    const confirmed = ws.waitForMessage(
      "chat_message_confirmed",
      (payload) => {
        const eventPayload = payload as Record<string, unknown>;
        return eventPayload.chat_id === chatId && eventPayload.message_id === messageId;
      },
      20_000,
    );
    await ws.sendAsync("chat_message_added", messagePayload);
    await confirmed;

    let assistant = "";
    let assistantMessageId: string | null = null;
    let category: string | null = null;
    let modelName: string | null = null;
    let followUpSuggestions: string[] = [];
    let taskProposals: TaskProposalEvent[] = [];
    let taskUpdateProposals: TaskUpdateProposalEvent[] = [];
    let taskEvents: TaskEventFrame[] = [];
    let pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[] = [];
    let subChatEvents: SubChatEvent[] = [];
    const appSettingsMemoryRequests: Array<{
      requestId: string | null;
      requestedKeys: string[];
      approvedKeys: string[];
      entryCount: number;
    }> = [];

    const numberOrNull = (value: unknown): number | null =>
      typeof value === "number" && Number.isFinite(value) ? value : null;

    const isApprovalWithinServerLimits = (request: SubChatApprovalRequest): boolean => {
      const count = request.subChats.length;
      if (count === 0) return false;
      if (request.remainingSubChats !== null && count > request.remainingSubChats) {
        return false;
      }
      if (
        request.maxDirectSubChats !== null &&
        request.existingSubChats !== null &&
        request.existingSubChats + count > request.maxDirectSubChats
      ) {
        return false;
      }
      return true;
    };

    const isAutoApprovalWithinServerLimits = (
      request: SubChatApprovalRequest,
    ): boolean => {
      if (!isApprovalWithinServerLimits(request)) return false;
      return (
        request.maxAutoSubChats === null ||
        request.subChats.length <= request.maxAutoSubChats
      );
    };

    const handleSubChatEvent = async (event: SubChatEvent) => {
      params.onSubChatEvent?.(event);

      if (event.type === "spawn_sub_chats") {
        if (params.incognito || !chatKeyBytes) return;
        const rawSubChats = event.payload.sub_chats;
        if (!Array.isArray(rawSubChats)) return;

        const metadataPayloads = await buildSubChatEncryptedMetadataPayloads({
          parentChatId: chatId,
          parentChatKey: chatKeyBytes,
          encryptedParentChatKey: encryptedChatKey,
          subChats: rawSubChats as CliSubChatRequest[],
        });
        for (const metadataPayload of metadataPayloads) {
          await ws.sendAsync("encrypted_chat_metadata", metadataPayload);
        }
        return;
      }

      if (event.type !== "sub_chat_confirmation_required") return;

      const payload = event.payload;
      const confirmationChatId =
        typeof payload.chat_id === "string" ? payload.chat_id : chatId;
      const taskId = typeof payload.task_id === "string" ? payload.task_id : null;
      const subChats = Array.isArray(payload.sub_chats)
        ? (payload.sub_chats as CliSubChatRequest[])
        : [];
      if (!taskId) return;

      const request: SubChatApprovalRequest = {
        chatId: confirmationChatId,
        taskId,
        subChats,
        maxAutoSubChats: numberOrNull(payload.max_auto_sub_chats),
        maxDirectSubChats: numberOrNull(payload.max_direct_sub_chats),
        existingSubChats: numberOrNull(payload.existing_sub_chats),
        remainingSubChats: numberOrNull(payload.remaining_sub_chats),
      };
      const withinLimits = isApprovalWithinServerLimits(request);
      const approved = params.autoApproveSubChats
        ? isAutoApprovalWithinServerLimits(request)
        : withinLimits && params.onSubChatApprovalRequest
          ? await params.onSubChatApprovalRequest(request)
          : false;

      await ws.sendAsync(
        "sub_chat_confirmation",
        buildSubChatConfirmationPayload({
          chatId: request.chatId,
          taskId: request.taskId,
          approved,
          approveCount: approved ? request.subChats.length : undefined,
        }),
      );
    };

    const persistSystemMessage = async (systemMessage: AppSettingsMemorySystemMessage) => {
      if (!chatKeyBytes) return;
      await ws.sendAsync("chat_system_message_added", {
        chat_id: chatId,
        message: {
          message_id: systemMessage.message_id,
          role: "system",
          encrypted_content: await encryptWithAesGcmCombined(
            systemMessage.content,
            chatKeyBytes,
          ),
          created_at: systemMessage.created_at,
          user_message_id: systemMessage.user_message_id,
        },
      });
      await ws.waitForMessage(
        "system_message_confirmed",
        (payload) => {
          const p = payload as Record<string, unknown>;
          return p.message_id === systemMessage.message_id;
        },
        20_000,
      );
    };

    const persistMemoryRequestSystemMessage = async (
      event: AppSettingsMemoriesRequestEvent,
    ) => {
      const requestId = event.requestId ?? `${messageId}-memory-request`;
      await persistSystemMessage(buildAppSettingsMemoryRequestSystemMessage({
        userMessageId: messageId,
        requestId,
        requestedKeys: event.requestedKeys,
        createdAt: Math.floor(Date.now() / 1000),
      }));
    };

    const responseCategoriesFromMemories = (
      approvedMemories: Array<{ app_id: string; item_key: string }>,
    ): AppSettingsMemoryResponseCategory[] => {
      const counts = new Map<string, AppSettingsMemoryResponseCategory>();
      for (const memory of approvedMemories) {
        const key = `${memory.app_id}-${memory.item_key}`;
        const existing = counts.get(key);
        if (existing) {
          existing.entryCount += 1;
        } else {
          counts.set(key, {
            appId: memory.app_id,
            itemType: memory.item_key,
            entryCount: 1,
          });
        }
      }
      return [...counts.values()];
    };

    const handleAppSettingsMemoriesRequest = async (
      event: AppSettingsMemoriesRequestEvent,
    ) => {
      await persistMemoryRequestSystemMessage(event);

      if (params.autoApproveMemories) {
        const requested = new Set(event.requestedKeys);
        const unadvertisedKeys = event.requestedKeys.filter(
          (key) => !memoryMetadataKeys.includes(key),
        );
        if (unadvertisedKeys.length > 0) {
          throw new Error(
            `Refusing to auto-approve unadvertised memory categories: ${unadvertisedKeys.join(", ")}`,
          );
        }

        const approvedMemories = availableMemories
          .filter((memory) => requested.has(`${memory.app_id}-${memory.item_type}`))
          .map((memory) => ({
            app_id: memory.app_id,
            item_key: memory.item_type,
            content: memory.data,
          }));
        const approvedKeys = [
          ...new Set(approvedMemories.map((memory) => `${memory.app_id}-${memory.item_key}`)),
        ];
        const categories = responseCategoriesFromMemories(approvedMemories);

        appSettingsMemoryRequests.push({
          requestId: event.requestId,
          requestedKeys: event.requestedKeys,
          approvedKeys,
          entryCount: approvedMemories.length,
        });

        await ws.sendAsync("app_settings_memories_confirmed", {
          chat_id: event.chatId,
          app_settings_memories: approvedMemories,
        });
        await persistSystemMessage(buildAppSettingsMemoryResponseSystemMessage({
          userMessageId: messageId,
          messageId: `${messageId}-memory-response`,
          action: "included",
          categories,
          createdAt: Math.floor(Date.now() / 1000),
        }));
        return;
      }

      appSettingsMemoryRequests.push({
        requestId: event.requestId,
        requestedKeys: event.requestedKeys,
        approvedKeys: [],
        entryCount: 0,
      });
      throw new Error(
        `The assistant requested memories (${event.requestedKeys.join(", ")}). ` +
          "Rerun with --auto-approve-memories to explicitly approve requested memory categories from the CLI, " +
          "or continue this chat in the web app to approve or reject the request.",
      );
    };

    const persistedTaskEventIds = new Set<string>();
    const persistTaskEventSystemMessages = async (events: TaskEventFrame[]) => {
      if (!chatKeyBytes || events.length === 0) return;
      for (const event of events) {
        if (persistedTaskEventIds.has(event.event_id)) continue;
        await this.persistEncryptedSystemMessage(
          ws,
          await buildTaskEventSystemMessage({
            chatKey: chatKeyBytes,
            userMessageId: messageId,
            event,
          }),
          chatId,
        );
        persistedTaskEventIds.add(event.event_id);
      }
    };

    const streamOpts = {
      onStream: params.onStream,
      onSubChatEvent: handleSubChatEvent,
      onAppSettingsMemoriesRequest: handleAppSettingsMemoriesRequest,
    };

    if (params.incognito) {
      try {
        const resp = await (precollectedResponse ?? ws.collectAiResponse(messageId, chatId, {
          ...streamOpts,
          timeoutMs: params.responseTimeoutMs,
          recoveryTurnId: savedTurnId,
        }));
        assistantMessageId = resp.messageId;
        assistant = resp.content;
        category = resp.category;
        modelName = resp.modelName;
        taskEvents = resp.taskEvents;
        pendingTaskUpdateJobs = resp.pendingTaskUpdateJobs;
        subChatEvents = resp.subChatEvents;
        // Incognito chats are not post-processed — follow-up suggestions are not stored.
        if (resp.status === "waiting_for_user") {
          return {
            status: resp.status,
            chatId,
            messageId: assistantMessageId,
            assistant,
            category,
            modelName,
            mateName: category ? MATE_NAMES[category] ?? null : null,
            followUpSuggestions,
            taskProposals,
            taskUpdateProposals,
            taskEvents,
            pendingTaskUpdateJobs,
            subChatEvents,
            appSettingsMemoryRequests,
          };
        }
      } finally {
        ws.close();
      }
    } else {
      try {
        const resp = await (precollectedResponse ?? ws.collectAiResponse(messageId, chatId, {
          ...streamOpts,
          timeoutMs: params.responseTimeoutMs,
        }));
        assistantMessageId = resp.messageId;
        assistant = resp.content;
        category = resp.category;
        modelName = resp.modelName;
        followUpSuggestions = resp.followUpSuggestions;
        taskProposals = resp.taskProposals;
        taskUpdateProposals = resp.taskUpdateProposals;
        taskEvents = resp.taskEvents;
        pendingTaskUpdateJobs = resp.pendingTaskUpdateJobs;
        subChatEvents = resp.subChatEvents;

        if (resp.status === "waiting_for_user") {
          return {
            status: resp.status,
            chatId,
            messageId: assistantMessageId,
            assistant,
            category,
            modelName,
            mateName: category ? MATE_NAMES[category] ?? null : null,
            followUpSuggestions,
            taskProposals,
            taskUpdateProposals,
            taskEvents,
            pendingTaskUpdateJobs,
            subChatEvents,
            appSettingsMemoryRequests,
          };
        }

        if (chatKeyBytes) {
          if (!resp.recoveryJobId || !savedTurnId || !ownerId) {
            throw new Error("Saved chat completion did not include recoverable terminal identity.");
          }
          const recoveryJobId = resp.recoveryJobId;
          const claimPromise = ws.waitForMessage(
            "recovery_job_claimed",
            (payload) => (payload as Record<string, unknown>).job_id === recoveryJobId,
            20_000,
          );
          await ws.sendAsync("recovery_job_claim", {
            protocol_version: 1,
            job_id: recoveryJobId,
          });
          const claim = (await claimPromise).payload as Record<string, unknown>;
          const leaseToken = typeof claim.lease_token === "string" ? claim.lease_token : null;
          const leaseGeneration = typeof claim.lease_generation === "number"
            && Number.isSafeInteger(claim.lease_generation)
            ? claim.lease_generation
            : null;
          const assistantId = typeof claim.assistant_message_id === "string"
            ? claim.assistant_message_id
            : null;
          const keyVersion = typeof claim.chat_key_version === "number"
            && Number.isSafeInteger(claim.chat_key_version)
            ? claim.chat_key_version
            : null;
          if (
            claim.state !== "LEASED"
            || !leaseToken
            || leaseGeneration === null
            || leaseGeneration < 1
            || !assistantId
            || keyVersion === null
            || keyVersion !== 1
            || claim.chat_id !== chatId
            || claim.turn_id !== savedTurnId
            || typeof claim.sealed_payload !== "string"
          ) {
            throw new Error("Recovery job claim returned invalid lease or identity data.");
          }

          const recoveryKeypair = await deriveChatCompletionRecoveryKeypair(
            Buffer.from(chatKeyBytes).toString("base64url"),
            chatId,
            keyVersion,
          );
          let envelope: Record<string, unknown>;
          try {
            envelope = JSON.parse(claim.sealed_payload) as Record<string, unknown>;
          } catch {
            throw new Error("Recovery job contained an invalid sealed envelope.");
          }
          const plaintext = await openChatCompletionRecoveryEnvelope(
            envelope as unknown as ChatCompletionRecoveryEnvelope,
            {
              recoveryPrivateKey: recoveryKeypair.privateKey,
              ownerId,
              chatId,
              turnId: savedTurnId,
              jobId: recoveryJobId,
              assistantMessageId: assistantId,
              keyVersion,
            },
          );
          let recovered: Record<string, unknown>;
          try {
            recovered = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext)) as Record<string, unknown>;
          } catch {
            throw new Error("Recovery job plaintext was not valid UTF-8 JSON.");
          }
          const expectedRecoveryFields = [
            "assistant_message_id",
            "category",
            "chat_id",
            "content",
            "job_id",
            "key_version",
            "model_name",
            "turn_id",
          ];
          if (
            Object.keys(recovered).sort().join(",") !== expectedRecoveryFields.join(",")
            || recovered.assistant_message_id !== assistantId
            || recovered.chat_id !== chatId
            || recovered.turn_id !== savedTurnId
            || recovered.job_id !== recoveryJobId
            || recovered.key_version !== keyVersion
            || typeof recovered.content !== "string"
            || (recovered.category !== null && typeof recovered.category !== "string")
            || (recovered.model_name !== null && typeof recovered.model_name !== "string")
          ) {
            throw new Error("Recovery job plaintext did not match the terminal completion identity.");
          }
          assistant = recovered.content;
          category = recovered.category as string | null;
          modelName = recovered.model_name as string | null;

          const completedAt = Math.floor(Date.now() / 1000);
          const encryptedAssistantContent = await encryptWithAesGcmCombined(
            assistant,
            chatKeyBytes,
          );
          const encryptedSenderName = await encryptWithAesGcmCombined("Assistant", chatKeyBytes);
          const encryptedCategory = recovered.category
            ? await encryptWithAesGcmCombined(recovered.category, chatKeyBytes)
            : undefined;
          const encryptedModelName = recovered.model_name
            ? await encryptWithAesGcmCombined(recovered.model_name, chatKeyBytes)
            : undefined;
          const persistedPromise = ws.waitForMessage(
            "recovery_job_persisted",
            (payload) => (payload as Record<string, unknown>).job_id === recoveryJobId,
            20_000,
          );
          await ws.sendAsync("recovery_job_persist", {
            protocol_version: 1,
            job_id: recoveryJobId,
            lease_token: leaseToken,
            lease_generation: leaseGeneration,
            expected_messages_v: terminalExpectedMessagesV,
            encrypted_assistant_message: {
              client_message_id: assistantId,
              chat_id: chatId,
              encrypted_content: encryptedAssistantContent,
              encrypted_sender_name: encryptedSenderName,
              encrypted_category: encryptedCategory,
              encrypted_model_name: encryptedModelName,
              role: "assistant",
              user_message_id: messageId,
              created_at: completedAt,
              updated_at: completedAt,
            },
          });
          await persistedPromise;
          assistantMessageId = assistantId;
          await this.persistStreamedEmbeds({
            ws,
            embeds: resp.embeds,
            chatId,
            chatKeyBytes,
            fallbackMessageId: assistantId,
          });
          await this.persistPostProcessingMetadata({
            ws,
            chatId,
            chatKeyBytes,
            followUpSuggestions: resp.followUpSuggestions,
            newChatSuggestions: resp.newChatSuggestions,
            encryptedChatKey,
          });
          const persistedTaskJobIds = await this.persistPendingTaskUpdateJobs({
            ws,
            jobs: pendingTaskUpdateJobs,
            events: taskEvents,
            activeChatId: chatId,
            activeChatKeyBytes: chatKeyBytes,
            fallbackUserMessageId: messageId,
            requireActiveTurnEvent: true,
          });
          pendingTaskUpdateJobs = pendingTaskUpdateJobs.filter((job) => !persistedTaskJobIds.has(job.job_id));
          await persistTaskEventSystemMessages(taskEvents);
          clearSyncCache();
        }
      } finally {
        ws.close();
      }
    }

    const mateName = category ? (MATE_NAMES[category] ?? null) : null;
    return {
      status: "completed",
      chatId,
      messageId: assistantMessageId,
      assistant,
      category,
      modelName,
      mateName,
      followUpSuggestions,
      taskProposals,
      taskUpdateProposals,
      taskEvents,
      pendingTaskUpdateJobs,
      subChatEvents,
      appSettingsMemoryRequests,
    };
  }

  private async persistEncryptedSystemMessage(
    ws: OpenMatesWsClient,
    systemMessage: {
      message_id: string;
      role: "system";
      encrypted_content: string;
      created_at: number;
      user_message_id: string;
      task_update_job_id?: string;
    },
    targetChatId: string,
  ): Promise<void> {
    await ws.sendAsync("chat_system_message_added", {
      chat_id: targetChatId,
      message: systemMessage,
    });
    await ws.waitForMessage(
      "system_message_confirmed",
      (payload) => (payload as Record<string, unknown>).message_id === systemMessage.message_id,
      20_000,
    );
  }

  private async persistPendingTaskUpdateJobs(params: {
    ws: OpenMatesWsClient;
    jobs: PendingTaskUpdateJobFrame[];
    events: TaskEventFrame[];
    activeChatId?: string | null;
    activeChatKeyBytes?: Uint8Array | null;
    fallbackUserMessageId?: string | null;
    syncedChats?: CachedChat[];
    requireActiveTurnEvent: boolean;
  }): Promise<Set<string>> {
    const handledJobIds = new Set<string>();
    if (params.jobs.length === 0) return handledJobIds;

    const masterKey = this.getMasterKeyBytes();
    let decryptedTasksCache: DecryptedUserTask[] | null = null;
    const eventByJobId = new Map(params.events.map((event) => [event.task_update_job_id, event]));

    const resolveChatKey = async (targetChatId: string): Promise<Uint8Array> => {
      if (targetChatId === params.activeChatId && params.activeChatKeyBytes) return params.activeChatKeyBytes;
      const findChat = (chats: CachedChat[] | undefined) => chats?.find((chat) => String(chat.details.id ?? "") === targetChatId);
      const targetChat = findChat(params.syncedChats) ?? findChat(loadSyncCache()?.chats);
      const encryptedTargetChatKey = typeof targetChat?.details.encrypted_chat_key === "string"
        ? targetChat.details.encrypted_chat_key
        : null;
      if (!encryptedTargetChatKey) {
        throw new Error(`Encrypted chat key not found for task update job target '${targetChatId}'. Sync and try again.`);
      }
      const targetChatKey = await decryptBytesWithAesGcm(encryptedTargetChatKey, masterKey);
      if (!targetChatKey) {
        throw new Error(`Failed to decrypt chat key for task update job target '${targetChatId}'.`);
      }
      return targetChatKey;
    };

    const listProjectTaskKeyWrappers = async (taskId: string, createdAt: number): Promise<Array<Record<string, unknown>>> => {
      const response = await this.http.get<{ key_wrappers?: Array<Record<string, unknown>> }>(
        `/v1/user-tasks/${encodeURIComponent(taskId)}/key-wrappers`,
        this.getCliRequestHeaders(),
      );
      if (!response.ok) {
        throw new Error(`User task key wrapper list failed with HTTP ${response.status}`);
      }
      return (response.data.key_wrappers ?? [])
        .filter((wrapper) => wrapper.key_type === "project")
        .map((wrapper) => ({
          key_type: "project",
          hashed_project_id: wrapper.hashed_project_id,
          encrypted_task_key: wrapper.encrypted_task_key,
          created_at: typeof wrapper.created_at === "number" ? wrapper.created_at : createdAt,
          expires_at: wrapper.expires_at ?? null,
        }));
    };

    const buildTaskKeyWrappersForChat = async (
      task: DecryptedUserTask,
      targetChatId: string,
      createdAt: number,
    ) => {
      const encryptedTaskKey = task.encrypted.encrypted_task_key;
      if (!encryptedTaskKey) throw new Error(`Task ${task.taskId} is missing encrypted task key.`);
      const taskKey = await decryptBytesWithAesGcm(encryptedTaskKey, masterKey);
      if (!taskKey) throw new Error(`Failed to decrypt task key for ${task.taskId}.`);
      const targetChatKey = await resolveChatKey(targetChatId);
      const existingProjectWrappers = await listProjectTaskKeyWrappers(task.taskId, createdAt);
      const linkedProjectIds = task.linkedProjectIds ?? [];
      if (linkedProjectIds.length > existingProjectWrappers.length) {
        throw new Error(`Task ${task.taskId} is missing project key wrappers required for move persistence.`);
      }
      return [
        {
          key_type: "master",
          encrypted_task_key: await encryptBytesWithAesGcm(taskKey, masterKey),
          created_at: createdAt,
        },
        {
          key_type: "chat",
          hashed_chat_id: computeSHA256(targetChatId),
          encrypted_task_key: await encryptBytesWithAesGcm(taskKey, targetChatKey),
          created_at: createdAt,
        },
        ...existingProjectWrappers,
      ];
    };

    const findTaskForUpdateJob = async (claim: TaskUpdateJobClaimPayload): Promise<DecryptedUserTask> => {
      const chatIds = [claim.source_task_chat_id, claim.chat_id, claim.safe_metadata?.primary_chat_id]
        .filter((value): value is string => typeof value === "string" && value.length > 0);
      for (const candidateChatId of [...new Set(chatIds)]) {
        const scopedTasks = await decryptUserTasks(await this.listUserTasks({ chatId: candidateChatId }), masterKey);
        try {
          return findTask(scopedTasks, claim.task_id);
        } catch (error) {
          if (!(error instanceof Error) || !error.message.includes("was not found")) throw error;
        }
      }
      if (!decryptedTasksCache) {
        decryptedTasksCache = await decryptUserTasks(await this.listUserTasks({ limit: 1000 }), masterKey);
      }
      return findTask(decryptedTasksCache, claim.task_id);
    };

    const taskEventTypeForOperation = (operation: string | null | undefined): string => {
      switch (operation) {
        case "create": return "created";
        case "move": return "moved";
        case "update": return "updated";
        default: return operation || "updated";
      }
    };

    for (const job of params.jobs) {
      if (
        params.requireActiveTurnEvent
        && params.activeChatId
        && !taskUpdateJobBelongsToActiveTurn(job, params.activeChatId, params.events)
      ) {
        handledJobIds.add(job.job_id);
        continue;
      }

      const claimPromise = params.ws.waitForMessage(
        "task_update_job_claimed",
        (payload) => (payload as Record<string, unknown>).job_id === job.job_id,
        20_000,
      );
      await params.ws.sendAsync("task_update_job_claim", {
        protocol_version: 1,
        job_id: job.job_id,
      });
      const claim = (await claimPromise).payload as unknown as TaskUpdateJobClaimPayload;

      const privatePatch = claim.private_patch ?? {};
      const safeMetadata = claim.safe_metadata ?? {};
      const sourceChatId = claim.chat_id ?? job.chat_id ?? params.activeChatId;
      if (!sourceChatId) throw new Error(`Task update job ${job.job_id} is missing a source chat id.`);
      const sourceChatKey = await resolveChatKey(sourceChatId);
      const event = eventByJobId.get(job.job_id) ?? {
        event_id: `task-event-${job.job_id}`,
        chat_id: sourceChatId,
        task_id: claim.task_id,
        event_type: taskEventTypeForOperation(claim.operation),
        title: typeof privatePatch.title === "string" ? privatePatch.title : null,
        status: typeof safeMetadata.status === "string" ? safeMetadata.status : null,
        created_at: typeof safeMetadata.updated_at === "number" ? safeMetadata.updated_at : Math.floor(Date.now() / 1000),
        task_update_job_id: job.job_id,
      } satisfies TaskEventFrame;
      const userMessageId = claim.message_id ?? params.fallbackUserMessageId;
      if (!userMessageId) throw new Error(`Task update job ${job.job_id} is missing a user message id.`);
      const eventMessage = await buildTaskEventSystemMessage({
        chatKey: sourceChatKey,
        userMessageId,
        event,
      });
      const confirmTaskEventPersisted = async () => {
        const confirmedPromise = params.ws.waitForMessage(
          "task_update_job_event_confirmed",
          (payload) => (payload as Record<string, unknown>).job_id === job.job_id,
          20_000,
        );
        await params.ws.sendAsync("task_update_job_event_confirmed", {
          protocol_version: 1,
          job_id: job.job_id,
          event_system_message_id: eventMessage.message_id,
        });
        await confirmedPromise;
      };

      if (claim.state === "TASK_PERSISTED") {
        await this.persistEncryptedSystemMessage(params.ws, eventMessage, sourceChatId);
        await confirmTaskEventPersisted();
        handledJobIds.add(job.job_id);
        continue;
      }
      if (!claim.lease_token || !Number.isSafeInteger(claim.lease_generation)) {
        throw new Error("Task update job claim returned an invalid lease.");
      }

      let encryptedTaskPayload: Record<string, unknown>;
      if (claim.operation === "create") {
        const input = await buildCreateUserTaskInput(masterKey, {
          title: typeof privatePatch.title === "string" ? privatePatch.title : "Untitled task",
          description: typeof privatePatch.description === "string" ? privatePatch.description : "",
          status: typeof safeMetadata.status === "string" ? safeMetadata.status as UserTaskStatus : "todo",
          assign: typeof safeMetadata.assignee_type === "string" ? safeMetadata.assignee_type : "user",
          chatId: typeof safeMetadata.primary_chat_id === "string" ? safeMetadata.primary_chat_id : claim.chat_id ?? params.activeChatId,
        });
        encryptedTaskPayload = {
          ...input,
          task_id: claim.task_id,
          position: typeof safeMetadata.position === "number" ? safeMetadata.position : input.position,
          created_at: typeof safeMetadata.created_at === "number" ? safeMetadata.created_at : input.created_at,
          updated_at: typeof safeMetadata.updated_at === "number" ? safeMetadata.updated_at : input.updated_at,
        };
      } else {
        const task = await findTaskForUpdateJob(claim);
        const patch = await buildUpdateUserTaskInput(task, masterKey, {
          title: typeof privatePatch.title === "string" ? privatePatch.title : undefined,
          description: typeof privatePatch.description === "string" ? privatePatch.description : undefined,
          status: typeof safeMetadata.status === "string" ? safeMetadata.status as UserTaskStatus : undefined,
          assign: typeof safeMetadata.assignee_type === "string" ? safeMetadata.assignee_type : undefined,
          chatId: typeof safeMetadata.primary_chat_id === "string" ? safeMetadata.primary_chat_id : undefined,
        });
        encryptedTaskPayload = {
          ...patch,
          version: claim.expected_task_version,
          updated_at: typeof safeMetadata.updated_at === "number" ? safeMetadata.updated_at : patch.updated_at,
        };
        if (typeof safeMetadata.primary_chat_id === "string") {
          encryptedTaskPayload.key_wrappers = await buildTaskKeyWrappersForChat(
            task,
            safeMetadata.primary_chat_id,
            typeof safeMetadata.updated_at === "number" ? safeMetadata.updated_at : Math.floor(Date.now() / 1000),
          );
        }
      }

      const persistedPromise = params.ws.waitForMessage(
        "task_update_job_persisted",
        (payload) => (payload as Record<string, unknown>).job_id === job.job_id,
        20_000,
      );
      await params.ws.sendAsync("task_update_job_persist", buildTaskUpdateJobPersistPayload({
        jobId: job.job_id,
        leaseToken: claim.lease_token,
        leaseGeneration: claim.lease_generation,
        expectedTaskVersion: claim.expected_task_version,
        encryptedTaskPayload,
        encryptedTaskEventMessage: eventMessage.encrypted_content,
      }));
      await persistedPromise;
      await this.persistEncryptedSystemMessage(params.ws, eventMessage, sourceChatId);
      await confirmTaskEventPersisted();
      handledJobIds.add(job.job_id);
    }

    clearSyncCache();
    return handledJobIds;
  }

  private async persistStreamedEmbeds(params: {
    ws: OpenMatesWsClient;
    embeds: SendEmbedDataFrame[];
    chatId: string;
    chatKeyBytes: Uint8Array;
    fallbackMessageId: string;
  }): Promise<void> {
    const finalized = new Map(
      params.embeds
        .filter((embed) => {
          const status = embed.status ?? "finished";
          return (
            embed.embed_id &&
            embed.content &&
            status !== "processing" &&
            status !== "error" &&
            status !== "cancelled"
          );
        })
        .map((embed) => [embed.embed_id, embed]),
    );
    if (finalized.size === 0) return;

    const session = this.requireSession();
    const masterKey = this.getMasterKeyBytes();
    const parentKeys = new Map<string, Uint8Array>();
    const processed = new Set<string>();
    const cachedEmbeds = loadSyncCache();

    const resolveCachedParentKey = async (parentId: string): Promise<Uint8Array | undefined> => {
      if (!cachedEmbeds) return undefined;
      const cachedParent = cachedEmbeds?.embeds.find(
        (entry) => String(entry.embed_id ?? entry.id ?? "") === parentId,
      );
      if (!cachedParent) return undefined;
      const hashedParentId = computeSHA256(parentId);
      return await this.resolveEmbedKey(
        cachedEmbeds,
        masterKey,
        cachedParent,
        parentId,
        hashedParentId,
      ) ?? undefined;
    };

    const persistOne = async (
      embed: SendEmbedDataFrame,
      embedKey: Uint8Array,
      isChild: boolean,
    ) => {
      const now = Math.floor(Date.now() / 1000);
      const createdAt = normalizeUnixSeconds(embed.createdAt, now);
      const updatedAt = normalizeUnixSeconds(embed.updatedAt, now);
      const messageId = embed.message_id || params.fallbackMessageId;
      const userId = embed.user_id || session.hashedEmail;
      const hashedChatId = computeSHA256(params.chatId);
      const hashedMessageId = computeSHA256(messageId);
      const hashedUserId = computeSHA256(userId);
      const hashedEmbedId = computeSHA256(embed.embed_id);
      const encryptedContent = await encryptWithAesGcmCombined(
        embed.content ?? "",
        embedKey,
      );
      const encryptedType = await encryptWithAesGcmCombined(
        embed.type || "app_skill_use",
        embedKey,
      );
      const encryptedTextPreview = embed.text_preview
        ? await encryptWithAesGcmCombined(embed.text_preview, embedKey)
        : undefined;
      const keys: EmbedKeyWrapper[] = !isChild
        ? [
            {
              hashed_embed_id: hashedEmbedId,
              key_type: "master",
              hashed_chat_id: null,
              encrypted_embed_key: await encryptBytesWithAesGcm(embedKey, masterKey),
              hashed_user_id: hashedUserId,
              created_at: now,
            },
            {
              hashed_embed_id: hashedEmbedId,
              key_type: "chat",
              hashed_chat_id: hashedChatId,
              encrypted_embed_key: await encryptBytesWithAesGcm(
                embedKey,
                params.chatKeyBytes,
              ),
              hashed_user_id: hashedUserId,
              created_at: now,
            },
          ]
        : [];

      await params.ws.sendAsync("store_embed", {
        embed_id: embed.embed_id,
        encrypted_type: encryptedType,
        encrypted_content: encryptedContent,
        encrypted_text_preview: encryptedTextPreview,
        status: embed.status || "finished",
        hashed_chat_id: hashedChatId,
        hashed_message_id: hashedMessageId,
        hashed_task_id: embed.task_id ? computeSHA256(embed.task_id) : undefined,
        hashed_user_id: hashedUserId,
        embed_ids: embed.embed_ids,
        parent_embed_id: embed.parent_embed_id || undefined,
        version_number: embed.version_number,
        file_path: embed.file_path,
        content_hash: embed.content_hash,
        text_length_chars: embed.text_length_chars,
        is_private: embed.is_private ?? false,
        is_shared: embed.is_shared ?? false,
        created_at: createdAt,
        updated_at: updatedAt,
      });

      if (keys.length > 0) {
        await params.ws.sendAsync("store_embed_keys", { keys });
        parentKeys.set(embed.embed_id, embedKey);
      }

      if (Array.isArray(embed.version_history_rows)) {
        for (const row of embed.version_history_rows) {
          if (!row.embed_id || typeof row.version_number !== "number") continue;
          const encryptedSnapshot =
            typeof row.snapshot === "string"
              ? await encryptWithAesGcmCombined(row.snapshot, embedKey)
              : undefined;
          const encryptedPatch =
            typeof row.patch === "string"
              ? await encryptWithAesGcmCombined(row.patch, embedKey)
              : undefined;
          if (!encryptedSnapshot && !encryptedPatch) continue;
          await params.ws.sendAsync("store_embed_diff", {
            embed_id: row.embed_id,
            version_number: row.version_number,
            encrypted_snapshot: encryptedSnapshot ?? null,
            encrypted_patch: encryptedPatch ?? null,
            hashed_user_id: hashedUserId,
            created_at: normalizeUnixSeconds(row.created_at, now),
          });
        }
      }
    };

    let madeProgress = true;
    while (processed.size < finalized.size && madeProgress) {
      madeProgress = false;
      for (const embed of finalized.values()) {
        if (processed.has(embed.embed_id)) continue;
        const parentId = embed.parent_embed_id || null;
        if (parentId && finalized.has(parentId) && !parentKeys.has(parentId)) {
          continue;
        }

        const parentKey = parentId
          ? parentKeys.get(parentId) ?? await resolveCachedParentKey(parentId)
          : undefined;
        if (parentId && !parentKey) continue;
        const embedKey = parentKey ?? await deriveEmbedKeyFromChatKey(params.chatKeyBytes, embed.embed_id);
        await persistOne(embed, embedKey, Boolean(parentId));
        processed.add(embed.embed_id);
        madeProgress = true;
      }
    }

    for (const embed of finalized.values()) {
      if (processed.has(embed.embed_id)) continue;
      const parentId = embed.parent_embed_id || null;
      const parentKey = parentId
        ? parentKeys.get(parentId) ?? await resolveCachedParentKey(parentId)
        : undefined;
      if (parentId && !parentKey) {
        throw new Error(`Cannot persist child embed ${embed.embed_id}: parent embed key ${parentId} is unavailable.`);
      }
      const embedKey = parentKey ?? await deriveEmbedKeyFromChatKey(params.chatKeyBytes, embed.embed_id);
      await persistOne(embed, embedKey, Boolean(parentId));
      processed.add(embed.embed_id);
    }
  }

  private async persistPostProcessingMetadata(params: {
    ws: OpenMatesWsClient;
    chatId: string;
    chatKeyBytes: Uint8Array;
    followUpSuggestions: string[];
    newChatSuggestions: string[];
    encryptedChatKey: string | null;
  }): Promise<void> {
    const encryptedFollowUps = params.followUpSuggestions.length > 0
      ? await encryptWithAesGcmCombined(
          JSON.stringify(params.followUpSuggestions.slice(0, 18)),
          params.chatKeyBytes,
        )
      : "";
    const masterKey = this.getMasterKeyBytes();
    const encryptedNewChatSuggestions = await Promise.all(
      params.newChatSuggestions.slice(0, 6).map((suggestion) =>
        encryptWithAesGcmCombined(suggestion, masterKey),
      ),
    );

    if (!encryptedFollowUps && encryptedNewChatSuggestions.length === 0) return;

    await params.ws.sendAsync("update_post_processing_metadata", {
      chat_id: params.chatId,
      encrypted_follow_up_suggestions: encryptedFollowUps,
      encrypted_new_chat_suggestions: encryptedNewChatSuggestions,
      encrypted_chat_key: params.encryptedChatKey ?? "",
    });
    await params.ws.waitForMessage(
      "post_processing_metadata_stored",
      (payload) => {
        const p = payload as Record<string, unknown>;
        return p.chat_id === params.chatId;
      },
      20_000,
    );
  }

  /**
   * Delete a chat by ID.
   *
   * Mirrors the web app's sendDeleteChatImpl in chatSyncServiceSenders.ts.
   * Sends a delete_chat WebSocket message and waits for the server ack.
   */
  async deleteChat(chatIdInput: string): Promise<void> {
    // Resolve short IDs (8-char prefix) to full UUIDs via sync cache.
    let chatId: string;
    if (chatIdInput.length < 36) {
      const resolved = await this.resolveFullChatId(chatIdInput);
      if (!resolved) {
        throw new Error(
          `Chat not found for '${chatIdInput}'. Use a full UUID or the first 8 characters of an existing chat ID.`,
        );
      }
      chatId = resolved;
    } else {
      chatId = chatIdInput;
    }

    const { ws } = await this.openWsClient();

    try {
      ws.send("delete_chat", { chatId: chatId });
      // Wait for the server to acknowledge the deletion.
      // The server broadcasts a chat_deleted event to all connected devices.
      await ws.waitForMessage(
        "chat_deleted",
        (payload) => {
          const p = payload as Record<string, unknown>;
          return p.chat_id === chatId || p.chatId === chatId;
        },
        15_000,
      );
    } finally {
      ws.close();
    }
  }

  // -------------------------------------------------------------------------
  // Apps
  // -------------------------------------------------------------------------

  async listApps(apiKey?: string): Promise<unknown> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    // include_unavailable=true: show all production-stage skills regardless
    // of provider API key availability — matches web app's static metadata.
    const response = await this.http.get(
      "/v1/apps?include_unavailable=true",
      headers,
    );
    if (!response.ok) {
      throw new Error(
        `Failed to list apps (HTTP ${response.status}). ` +
          (apiKey
            ? "Ensure API key has app scope."
            : "Ensure you are logged in (run `openmates login`)."),
      );
    }
    return response.data;
  }

  private async resolveAsyncSkillResponse(
    responseData: unknown,
    headers: Record<string, string>,
  ): Promise<unknown> {
    const envelope = responseData as Record<string, unknown>;
    const data = (envelope?.data ?? envelope) as Record<string, unknown>;
    const taskId = typeof data?.task_id === "string" ? data.task_id : null;
    const taskIds = Array.isArray(data?.task_ids)
      ? (data.task_ids as unknown[]).filter((id): id is string => typeof id === "string")
      : [];

    if (taskId) {
      const result = await this.pollTaskUntilComplete(taskId, headers);
      return this.wrapResolvedSkillResult(responseData, result.result);
    }

    if (taskIds.length > 0) {
      const taskResults = await Promise.all(
        taskIds.map((id) => this.pollTaskUntilComplete(id, headers)),
      );
      return this.wrapResolvedSkillResult(
        responseData,
        this.mergeTaskResults(taskResults.map((task) => task.result)),
      );
    }

    return responseData;
  }

  private async pollTaskUntilComplete(
    taskId: string,
    headers: Record<string, string>,
  ): Promise<TaskStatusResponse> {
    const started = Date.now();
    let lastTransientError: string | null = null;
    while (Date.now() - started < SKILL_TASK_POLL_TIMEOUT_MS) {
      let response;
      try {
        response = await this.http.get<TaskStatusResponse>(
          `/v1/tasks/${encodeURIComponent(taskId)}`,
          headers,
        );
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
        throw new Error(`Task polling failed with HTTP ${response.status}`);
      }
      lastTransientError = null;
      if (response.data.status === "completed") {
        return response.data;
      }
      if (response.data.status === "failed") {
        throw new Error(response.data.error ?? "Task failed");
      }
      await new Promise((resolve) => setTimeout(resolve, SKILL_TASK_POLL_INTERVAL_MS));
    }
    if (lastTransientError) {
      throw new Error(
        `Task ${taskId} did not complete within ${SKILL_TASK_POLL_TIMEOUT_MS / 1000}s; last polling error: ${lastTransientError}`,
      );
    }
    throw new Error(`Task ${taskId} did not complete within ${SKILL_TASK_POLL_TIMEOUT_MS / 1000}s`);
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
    if (groupedResults.length === 0) {
      return { results };
    }
    const first = resultObjects[0] ?? {};
    return {
      ...first,
      results: groupedResults,
      items: resultObjects.flatMap((result) =>
        Array.isArray(result.items) ? (result.items as unknown[]) : [],
      ),
      result_count: groupedResults.length,
      post_count: resultObjects.reduce(
        (count, result) => count + (typeof result.post_count === "number" ? result.post_count : 0),
        0,
      ),
      request_count: resultObjects.reduce(
        (count, result) => count + (typeof result.request_count === "number" ? result.request_count : 0),
        0,
      ),
    };
  }

  async getApp(appId: string): Promise<unknown> {
    // Public metadata endpoint with include_unavailable to show all skills
    const response = await this.http.get(
      `/v1/apps/${encodeURIComponent(appId)}/metadata?include_unavailable=true`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`App '${appId}' not found (HTTP ${response.status})`);
    }
    return response.data;
  }

  async getSkillInfo(
    appId: string,
    skillId: string,
    apiKey?: string,
  ): Promise<unknown> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.get(
      `/v1/apps/${encodeURIComponent(appId)}/skills/${encodeURIComponent(skillId)}`,
      headers,
    );
    if (!response.ok) {
      throw new Error(
        `Skill '${appId}/${skillId}' not found (HTTP ${response.status})`,
      );
    }
    return response.data;
  }

  /** A single parameter entry from the skill schema. */
  // Exported via index.ts for external consumers.
  async getSkillSchema(appId: string, skillId: string): Promise<SkillParam[]> {
    const response = await this.http.get(
      "/openapi.json",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) return [];

    const spec = response.data as {
      paths?: Record<
        string,
        Record<
          string,
          {
            requestBody?: {
              content?: {
                "application/json"?: { schema?: Record<string, unknown> };
              };
            };
          }
        >
      >;
      components?: { schemas?: Record<string, Record<string, unknown>> };
    };

    const paths = spec.paths ?? {};
    const schemas = spec.components?.schemas ?? {};
    const postPath = paths[`/v1/apps/${appId}/skills/${skillId}`]?.post;
    if (!postPath) return [];

    // Resolve the request body schema
    const bodySchema =
      postPath.requestBody?.content?.["application/json"]?.schema;
    if (!bodySchema) return [];

    // Recursively resolve $ref to a schema object
    const resolveRef = (ref: string): Record<string, unknown> | null => {
      const name = ref.replace("#/components/schemas/", "");
      return (schemas[name] as Record<string, unknown>) ?? null;
    };

    const resolveSchema = (
      s: Record<string, unknown>,
    ): Record<string, unknown> => {
      if (typeof s.$ref === "string") {
        return resolveRef(s.$ref) ?? s;
      }
      return s;
    };

    const topSchema =
      typeof bodySchema.$ref === "string"
        ? resolveRef(bodySchema.$ref)
        : (bodySchema as Record<string, unknown>);
    if (!topSchema) return [];

    // Most app skills use a top-level "requests" array. Some older skills use
    // a flat object schema directly, so fall back to the top-level properties.
    const requestsProp = (
      topSchema.properties as
        | Record<string, Record<string, unknown>>
        | undefined
    )?.requests;
    const itemsRef = requestsProp?.items as Record<string, unknown> | undefined;
    const itemSchema = itemsRef ? resolveSchema(itemsRef) : topSchema;
    const inputShape: "requests" | "flat" = itemsRef ? "requests" : "flat";

    if (!itemSchema?.properties) return [];

    const required = new Set(
      Array.isArray(itemSchema.required)
        ? (itemSchema.required as string[])
        : [],
    );
    const props = itemSchema.properties as Record<
      string,
      Record<string, unknown>
    >;

    return Object.entries(props).map(([name, p]) => {
      const resolved = resolveSchema(p);
      let typeStr = (resolved.type as string | undefined) ?? "string";

      // For array types, try to describe the item structure from the description
      // since the OpenAPI spec often uses items:{} (freeform) for nested objects.
      let itemTypeStr: string | undefined;
      if (typeStr === "array") {
        const items = resolved.items as Record<string, unknown> | undefined;
        if (items && typeof items.$ref === "string") {
          const itemResolved = resolveRef(items.$ref as string);
          if (itemResolved?.properties) {
            const itemProps = Object.keys(
              itemResolved.properties as Record<string, unknown>,
            );
            itemTypeStr = `{${itemProps.join(", ")}}`;
          }
        }
        typeStr = itemTypeStr ? `array of ${itemTypeStr}` : "array";
      }

      // For anyOf/oneOf, build a union type string
      if (resolved.anyOf || resolved.oneOf) {
        const variants = (resolved.anyOf ?? resolved.oneOf) as Array<
          Record<string, unknown>
        >;
        const types = variants
          .map((v) => (v.type as string | undefined) ?? "")
          .filter(Boolean)
          .filter((t) => t !== "null");
        if (types.length > 0) typeStr = types.join(" | ");
      }

      return {
        name,
        type: typeStr,
        description: (resolved.description as string | undefined) ?? "",
        required: required.has(name),
        default: resolved.default,
        inputShape,
      };
    });
  }

  async runSkill(params: {
    app: string;
    skill: string;
    inputData: Record<string, unknown>;
    apiKey?: string;
  }): Promise<unknown> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (params.apiKey) headers.Authorization = `Bearer ${params.apiKey}`;
    // The dynamic skill endpoints expect the tool_schema structure directly
    // as the request body (e.g. {"requests": [...]}), not wrapped in input_data.
    const response = await this.http.post(
      `/v1/apps/${params.app}/skills/${params.skill}`,
      params.inputData,
      headers,
    );
    if (!response.ok) {
      const body = response.data as Record<string, unknown> | undefined;
      const detail =
        typeof body?.detail === "string"
          ? body.detail
          : Array.isArray(body?.detail)
            ? (body.detail as Array<{ msg?: string }>)
                .map((d) => d.msg ?? JSON.stringify(d))
                .join("; ")
            : undefined;
      const err = new Error(
        detail
          ? `Skill execution failed: ${detail}`
          : `Skill execution failed with HTTP ${response.status}`,
      );
      (err as Error & { statusCode: number }).statusCode = response.status;
      throw err;
    }
    return this.resolveAsyncSkillResponse(response.data, headers);
  }

  async getCodeRunStreamAuth(): Promise<{ sessionId: string; token: string; fallbackToken?: string } | null> {
    const session = this.session;
    if (!session) return null;
    await this.refreshWsToken();
    const token = session.wsToken || session.cookies.auth_refresh_token;
    if (!token) return null;
    const fallbackToken = session.cookies.auth_refresh_token;
    return { sessionId: session.sessionId, token, fallbackToken };
  }

  async getCodeRunStatus(path: string, apiKey?: string): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.get<Record<string, unknown>>(path, headers);
    if (!response.ok) {
      throw new Error(`Code Run status request failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  // -------------------------------------------------------------------------
  // Travel: booking link resolution
  // -------------------------------------------------------------------------

  /**
   * Look up a booking URL for a flight using its booking_token.
   *
   * Calls POST /v1/apps/travel/booking-link which resolves the SerpAPI
   * booking_token to a direct airline/OTA booking URL. Costs 25 credits.
   *
   * @see TravelConnectionEmbedFullscreen.svelte — handleLoadBookingLink()
   */
  async getBookingLink(params: {
    bookingToken: string;
    bookingContext?: Record<string, string>;
    apiKey?: string;
  }): Promise<{
    success: boolean;
    booking_url?: string;
    booking_provider?: string;
    credits_charged?: number;
    error?: string;
  }> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (params.apiKey) headers.Authorization = `Bearer ${params.apiKey}`;
    const response = await this.http.post(
      "/v1/apps/travel/booking-link",
      {
        booking_token: params.bookingToken,
        booking_context: params.bookingContext ?? null,
        hashed_chat_id: null,
      },
      headers,
    );
    if (!response.ok) {
      throw new Error(
        `Booking link request failed with HTTP ${response.status}`,
      );
    }
    return response.data as {
      success: boolean;
      booking_url?: string;
      booking_provider?: string;
      credits_charged?: number;
      error?: string;
    };
  }

  // -------------------------------------------------------------------------
  // Workflows
  // -------------------------------------------------------------------------

  async listWorkflows(): Promise<WorkflowSummary[]> {
    this.requireSession();
    const response = await this.http.get<{ workflows?: WorkflowSummary[] }>(
      "/v1/workflows",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow list failed with HTTP ${response.status}`);
    }
    return response.data.workflows ?? [];
  }

  async listTemporaryWorkflows(): Promise<WorkflowSummary[]> {
    this.requireSession();
    const response = await this.http.get<{ workflows?: WorkflowSummary[] }>(
      "/v1/workflows/temporary",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Temporary workflow list failed with HTTP ${response.status}`);
    }
    return response.data.workflows ?? [];
  }

  async createWorkflow(params: {
    title: string;
    graph: WorkflowGraph;
    enabled?: boolean;
    runContentRetention?: WorkflowRunContentRetention;
    lifecycle?: WorkflowLifecycle;
    source?: string;
    sourceChatId?: string | null;
    createdByAssistant?: boolean;
    autoDeleteAt?: number | null;
  }): Promise<WorkflowDetail> {
    this.requireSession();
    const response = await this.http.post<{ workflow?: WorkflowDetail }>(
      "/v1/workflows",
      {
        title: params.title,
        graph: params.graph,
        enabled: params.enabled ?? false,
        ...(params.runContentRetention ? { run_content_retention: params.runContentRetention } : {}),
        ...(params.lifecycle ? { lifecycle: params.lifecycle } : {}),
        ...(params.source ? { source: params.source } : {}),
        ...(params.sourceChatId !== undefined ? { source_chat_id: params.sourceChatId } : {}),
        ...(params.createdByAssistant !== undefined ? { created_by_assistant: params.createdByAssistant } : {}),
        ...(params.autoDeleteAt !== undefined ? { auto_delete_at: params.autoDeleteAt } : {}),
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow create failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  async validateWorkflowYaml(source: string): Promise<{
    draft_valid: boolean;
    enable_ready: boolean;
    diagnostics: Array<Record<string, unknown>>;
  }> {
    this.requireSession();
    const response = await this.http.post<{ validation?: {
      draft_valid: boolean;
      enable_ready: boolean;
      diagnostics: Array<Record<string, unknown>>;
    } }>("/v1/workflows/validate", { source }, this.getCliRequestHeaders());
    if (!response.ok || !response.data.validation) {
      throw new Error(`Workflow YAML validation failed with HTTP ${response.status}`);
    }
    return response.data.validation;
  }

  async createWorkflowYaml(source: string): Promise<{
    workflow: WorkflowDetail;
    validation: { draft_valid: boolean; enable_ready: boolean; diagnostics: Array<Record<string, unknown>> };
  }> {
    this.requireSession();
    const response = await this.http.post<{
      workflow?: WorkflowDetail;
      validation?: { draft_valid: boolean; enable_ready: boolean; diagnostics: Array<Record<string, unknown>> };
    }>("/v1/workflows/yaml", { source }, this.getCliRequestHeaders());
    if (!response.ok || !response.data.workflow || !response.data.validation) {
      throw new Error(`Workflow YAML create failed with HTTP ${response.status}`);
    }
    return { workflow: response.data.workflow, validation: response.data.validation };
  }

  async updateWorkflowYaml(workflowId: string, source: string): Promise<{
    workflow: WorkflowDetail;
    validation: { draft_valid: boolean; enable_ready: boolean; diagnostics: Array<Record<string, unknown>> };
  }> {
    this.requireSession();
    const createLike = await this.http.post<{
      workflow?: WorkflowDetail;
      validation?: { draft_valid: boolean; enable_ready: boolean; diagnostics: Array<Record<string, unknown>> };
    }>(`/v1/workflows/${encodeURIComponent(workflowId)}/yaml`, { source }, this.getCliRequestHeaders());
    if (!createLike.ok || !createLike.data.workflow || !createLike.data.validation) {
      throw new Error(`Workflow YAML update failed with HTTP ${createLike.status}`);
    }
    return { workflow: createLike.data.workflow, validation: createLike.data.validation };
  }

  async getWorkflow(workflowId: string): Promise<WorkflowDetail> {
    this.requireSession();
    const response = await this.http.get<{ workflow?: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow get failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  async updateWorkflow(
    workflowId: string,
    params: { title?: string; graph?: WorkflowGraph; enabled?: boolean; runContentRetention?: WorkflowRunContentRetention },
  ): Promise<WorkflowDetail> {
    this.requireSession();
    const payload = {
      ...params,
      ...(params.runContentRetention ? { run_content_retention: params.runContentRetention } : {}),
    };
    delete payload.runContentRetention;
    const response = await this.http.patch<{ workflow?: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}`,
      payload,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow update failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  async deleteWorkflow(workflowId: string): Promise<{ deleted: boolean }> {
    this.requireSession();
    const response = await this.http.delete<{ deleted?: boolean }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}`,
      undefined,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow delete failed with HTTP ${response.status}`);
    }
    return { deleted: response.data.deleted === true };
  }

  async keepWorkflow(workflowId: string): Promise<WorkflowDetail> {
    this.requireSession();
    const response = await this.http.post<{ workflow?: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/keep`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow keep failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  async enableWorkflow(workflowId: string): Promise<WorkflowDetail> {
    return this.setWorkflowEnabled(workflowId, true);
  }

  async disableWorkflow(workflowId: string): Promise<WorkflowDetail> {
    return this.setWorkflowEnabled(workflowId, false);
  }

  async runWorkflow(
    workflowId: string,
    params: { idempotencyKey: string; mode?: "manual" | "test"; input?: Record<string, unknown> },
  ): Promise<WorkflowRunDetail> {
    this.requireSession();
    if (!params.idempotencyKey.trim()) {
      throw new Error("Workflow run requires a stable idempotencyKey");
    }
    const response = await this.http.post<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/run`,
      { mode: params.mode ?? "manual", input: params.input ?? {} },
      { ...this.getCliRequestHeaders(), "Idempotency-Key": params.idempotencyKey },
    );
    if (!response.ok || !response.data.run) {
      throw new Error(`Workflow run failed with HTTP ${response.status}`);
    }
    return response.data.run;
  }

  async listWorkflowRuns(workflowId: string): Promise<WorkflowRunDetail[]> {
    this.requireSession();
    const response = await this.http.get<{ runs?: WorkflowRunDetail[] }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow runs list failed with HTTP ${response.status}`);
    }
    return response.data.runs ?? [];
  }

  async getWorkflowRun(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    this.requireSession();
    const response = await this.http.get<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.run) {
      throw new Error(`Workflow run get failed with HTTP ${response.status}`);
    }
    return response.data.run;
  }

  async cancelWorkflowRun(workflowId: string, runId: string): Promise<WorkflowRunCancellationResult> {
    this.requireSession();
    const response = await this.http.post<WorkflowRunCancellationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/cancel`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || (response.data.status !== "cancellation_requested" && response.data.status !== "cancelled")) {
      throw new Error(`Workflow run cancellation failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async testWorkflowStep(
    workflowId: string,
    stepId: string,
    params: { input?: Record<string, unknown>; confirmed?: boolean } = {},
  ): Promise<WorkflowRunDetail> {
    this.requireSession();
    const response = await this.http.post<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(stepId)}/test`,
      { input: params.input ?? {}, confirmed: params.confirmed === true },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.run) {
      throw new Error(`Workflow step test failed with HTTP ${response.status}`);
    }
    return response.data.run;
  }

  async respondToWorkflowRun(
    workflowId: string,
    runId: string,
    stepId: string,
    input: Record<string, unknown>,
  ): Promise<WorkflowRunDetail> {
    this.requireSession();
    const response = await this.http.post<{ run?: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/respond`,
      { step_id: stepId, input },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.run) {
      throw new Error(`Workflow response failed with HTTP ${response.status}`);
    }
    return response.data.run;
  }

  async listWorkflowCapabilities(): Promise<WorkflowCapability[]> {
    this.requireSession();
    const response = await this.http.get<{ capabilities?: WorkflowCapability[] }>(
      "/v1/workflows/capabilities",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow capabilities failed with HTTP ${response.status}`);
    }
    return response.data.capabilities ?? [];
  }

  async upsertWorkflowTemplateProjection(
    workflowId: string,
    params: WorkflowTemplateProjectionUpsertParams,
  ): Promise<WorkflowTemplateProjectionResult> {
    this.requireSession();
    const response = await this.http.put<WorkflowTemplateProjectionResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/template-projection`,
      {
        template_id: params.templateId,
        source_version: params.sourceVersion,
        ciphertext: params.ciphertext,
        ciphertext_checksum: params.ciphertextChecksum,
        owner_wrapped_key: params.ownerWrappedKey,
        projection_schema_version: params.projectionSchemaVersion,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow template projection upsert failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async getPublicWorkflowTemplateProjection(templateId: string): Promise<PublicWorkflowTemplateProjection> {
    const response = await this.http.get<PublicWorkflowTemplateProjection>(
      `/v1/workflows/template-projections/${encodeURIComponent(templateId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow template projection retrieval failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async revokeWorkflowTemplateProjection(workflowId: string): Promise<WorkflowTemplateProjectionRevocationResult> {
    this.requireSession();
    const response = await this.http.post<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/revoke`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow template projection revoke failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async unrevokeWorkflowTemplateProjection(workflowId: string): Promise<WorkflowTemplateProjectionRevocationResult> {
    this.requireSession();
    const response = await this.http.post<WorkflowTemplateProjectionRevocationResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/unrevoke`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow template projection unrevoke failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async completeImportedWorkflowBinding(
    workflowId: string,
    params: WorkflowTemplateBindingCompletionParams,
  ): Promise<WorkflowTemplateBindingCompletionResult> {
    this.requireSession();
    const response = await this.http.post<WorkflowTemplateBindingCompletionResult>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/binding-requirements/complete`,
      { type: params.type, node_id: params.nodeId },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow imported binding completion failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async createWorkflowTemplateShortUrl(params: WorkflowTemplateShortUrlParams): Promise<WorkflowTemplateShortUrlResult> {
    this.requireSession();
    const response = await this.http.post<WorkflowTemplateShortUrlResult>(
      "/v1/share/short-url",
      {
        token: params.token,
        encrypted_url: params.encryptedUrl,
        content_type: "workflow_template",
        content_id: params.templateId,
        password_protected: params.passwordProtected ?? false,
        ...(params.ttlSeconds !== undefined ? { ttl_seconds: params.ttlSeconds } : {}),
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow template short URL create failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async revokeShortUrl(token: string): Promise<ShortUrlRevokeResult> {
    this.requireSession();
    const response = await this.http.delete<ShortUrlRevokeResult>(
      `/v1/share/short-url/${encodeURIComponent(token)}`,
      undefined,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Short URL revoke failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async importWorkflowTemplate(payload: WorkflowTemplateImportPayload): Promise<ImportedWorkflowTemplate> {
    this.requireSession();
    const response = await this.http.post<{ workflow?: ImportedWorkflowTemplate }>(
      "/v1/workflows/template-import",
      payload,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow template import failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  async startWorkflowInput(params: WorkflowInputStartParams): Promise<WorkflowInputSessionResult> {
    this.requireSession();
    const response = await this.http.post<{ session?: WorkflowInputSessionResult }>(
      "/v1/workflows/input",
      {
        ...(params.text !== undefined ? { text: params.text } : {}),
        input_type: params.inputType ?? "text",
        ...(params.audioRef !== undefined ? { audio_ref: params.audioRef } : {}),
        ...(params.selectedWorkflowId !== undefined ? { selected_workflow_id: params.selectedWorkflowId } : {}),
        ...(params.selectedProjectId !== undefined ? { selected_project_id: params.selectedProjectId } : {}),
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.session) {
      throw new Error(`Workflow input start failed with HTTP ${response.status}`);
    }
    return response.data.session;
  }

  async getWorkflowInputSession(sessionId: string): Promise<WorkflowInputSessionDetail> {
    this.requireSession();
    const response = await this.http.get<{ session?: WorkflowInputSessionDetail }>(
      `/v1/workflows/input/${encodeURIComponent(sessionId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.session) {
      throw new Error(`Workflow input session get failed with HTTP ${response.status}`);
    }
    return response.data.session;
  }

  async listWorkflowInputEvents(sessionId: string, afterEventId = 0): Promise<WorkflowInputEvent[]> {
    this.requireSession();
    const response = await this.http.get<{ events?: WorkflowInputEvent[] }>(
      `/v1/workflows/input/${encodeURIComponent(sessionId)}/events?after_event_id=${encodeURIComponent(String(afterEventId))}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Workflow input events failed with HTTP ${response.status}`);
    }
    return response.data.events ?? [];
  }

  async followUpWorkflowInput(sessionId: string, text: string): Promise<WorkflowInputSessionResult> {
    this.requireSession();
    const response = await this.http.post<{ session?: WorkflowInputSessionResult }>(
      `/v1/workflows/input/${encodeURIComponent(sessionId)}/follow-up`,
      { text },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.session) {
      throw new Error(`Workflow input follow-up failed with HTTP ${response.status}`);
    }
    return response.data.session;
  }

  async stopWorkflowInput(sessionId: string): Promise<WorkflowInputSessionResult> {
    this.requireSession();
    const response = await this.http.post<{ session?: WorkflowInputSessionResult }>(
      `/v1/workflows/input/${encodeURIComponent(sessionId)}/stop`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.session) {
      throw new Error(`Workflow input stop failed with HTTP ${response.status}`);
    }
    return response.data.session;
  }

  async undoWorkflowInput(sessionId: string): Promise<WorkflowInputSessionResult> {
    this.requireSession();
    const response = await this.http.post<{ session?: WorkflowInputSessionResult }>(
      `/v1/workflows/input/${encodeURIComponent(sessionId)}/undo`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.session) {
      throw new Error(`Workflow input undo failed with HTTP ${response.status}`);
    }
    return response.data.session;
  }

  private async setWorkflowEnabled(workflowId: string, enabled: boolean): Promise<WorkflowDetail> {
    this.requireSession();
    const action = enabled ? "enable" : "disable";
    const response = await this.http.post<{ workflow?: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/${action}`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.workflow) {
      throw new Error(`Workflow ${action} failed with HTTP ${response.status}`);
    }
    return response.data.workflow;
  }

  // -------------------------------------------------------------------------
  // Project sources
  // -------------------------------------------------------------------------

  async listProjectSources(projectId: string): Promise<ProjectSourceRecord[]> {
    this.requireSession();
    const response = await this.http.get<{ sources?: ProjectSourceRecord[] }>(
      `/v1/projects/${encodeURIComponent(projectId)}/sources`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Project source list failed with HTTP ${response.status}`);
    }
    return response.data.sources ?? [];
  }

  async createProjectSource(projectId: string, input: ProjectSourceCreateInput): Promise<ProjectSourceRecord> {
    this.requireSession();
    const response = await this.http.post<{ source?: ProjectSourceRecord }>(
      `/v1/projects/${encodeURIComponent(projectId)}/sources`,
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.source) {
      throw new Error(`Project source create failed with HTTP ${response.status}`);
    }
    return response.data.source;
  }

  // -------------------------------------------------------------------------
  // User tasks
  // -------------------------------------------------------------------------

  async listUserTasks(filters: { status?: UserTaskStatus; chatId?: string; projectId?: string; limit?: number } = {}): Promise<UserTaskRecord[]> {
    this.requireSession();
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.chatId) params.set("chat_id", filters.chatId);
    if (filters.projectId) params.set("project_id", filters.projectId);
    const limit = filters.limit;
    if (Number.isSafeInteger(limit) && limit !== undefined && limit > 0) params.set("limit", String(limit));
    const query = params.toString();
    const response = await this.http.get<{ tasks?: UserTaskRecord[] }>(
      `/v1/user-tasks${query ? `?${query}` : ""}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`User task list failed with HTTP ${response.status}`);
    }
    return response.data.tasks ?? [];
  }

  async createUserTask(input: UserTaskCreateInput): Promise<UserTaskRecord> {
    this.requireSession();
    const response = await this.http.post<{ task?: UserTaskRecord }>(
      "/v1/user-tasks",
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.task) {
      throw new Error(`User task create failed with HTTP ${response.status}`);
    }
    return response.data.task;
  }

  async extractUserTaskProposals(input: {
    correctedText: string;
    mode?: "create" | "update";
    contextChatId?: string | null;
    projectIds?: string[];
  }): Promise<UserTaskProposalRecord[]> {
    const response = await this.http.post<{ proposed_tasks?: UserTaskProposalRecord[] }>(
      "/v1/user-tasks/extract",
      {
        corrected_text: input.correctedText,
        mode: input.mode ?? "create",
        context_chat_id: input.contextChatId ?? null,
        project_ids: input.projectIds ?? [],
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !Array.isArray(response.data.proposed_tasks)) {
      throw new Error(`Failed to extract task proposals (HTTP ${response.status})`);
    }
    return response.data.proposed_tasks;
  }

  async updateUserTask(taskId: string, input: UserTaskUpdateInput): Promise<UserTaskRecord> {
    this.requireSession();
    const response = await this.http.patch<{ task?: UserTaskRecord }>(
      `/v1/user-tasks/${encodeURIComponent(taskId)}`,
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.task) {
      throw new Error(`User task update failed with HTTP ${response.status}`);
    }
    return response.data.task;
  }

  async startUserTaskWithAI(taskId: string, input: UserTaskStartAIInput): Promise<UserTaskRecord> {
    this.requireSession();
    const response = await this.http.post<{ task?: UserTaskRecord }>(
      `/v1/user-tasks/${encodeURIComponent(taskId)}/start-ai`,
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.task) {
      throw new Error(`User task AI start failed with HTTP ${response.status}`);
    }
    return response.data.task;
  }

  async deleteUserTask(taskId: string, version: number): Promise<{ deleted?: boolean; task_id?: string }> {
    this.requireSession();
    const response = await this.http.delete<{ deleted?: boolean; task_id?: string }>(
      `/v1/user-tasks/${encodeURIComponent(taskId)}?version=${encodeURIComponent(String(version))}`,
      undefined,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`User task delete failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async completeUserTask(taskId: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    return this.postUserTaskAction(taskId, "complete", input);
  }

  async blockUserTask(taskId: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    return this.postUserTaskAction(taskId, "block", input);
  }

  async unblockUserTask(taskId: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    return this.postUserTaskAction(taskId, "unblock", input);
  }

  async skipUserTask(taskId: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    return this.postUserTaskAction(taskId, "skip", input);
  }

  async reorderUserTasks(input: UserTaskReorderInput): Promise<UserTaskRecord[]> {
    this.requireSession();
    const response = await this.http.post<{ tasks?: UserTaskRecord[] }>(
      "/v1/user-tasks/reorder",
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`User task reorder failed with HTTP ${response.status}`);
    }
    return response.data.tasks ?? [];
  }

  async postUserTaskAction(taskId: string, action: string, input: UserTaskActionInput): Promise<UserTaskRecord> {
    this.requireSession();
    const response = await this.http.post<{ task?: UserTaskRecord }>(
      `/v1/user-tasks/${encodeURIComponent(taskId)}/${encodeURIComponent(action)}`,
      input,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.task) {
      throw new Error(`User task ${action} failed with HTTP ${response.status}`);
    }
    return response.data.task;
  }

  // -------------------------------------------------------------------------
  // User plans
  // -------------------------------------------------------------------------

  async listUserPlans(filters: { status?: UserPlanStatus; chatId?: string; projectId?: string; activeOnly?: boolean } = {}): Promise<UserPlanRecord[]> {
    this.requireSession();
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.chatId) params.set("chat_id", filters.chatId);
    if (filters.projectId) params.set("project_id", filters.projectId);
    if (filters.activeOnly !== undefined) params.set("active_only", String(filters.activeOnly));
    const query = params.toString();
    const response = await this.http.get<{ plans?: UserPlanRecord[] }>(
      `/v1/user-plans${query ? `?${query}` : ""}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`User plan list failed with HTTP ${response.status}`);
    }
    return response.data.plans ?? [];
  }

  async createUserPlan(input: UserPlanCreateInput): Promise<UserPlanRecord> {
    this.requireSession();
    const response = await this.http.post<{ plan?: UserPlanRecord }>("/v1/user-plans", input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.plan) {
      throw new Error(`User plan create failed with HTTP ${response.status}`);
    }
    return response.data.plan;
  }

  async updateUserPlan(planId: string, input: UserPlanUpdateInput): Promise<UserPlanRecord> {
    this.requireSession();
    const response = await this.http.patch<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.plan) {
      throw new Error(`User plan update failed with HTTP ${response.status}`);
    }
    return response.data.plan;
  }

  async activateUserPlan(planId: string, input: Record<string, unknown> = {}): Promise<UserPlanRecord> {
    this.requireSession();
    const response = await this.http.post<{ plan?: UserPlanRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/activate`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.plan) {
      throw new Error(`User plan activate failed with HTTP ${response.status}`);
    }
    return response.data.plan;
  }

  async completeUserPlan(planId: string, input: Record<string, unknown> = {}): Promise<UserPlanRecord> {
    this.requireSession();
    const response = await this.http.post<{ plan?: UserPlanRecord; blocked_by?: unknown[] }>(`/v1/user-plans/${encodeURIComponent(planId)}/complete`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.plan) {
      throw new Error(`User plan complete failed with HTTP ${response.status}`);
    }
    return response.data.plan;
  }

  async createPlanCriterion(planId: string, input: UserPlanCriterionRecord): Promise<UserPlanCriterionRecord> {
    this.requireSession();
    const response = await this.http.post<{ criterion?: UserPlanCriterionRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/criteria`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.criterion) {
      throw new Error(`User plan criterion create failed with HTTP ${response.status}`);
    }
    return response.data.criterion;
  }

  async createPlanVerification(planId: string, input: UserPlanVerificationRecord & Record<string, unknown>): Promise<UserPlanVerificationRecord> {
    this.requireSession();
    const response = await this.http.post<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/verification`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.verification) {
      throw new Error(`User plan verification create failed with HTTP ${response.status}`);
    }
    return response.data.verification;
  }

  async addPlanVerificationEvidence(planId: string, verificationId: string, input: Partial<UserPlanVerificationRecord>): Promise<UserPlanVerificationRecord> {
    this.requireSession();
    const response = await this.http.post<{ verification?: UserPlanVerificationRecord }>(`/v1/user-plans/${encodeURIComponent(planId)}/verification/${encodeURIComponent(verificationId)}/evidence`, input, this.getCliRequestHeaders());
    if (!response.ok || !response.data.verification) {
      throw new Error(`User plan verification evidence failed with HTTP ${response.status}`);
    }
    return response.data.verification;
  }

  // -------------------------------------------------------------------------
  // Settings (generic passthrough)
  // -------------------------------------------------------------------------

  async settingsGet(path: string, apiKey?: string): Promise<unknown> {
    if (!apiKey) this.requireSession();
    const normalizedPath = this.normalizePath(path);
    const headers = this.getCliRequestHeaders();
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    let response = await this.http.get(
      normalizedPath,
      headers,
    );
    if (response.status === 429) {
      process.stderr.write(
        `Rate limited by settings API; retrying in ${Math.ceil(SETTINGS_GET_RATE_LIMIT_RETRY_MS / 1000)}s...\n`,
      );
      await new Promise((resolve) => setTimeout(resolve, SETTINGS_GET_RATE_LIMIT_RETRY_MS));
      response = await this.http.get(normalizedPath, headers);
    }
    if (!response.ok) {
      throw new Error(`Settings GET failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async createApiKey(options: ApiKeyCreateOptions): Promise<CreatedApiKeyResult> {
    const session = this.requireSession();
    const name = options.name.trim();
    if (!name) throw new Error("API key name is required");
    const material = await createApiKeyCryptoMaterial(name, session.masterKeyExportedB64);
    const response = await this.http.post(
      "/v1/settings/api-keys",
      {
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
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      const detail = (response.data as { detail?: string; message?: string } | undefined)?.detail
        ?? (response.data as { message?: string } | undefined)?.message;
      throw new Error(detail ?? `API key creation failed with HTTP ${response.status}`);
    }
    return {
      api_key: material.apiKey,
      key: response.data,
      crypto: material,
    };
  }

  async settingsPost(
    path: string,
    body: Record<string, unknown>,
    apiKey?: string,
  ): Promise<unknown> {
    if (!apiKey) this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const headers = this.getCliRequestHeaders();
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.post(
      normalizedPath,
      body,
      headers,
    );
    if (!response.ok) {
      throw new Error(`Settings POST failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async settingsDelete(path: string, body?: Record<string, unknown>, apiKey?: string): Promise<unknown> {
    if (!apiKey) this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const headers = this.getCliRequestHeaders();
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.delete(
      normalizedPath,
      body,
      headers,
    );
    if (!response.ok) {
      throw new Error(`Settings DELETE failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async settingsPatch(
    path: string,
    body: Record<string, unknown>,
    apiKey?: string,
  ): Promise<unknown> {
    if (!apiKey) this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const headers = this.getCliRequestHeaders();
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.patch(
      normalizedPath,
      body,
      headers,
    );
    if (!response.ok) {
      throw new Error(`Settings PATCH failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  // -------------------------------------------------------------------------
  // Gift cards (under /v1/payments, not /v1/settings)
  // -------------------------------------------------------------------------

  async redeemGiftCard(code: string): Promise<{
    success: boolean;
    credits_added: number;
    current_credits: number;
    message: string;
  }> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post(
      "/v1/payments/redeem-gift-card",
      { code, email_encryption_key: emailEncryptionKey },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Gift card redemption failed (HTTP ${response.status})`);
    }
    return response.data as {
      success: boolean;
      credits_added: number;
      current_credits: number;
      message: string;
    };
  }

  async listRedeemedGiftCards(): Promise<unknown> {
    this.requireSession();
    const response = await this.http.get(
      "/v1/payments/redeemed-gift-cards",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(
        `Failed to fetch redeemed gift cards (HTTP ${response.status})`,
      );
    }
    return response.data;
  }

  async listPurchasedGiftCards(): Promise<unknown> {
    this.requireSession();
    const response = await this.http.get(
      "/v1/payments/purchased-gift-cards",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(
        `Failed to fetch purchased gift cards (HTTP ${response.status})`,
      );
    }
    return response.data;
  }

  async createBankTransferOrder(creditsAmount: number): Promise<BankTransferOrderDetails> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post<BankTransferOrderDetails>(
      "/v1/payments/create-bank-transfer-order",
      {
        credits_amount: creditsAmount,
        currency: "eur",
        email_encryption_key: emailEncryptionKey,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Bank transfer order failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async createGiftCardBankTransferOrder(creditsAmount: number): Promise<BankTransferOrderDetails> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post<BankTransferOrderDetails>(
      "/v1/payments/create-gift-card-bank-transfer-order",
      {
        credits_amount: creditsAmount,
        currency: "eur",
        email_encryption_key: emailEncryptionKey,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Gift card bank transfer order failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async getBankTransferStatus(orderId: string): Promise<BankTransferStatus> {
    this.requireSession();
    const response = await this.http.get<BankTransferStatus>(
      `/v1/payments/bank-transfer-status/${encodeURIComponent(orderId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch bank transfer status (HTTP ${response.status})`);
    }
    return response.data;
  }

  async listBankTransferOrders(): Promise<BankTransferStatus[]> {
    this.requireSession();
    const response = await this.http.get<BankTransferStatus[]>(
      "/v1/payments/bank-transfer-pending",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch bank transfer orders (HTTP ${response.status})`);
    }
    return response.data;
  }

  async getGiftCardPurchaseStatus(orderId: string): Promise<GiftCardBankTransferStatus> {
    this.requireSession();
    const response = await this.http.get<GiftCardBankTransferStatus>(
      `/v1/payments/gift-card-purchase-status/${encodeURIComponent(orderId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch gift card purchase status (HTTP ${response.status})`);
    }
    return response.data;
  }

  async listInvoices(): Promise<{ invoices: InvoiceListItem[] }> {
    this.requireSession();
    const response = await this.http.get<{ invoices?: InvoiceListItem[] }>(
      "/v1/payments/invoices",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch invoices (HTTP ${response.status})`);
    }
    return { invoices: response.data.invoices ?? [] };
  }

  async downloadInvoice(invoiceId: string): Promise<DownloadedDocument> {
    return this.downloadPaymentPdf(
      `/v1/payments/invoices/${encodeURIComponent(invoiceId)}/download`,
      `Invoice_${invoiceId}.pdf`,
    );
  }

  async downloadCreditNote(invoiceId: string): Promise<DownloadedDocument> {
    return this.downloadPaymentPdf(
      `/v1/payments/invoices/${encodeURIComponent(invoiceId)}/credit-note/download`,
      `CreditNote_${invoiceId}.pdf`,
    );
  }

  async requestRefund(invoiceId: string): Promise<unknown> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post(
      "/v1/payments/refund",
      { invoice_id: invoiceId, email_encryption_key: emailEncryptionKey },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Refund request failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async getAuthMethodsStatus(): Promise<AuthMethodsStatus> {
    this.requireSession();
    const response = await this.http.get<AuthMethodsStatus>(
      "/v1/payments/user-auth-methods",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch auth methods (HTTP ${response.status})`);
    }
    return response.data;
  }

  async requestDeleteAccountEmailCode(): Promise<unknown> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post(
      "/v1/settings/request-action-verification",
      { action: "delete_account", email_encryption_key: emailEncryptionKey },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to request account deletion email code (HTTP ${response.status})`);
    }
    return response.data;
  }

  async verifyDeleteAccountEmailCode(code: string): Promise<unknown> {
    this.requireSession();
    const response = await this.http.post(
      "/v1/settings/verify-action-code",
      { action: "delete_account", code },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Account deletion email code verification failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async deleteAccountWithCliVerification(totpCode?: string): Promise<unknown> {
    const session = this.requireSession();
    const emailEncryptionKey = await this.ensureEmailEncryptionKey(session);
    const response = await this.http.post(
      "/v1/settings/delete-account",
      {
        confirm_data_deletion: true,
        auth_method: totpCode ? "2fa_otp" : "email_otp",
        auth_code: totpCode,
        email_encryption_key: emailEncryptionKey,
        require_email_verification: true,
      },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Account deletion failed (HTTP ${response.status})`);
    }
    clearSession();
    clearSyncCache();
    return response.data;
  }

  async updateUsername(username: string): Promise<unknown> {
    return this.settingsPost("user/username", { username });
  }

  async updateProfileImage(filePath: string): Promise<unknown> {
    const { uploadProfileImage } = await import("./uploadService.js");
    const result = await uploadProfileImage(filePath, this.requireSession());
    if (result.status === "rejected") {
      throw new Error(result.detail ?? "Profile image rejected by content safety checks.");
    }
    if (result.status === "account_deleted") {
      throw new Error("Account deleted due to repeated profile image policy violations.");
    }
    if (result.status !== "ok") {
      throw new Error(result.detail ?? `Profile image upload failed with status '${result.status}'.`);
    }
    return result;
  }

  async getNewsletterCategories(): Promise<unknown> {
    this.requireSession();
    const response = await this.http.get(
      "/v1/newsletter/categories",
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch newsletter categories (HTTP ${response.status})`);
    }
    return response.data;
  }

  async updateNewsletterCategories(categories: Record<string, boolean>): Promise<unknown> {
    this.requireSession();
    const response = await this.http.patch(
      "/v1/newsletter/categories",
      { categories },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to update newsletter categories (HTTP ${response.status})`);
    }
    return response.data;
  }

  async subscribeNewsletter(
    email: string,
    language = "en",
    darkmode = false,
  ): Promise<unknown> {
    const response = await this.http.post(
      "/v1/newsletter/subscribe",
      { email, language, darkmode },
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Newsletter subscribe failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async confirmNewsletter(token: string): Promise<unknown> {
    const response = await this.http.get(
      `/v1/newsletter/confirm/${encodeURIComponent(token)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Newsletter confirmation failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async unsubscribeNewsletter(token: string): Promise<unknown> {
    const response = await this.http.get(
      `/v1/newsletter/unsubscribe/${encodeURIComponent(token)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Newsletter unsubscribe failed (HTTP ${response.status})`);
    }
    return response.data;
  }

  async updateEmailNotificationSettings(payload: {
    enabled: boolean;
    email?: string | null;
    preferences: Record<string, boolean>;
    backup_reminder_interval_days?: number;
  }): Promise<unknown> {
    const { ws } = await this.openWsClient();
    try {
      const ackPromise = ws.waitForMessage("email_notification_settings_ack");
      ws.send("email_notification_settings", payload);
      const ack = await ackPromise;
      return ack.payload;
    } finally {
      ws.close();
    }
  }

  async listNotifications(limit = 50): Promise<unknown> {
    this.requireSession();
    const response = await this.http.get(
      `/v1/notifications?limit=${encodeURIComponent(String(limit))}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch notifications (HTTP ${response.status})`);
    }
    return response.data;
  }

  async *streamNotifications(): AsyncGenerator<unknown> {
    this.requireSession();
    for await (const message of this.http.streamSse(
      "/v1/notifications/stream",
      this.getCliRequestHeaders(),
    )) {
      if (message.event && message.event !== "notification") continue;
      try {
        yield JSON.parse(message.data);
      } catch {
        yield { event: message.event ?? "message", data: message.data };
      }
    }
  }

  // -------------------------------------------------------------------------
  // Daily Inspirations
  // -------------------------------------------------------------------------

  /**
   * Fetch today's daily inspirations.
   *
   * When the user is logged in, fetches their personalized (encrypted)
   * inspirations from GET /v1/daily-inspirations and decrypts each field
   * with their master key.  Falls back to the public defaults endpoint if
   * no personalized inspirations exist for the user yet.
   *
   * When not logged in, fetches the public defaults from
   * GET /v1/default-inspirations?lang=<lang> — no decryption needed.
   *
   * Mirrors: frontend/packages/ui/src/services/dailyInspirationDB.ts
   *          frontend/packages/ui/src/demo_chats/loadDefaultInspirations.ts
   */
  async getDailyInspirations(lang = "en"): Promise<DailyInspiration[]> {
    if (this.hasSession()) {
      return this._getPersonalizedInspirations(lang);
    }
    return this._getPublicInspirations(lang);
  }

  /**
   * Fetch and decrypt the authenticated user's persisted inspirations.
   * Falls back to public defaults when none are stored yet.
   */
  private async _getPersonalizedInspirations(
    lang: string,
  ): Promise<DailyInspiration[]> {
    const masterKey = this.getMasterKeyBytes();

    const response = await this.http.get<{ inspirations?: unknown[] }>(
      "/v1/daily-inspirations",
      this.getCliRequestHeaders(),
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch daily inspirations (HTTP ${response.status})`,
      );
    }

    const raw = response.data.inspirations ?? [];

    // No personalized inspirations stored yet — fall back to public defaults.
    if (raw.length === 0) {
      return this._getPublicInspirations(lang);
    }

    const results: DailyInspiration[] = [];
    for (const item of raw) {
      const r = item as Record<string, unknown>;

      // Each content field is AES-256-GCM encrypted with the master key.
      // Mirrors dailyInspirationDB.ts restoreFromServerPayload()
      const phrase =
        typeof r.encrypted_phrase === "string"
          ? ((await decryptWithAesGcmCombined(r.encrypted_phrase, masterKey)) ??
            "[encrypted]")
          : "";
      const title =
        typeof r.encrypted_title === "string"
          ? ((await decryptWithAesGcmCombined(r.encrypted_title, masterKey)) ??
            "[encrypted]")
          : "";
      const assistantResponse =
        typeof r.encrypted_assistant_response === "string"
          ? ((await decryptWithAesGcmCombined(
              r.encrypted_assistant_response,
              masterKey,
            )) ?? "[encrypted]")
          : "";
      const category =
        typeof r.encrypted_category === "string"
          ? ((await decryptWithAesGcmCombined(
              r.encrypted_category,
              masterKey,
            )) ?? "")
          : "";

      // Video metadata is stored as an encrypted JSON blob.
      let video: DailyInspirationVideo | null = null;
      if (typeof r.encrypted_video_metadata === "string") {
        const rawJson = await decryptWithAesGcmCombined(
          r.encrypted_video_metadata,
          masterKey,
        );
        if (rawJson) {
          try {
            video = JSON.parse(rawJson) as DailyInspirationVideo;
          } catch {
            // Corrupted metadata — skip video but keep inspiration
          }
        }
      }

      results.push({
        id:
          typeof r.daily_inspiration_id === "string"
            ? r.daily_inspiration_id
            : "",
        phrase,
        title,
        assistant_response: assistantResponse,
        category,
        content_type:
          typeof r.content_type === "string" ? r.content_type : "video",
        video,
        generated_at: typeof r.generated_at === "number" ? r.generated_at : 0,
        follow_up_suggestions: [],
        is_opened: r.is_opened === true,
      });
    }

    return results;
  }

  /**
   * Fetch the public (unauthenticated) default inspirations for the day.
   * These come cleartext — no decryption needed.
   * Mirrors loadDefaultInspirations.ts fetchServerDefaultInspirations()
   */
  private async _getPublicInspirations(
    lang: string,
  ): Promise<DailyInspiration[]> {
    const response = await this.http.get<{ inspirations?: unknown[] }>(
      `/v1/default-inspirations?lang=${encodeURIComponent(lang)}`,
      this.getCliRequestHeaders(),
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch public inspirations (HTTP ${response.status})`,
      );
    }

    const raw = response.data.inspirations ?? [];
    return raw.map((item) => {
      const r = item as Record<string, unknown>;
      const video = r.video as Record<string, unknown> | null | undefined;
      return {
        id: typeof r.inspiration_id === "string" ? r.inspiration_id : "",
        phrase: typeof r.phrase === "string" ? r.phrase : "",
        title: typeof r.title === "string" ? r.title : "",
        assistant_response:
          typeof r.assistant_response === "string" ? r.assistant_response : "",
        category: typeof r.category === "string" ? r.category : "",
        content_type:
          typeof r.content_type === "string" ? r.content_type : "video",
        video: video
          ? {
              youtube_id:
                typeof video.youtube_id === "string" ? video.youtube_id : "",
              title: typeof video.title === "string" ? video.title : "",
              thumbnail_url:
                typeof video.thumbnail_url === "string"
                  ? video.thumbnail_url
                  : "",
              channel_name:
                typeof video.channel_name === "string"
                  ? video.channel_name
                  : null,
              view_count:
                typeof video.view_count === "number" ? video.view_count : null,
              duration_seconds:
                typeof video.duration_seconds === "number"
                  ? video.duration_seconds
                  : null,
              published_at:
                typeof video.published_at === "string"
                  ? video.published_at
                  : null,
            }
          : null,
        generated_at: typeof r.generated_at === "number" ? r.generated_at : 0,
        follow_up_suggestions: Array.isArray(r.follow_up_suggestions)
          ? (r.follow_up_suggestions as string[])
          : [],
      };
    });
  }

  // -------------------------------------------------------------------------
  // Memories (zero-knowledge encrypted, WS create/update/delete + REST list)
  // -------------------------------------------------------------------------

  /**
   * List all memories for the current user, decrypted.
   * Fetches from the GDPR export endpoint and decrypts each entry with the master key.
   */
  async listMemories(): Promise<DecryptedMemoryEntry[]> {
    const masterKey = this.getMasterKeyBytes();
    const data = (await this.settingsGet(
      "/v1/settings/export-account-data?include_usage=false&include_invoices=false",
    )) as { data?: { app_settings_memories?: Array<Record<string, unknown>> } };
    const rawEntries = data.data?.app_settings_memories ?? [];
    const results: DecryptedMemoryEntry[] = [];

    for (const raw of rawEntries) {
      const encryptedJson =
        typeof raw.encrypted_item_json === "string"
          ? raw.encrypted_item_json
          : null;
      if (!encryptedJson) {
        continue;
      }
      const decrypted = await decryptWithAesGcmCombined(
        encryptedJson,
        masterKey,
      );
      if (!decrypted) {
        continue; // skip entries we can't decrypt (wrong key, corrupted)
      }
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(decrypted) as Record<string, unknown>;
      } catch {
        continue;
      }
      results.push({
        id: String(raw.id ?? ""),
        app_id: String(raw.app_id ?? ""),
        item_type: String(raw.item_type ?? ""),
        item_key_hash: String(raw.item_key ?? ""),
        item_version:
          typeof raw.item_version === "number" ? raw.item_version : 1,
        created_at: typeof raw.created_at === "number" ? raw.created_at : 0,
        updated_at: typeof raw.updated_at === "number" ? raw.updated_at : 0,
        data: parsed,
      });
    }
    return results;
  }

  /**
   * Create a new memory entry with schema validation.
   *
   * Encrypts the full item_value (including _original_item_key and settings_group)
   * before sending over WebSocket, matching the browser's exact payload format.
   *
   * @param appId     - App identifier (e.g. "code")
   * @param itemType  - Memory type ID (e.g. "preferred_tech")
   * @param itemValue - Field values (must satisfy the schema's required fields)
   */
  async createMemory(params: {
    appId: string;
    itemType: string;
    itemValue: Record<string, unknown>;
  }): Promise<{ success: boolean; id: string }> {
    return this.upsertMemory({ ...params, entryId: undefined, itemVersion: 1 });
  }

  /**
   * Update an existing memory entry.
   * Uses the same `store_app_settings_memories_entry` WS event with an
   * incremented version so the server's conflict-resolution logic accepts it.
   *
   * @param entryId   - UUID of the entry to update (from listMemories())
   * @param appId     - App identifier
   * @param itemType  - Memory type ID
   * @param itemValue - Updated field values (partial — merged with required fields check)
   * @param currentVersion - The entry's current item_version from listMemories()
   */
  async updateMemory(params: {
    entryId: string;
    appId: string;
    itemType: string;
    itemValue: Record<string, unknown>;
    currentVersion: number;
  }): Promise<{ success: boolean; id: string }> {
    return this.upsertMemory({
      appId: params.appId,
      itemType: params.itemType,
      itemValue: params.itemValue,
      entryId: params.entryId,
      itemVersion: params.currentVersion + 1,
    });
  }

  /**
   * Delete a memory entry. Sends `delete_app_settings_memories_entry` over
   * WebSocket. The server deletes from Directus and broadcasts to all devices.
   */
  async deleteMemory(entryId: string): Promise<{ success: boolean }> {
    const { ws } = await this.openWsClient();

    try {
      ws.send("delete_app_settings_memories_entry", { entry_id: entryId });
      await ws.waitForMessage(
        "app_settings_memories_entry_deleted",
        (payload) => {
          const p = payload as Record<string, unknown>;
          return p.entry_id === entryId && p.success === true;
        },
        15_000,
      );
    } finally {
      ws.close();
    }
    return { success: true };
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  /**
   * Validate memory item_value against the registered schema and
   * encrypt + send over WebSocket.
   */
  private async upsertMemory(params: {
    appId: string;
    itemType: string;
    itemValue: Record<string, unknown>;
    entryId?: string;
    itemVersion: number;
  }): Promise<{ success: boolean; id: string }> {
    const masterKey = this.getMasterKeyBytes();
    const registryKey = `${params.appId}/${params.itemType}`;
    const schema = MEMORY_TYPE_REGISTRY[registryKey];

    if (!schema) {
      const known = Object.keys(MEMORY_TYPE_REGISTRY)
        .map((k) => `  ${k}`)
        .join("\n");
      throw new Error(
        `Unknown memory type '${registryKey}'.\n\nAvailable types:\n${known}`,
      );
    }

    // Validate required fields
    const missing = schema.required.filter(
      (f) =>
        params.itemValue[f] === undefined ||
        params.itemValue[f] === null ||
        params.itemValue[f] === "",
    );
    if (missing.length > 0) {
      throw new Error(
        `Missing required fields for '${registryKey}': ${missing.join(", ")}\n` +
          `Required: ${schema.required.join(", ")}`,
      );
    }

    // Validate enum fields
    for (const [field, def] of Object.entries(schema.properties)) {
      const val = params.itemValue[field];
      if (val !== undefined && def.enum && !def.enum.includes(String(val))) {
        throw new Error(
          `Invalid value '${String(val)}' for field '${field}'. ` +
            `Allowed values: ${def.enum.join(", ")}`,
        );
      }
    }

    const entryId = params.entryId ?? randomUUID();
    const now = Math.floor(Date.now() / 1000);

    // Build the hashed item_key (privacy: server never sees the plaintext key)
    const hashedKey = hashItemKey(params.appId, params.itemType);

    // Build the plaintext payload — mirrors browser's appSettingsMemoriesStore exactly:
    // { ...item_value, settings_group, _original_item_key, added_date }
    const plaintextPayload: Record<string, unknown> = {
      ...params.itemValue,
      settings_group: params.appId,
      _original_item_key: params.itemType,
      added_date: now,
    };

    const encryptedItemJson = await encryptWithAesGcmCombined(
      JSON.stringify(plaintextPayload),
      masterKey,
    );

    const { ws } = await this.openWsClient();
    try {
      ws.send("store_app_settings_memories_entry", {
        entry: {
          id: entryId,
          app_id: params.appId,
          item_key: hashedKey,
          item_type: params.itemType,
          encrypted_item_json: encryptedItemJson,
          encrypted_app_key: "",
          created_at: now,
          updated_at: now,
          item_version: params.itemVersion,
        },
      });

      await ws.waitForMessage(
        "app_settings_memories_entry_stored",
        (payload) => {
          const p = payload as Record<string, unknown>;
          return p.entry_id === entryId;
        },
        15_000,
      );
    } finally {
      ws.close();
    }

    return { success: true, id: entryId };
  }

  // ── Embed encryption helpers ─────────────────────────────────────────

  /**
   * Get the master key bytes for embed encryption.
   * Requires active session.
   */
  getEmbedEncryptionKeys(): { masterKey: Uint8Array; userId: string } {
    const session = this.requireSession();
    const masterKey = base64ToBytes(session.masterKeyExportedB64);
    const userId = session.hashedEmail;
    return { masterKey, userId };
  }

  /**
   * Get the session for file upload authentication.
   */
  getSession(): import("./storage.js").OpenMatesSession {
    const session = this.requireSession();
    const currentCookies = this.http.getCookieMap();
    if (JSON.stringify(session.cookies) !== JSON.stringify(currentCookies)) {
      session.cookies = currentCookies;
      saveSession(session);
    }
    return session;
  }

  // ── Share link creation ──────────────────────────────────────────────

  /**
   * Create a shareable link for a chat.
   *
   * Mirrors: SettingsShare.svelte generateShareLink() + shareEncryption.ts generateShareKeyBlob()
   *
   * The chat key is decrypted from encrypted_chat_key in the sync cache,
   * then used to generate the encrypted blob. The chat key bytes never leave
   * the process — only the blob (which the recipient needs to access the chat)
   * is placed in the URL fragment (never sent to the server).
   *
   * @param chatId          UUID or short ID of the chat to share
   * @param durationSeconds Expiry (0 = no expiry, default)
   * @param password        Optional password protection (max 10 chars)
   * @returns Full share URL, e.g. https://openmates.org/share/chat/{id}#key={blob}
   */
  async createChatShareLink(
    chatId: string,
    durationSeconds: ShareDuration = 0,
    password?: string,
  ): Promise<string> {
    const session = this.requireSession();
    const masterKey = base64ToBytes(session.masterKeyExportedB64);

    // Ensure sync cache is fresh so we have the encrypted_chat_key
    const cache = await this.ensureSynced();

    // Resolve the chat — support short IDs and "last"
    let resolvedId = chatId;
    if (
      chatId.toLowerCase() === "__last__" ||
      chatId.toLowerCase() === "last"
    ) {
      const sorted = [...cache.chats].sort(
        (a, b) =>
          Number(b.details.updated_at ?? 0) - Number(a.details.updated_at ?? 0),
      );
      if (!sorted.length) throw new Error("No chats found.");
      resolvedId = String(sorted[0].details.id ?? "");
    } else {
      const found = cache.chats.find(
        (c) =>
          String(c.details.id ?? "").startsWith(chatId) ||
          String(c.details.id ?? "") === chatId,
      );
      if (!found)
        throw new Error(
          `Chat '${chatId}' not found. Run 'openmates chats list' first.`,
        );
      resolvedId = String(found.details.id ?? "");
    }

    // Decrypt the chat key from encrypted_chat_key
    const chat = cache.chats.find(
      (c) => String(c.details.id ?? "") === resolvedId,
    );
    if (!chat) throw new Error(`Chat '${resolvedId}' not in local cache.`);

    const encChatKey =
      typeof chat.details.encrypted_chat_key === "string"
        ? chat.details.encrypted_chat_key
        : null;
    if (!encChatKey) {
      throw new Error(
        "Chat does not have an encryption key. It may be a public/demo chat — share it directly by its URL.",
      );
    }

    const chatKeyBytes = await decryptBytesWithAesGcm(encChatKey, masterKey);
    if (!chatKeyBytes)
      throw new Error("Failed to decrypt chat key. Try logging in again.");

    const blob = await generateChatShareBlob(
      resolvedId,
      chatKeyBytes,
      durationSeconds,
      password,
    );
    const origin = deriveWebOrigin(session.apiUrl);
    return buildChatShareUrl(origin, resolvedId, blob);
  }

  /**
   * Create a shareable link for an embed.
   *
   * Mirrors: SettingsShare.svelte (embed path) + embedShareEncryption.ts generateEmbedShareKeyBlob()
   *
   * Resolves the embed's AES-256 key using the same 3-strategy key resolution
   * as resolveEmbedKey(), then generates the encrypted blob.
   *
   * @param embedIdOrShort  UUID or short prefix of the embed to share
   * @param durationSeconds Expiry (0 = no expiry, default)
   * @param password        Optional password protection (max 10 chars)
   * @returns Full share URL, e.g. https://openmates.org/share/embed/{id}#key={blob}
   */
  async createEmbedShareLink(
    embedIdOrShort: string,
    durationSeconds: ShareDuration = 0,
    password?: string,
  ): Promise<string> {
    const session = this.requireSession();
    const masterKey = base64ToBytes(session.masterKeyExportedB64);

    const cache = await this.ensureSynced();
    const { createHash } = await import("node:crypto");

    const embed = cache.embeds.find(
      (e) =>
        String(e.embed_id ?? "").startsWith(embedIdOrShort) ||
        String(e.id ?? "").startsWith(embedIdOrShort),
    );
    if (!embed) {
      throw new Error(`Embed '${embedIdOrShort}' not found in local cache.`);
    }

    const embedId = String(embed.embed_id ?? embed.id ?? "");
    const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");

    const embedKeyBytes = await this.resolveEmbedKey(
      cache,
      masterKey,
      embed as Record<string, unknown>,
      embedId,
      hashedEmbedId,
    );
    if (!embedKeyBytes) {
      throw new Error(
        "Could not resolve embed encryption key. Ensure you are logged in as the owner.",
      );
    }

    const blob = await generateEmbedShareBlob(
      embedId,
      embedKeyBytes,
      durationSeconds,
      password,
    );
    const origin = deriveWebOrigin(session.apiUrl);
    return buildEmbedShareUrl(origin, embedId, blob);
  }

  async listEmbedVersions(embedIdOrShort: string): Promise<EmbedVersionsResponse> {
    const embedId = await this.resolveEmbedId(embedIdOrShort);
    const response = await this.http.get<EmbedVersionsResponse>(
      `/v1/embeds/${encodeURIComponent(embedId)}/versions`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatEmbedVersionError(response.data, `Failed to list embed versions (HTTP ${response.status})`));
    }
    return response.data;
  }

  async startApplicationPreview(params: ApplicationPreviewStartParams): Promise<ApplicationPreviewStartResponse> {
    const embedId = await this.resolveEmbedId(params.embedId);
    const body: Record<string, unknown> = { chat_id: params.chatId };
    if (params.sharedContext) body.shared_context = params.sharedContext;
    if (params.requestedRuntime) body.requested_runtime = params.requestedRuntime;
    if (params.sourceMessageId) body.source_message_id = params.sourceMessageId;
    const response = await this.http.post<ApplicationPreviewStartResponse>(
      `/v1/applications/${encodeURIComponent(embedId)}/preview/start`,
      body,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatApplicationPreviewError(response.data, `Failed to start application preview (HTTP ${response.status})`));
    }
    return response.data;
  }

  async getApplicationPreviewStatus(sessionId: string): Promise<ApplicationPreviewStatusResponse> {
    const response = await this.http.get<ApplicationPreviewStatusResponse>(
      `/v1/applications/preview/${encodeURIComponent(sessionId)}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatApplicationPreviewError(response.data, `Failed to load application preview status (HTTP ${response.status})`));
    }
    return response.data;
  }

  async openApplicationPreview(sessionId: string): Promise<ApplicationPreviewStatusResponse> {
    const response = await this.http.post<ApplicationPreviewStatusResponse>(
      `/v1/applications/preview/${encodeURIComponent(sessionId)}/open`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatApplicationPreviewError(response.data, `Failed to open application preview (HTTP ${response.status})`));
    }
    return response.data;
  }

  async stopApplicationPreview(sessionId: string): Promise<ApplicationPreviewStopResponse> {
    const response = await this.http.post<ApplicationPreviewStopResponse>(
      `/v1/applications/preview/${encodeURIComponent(sessionId)}/stop`,
      {},
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatApplicationPreviewError(response.data, `Failed to stop application preview (HTTP ${response.status})`));
    }
    return response.data;
  }

  async getEmbedVersion(embedIdOrShort: string, version: number): Promise<EmbedVersionContentResponse> {
    const embedId = await this.resolveEmbedId(embedIdOrShort);
    const response = await this.http.get<EmbedVersionContentResponse>(
      `/v1/embeds/${encodeURIComponent(embedId)}/versions/${version}`,
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data) {
      throw new Error(this.formatEmbedVersionError(response.data, `Failed to load embed version ${version} (HTTP ${response.status})`));
    }
    if (typeof response.data.content === "string" || !Array.isArray(response.data.rows)) {
      return response.data;
    }
    return {
      ...response.data,
      content: await this.reconstructEncryptedEmbedVersion(embedId, response.data.rows),
    };
  }

  async restoreEmbedVersion(embedIdOrShort: string, version: number): Promise<EmbedVersionRestoreResponse> {
    const embedId = await this.resolveEmbedId(embedIdOrShort);
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const embed = cache.embeds.find(
      (entry) => String(entry.embed_id ?? entry.id ?? "") === embedId,
    );
    if (!embed) {
      throw new Error(`Embed '${embedId}' not found in local cache. Run 'openmates chats list' to sync first.`);
    }

    const { createHash } = await import("node:crypto");
    const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");
    const embedKey = await this.resolveEmbedKey(
      cache,
      masterKey,
      embed,
      embedId,
      hashedEmbedId,
    );
    if (!embedKey) {
      throw new Error("Could not resolve embed encryption key for version restore.");
    }

    const target = await this.getEmbedVersion(embedId, version);
    if (typeof target.content !== "string") {
      throw new Error("Embed version content was not available for restore.");
    }

    const encryptedCurrentContent = embed.encrypted_content;
    if (typeof encryptedCurrentContent !== "string") {
      throw new Error("Current embed content is not available for encrypted restore.");
    }
    const currentToon = await decryptWithAesGcmCombined(encryptedCurrentContent, embedKey);
    if (!currentToon) {
      throw new Error("Could not decrypt current embed content for restore.");
    }
    const currentObject = parseEmbedContentObject(currentToon);
    const currentVersion =
      typeof embed.version_number === "number" ? embed.version_number : target.current_version;
    if (version === currentVersion) {
      throw new Error("Selected version is already current.");
    }

    const currentContent = extractVersionedEmbedContent(currentObject);
    const newVersion = currentVersion + 1;
    const restoredObject = buildRestoredEmbedContentObject(currentObject, target.content, newVersion);
    const restoredToon = await encodeEmbedContentObject(restoredObject);
    const encryptedRestoredContent = await encryptWithAesGcmCombined(restoredToon, embedKey);
    const restorePatch = buildUnifiedDiffForEmbedRestore(
      currentContent,
      target.content,
      currentVersion,
      newVersion,
    );
    const encryptedPatch = await encryptWithAesGcmCombined(restorePatch, embedKey);
    const contentHash = computeSHA256(target.content);
    const now = Math.floor(Date.now() / 1000);

    const { ws } = await this.openWsClient();
    try {
      await ws.sendAsync("store_embed", {
        embed_id: embedId,
        encrypted_type: embed.encrypted_type,
        encrypted_content: encryptedRestoredContent,
        encrypted_text_preview: embed.encrypted_text_preview,
        status: embed.status || "finished",
        hashed_chat_id: embed.hashed_chat_id,
        hashed_message_id: embed.hashed_message_id,
        hashed_task_id: embed.hashed_task_id,
        hashed_user_id: embed.hashed_user_id,
        embed_ids: embed.embed_ids,
        parent_embed_id: embed.parent_embed_id,
        version_number: newVersion,
        file_path: embed.file_path,
        content_hash: contentHash,
        text_length_chars: target.content.length,
        is_private: embed.is_private ?? false,
        is_shared: embed.is_shared ?? false,
        created_at: normalizeUnixSeconds(embed.created_at, now),
        updated_at: now,
      });
      await ws.sendAsync("store_embed_diff", {
        embed_id: embedId,
        version_number: newVersion,
        encrypted_snapshot: null,
        encrypted_patch: encryptedPatch,
        hashed_user_id: embed.hashed_user_id,
        created_at: now,
      });
    } finally {
      ws.close();
    }

    clearSyncCache();
    return {
      embed_id: embedId,
      restored_from_version: version,
      version_number: newVersion,
      content: target.content,
      content_hash: contentHash,
    };
  }

  private async reconstructEncryptedEmbedVersion(
    embedId: string,
    rows: EmbedVersionMeta[],
  ): Promise<string> {
    const cache = await this.ensureSynced();
    const masterKey = this.getMasterKeyBytes();
    const embed = cache.embeds.find(
      (entry) => String(entry.embed_id ?? entry.id ?? "") === embedId,
    );
    if (!embed) {
      throw new Error(`Embed '${embedId}' not found in local cache. Run 'openmates chats list' to sync first.`);
    }

    const { createHash } = await import("node:crypto");
    const hashedEmbedId = createHash("sha256").update(embedId).digest("hex");
    const embedKey = await this.resolveEmbedKey(
      cache,
      masterKey,
      embed,
      embedId,
      hashedEmbedId,
    );
    if (!embedKey) {
      throw new Error("Could not resolve embed encryption key for version history.");
    }

    const sortedRows = [...rows].sort((a, b) => a.version_number - b.version_number);
    let content: string | null = null;
    for (const row of sortedRows) {
      if (row.encrypted_snapshot) {
        content = await decryptWithAesGcmCombined(row.encrypted_snapshot, embedKey);
        continue;
      }
      if (row.encrypted_patch && content !== null) {
        const patch = await decryptWithAesGcmCombined(row.encrypted_patch, embedKey);
        content = applyUnifiedDiffForEmbedVersion(content, patch ?? "");
      }
    }
    if (content === null) {
      throw new Error("Version history is missing the initial snapshot");
    }
    return content;
  }

  private formatEmbedVersionError(data: unknown, fallback: string): string {
    if (data && typeof data === "object") {
      const detail = (data as { detail?: unknown; message?: unknown }).detail;
      const message = (data as { detail?: unknown; message?: unknown }).message;
      if (typeof detail === "string" && detail.trim()) return detail;
      if (typeof message === "string" && message.trim()) return message;
    }
    return fallback;
  }

  private formatApplicationPreviewError(data: unknown, fallback: string): string {
    if (data && typeof data === "object") {
      const detail = (data as { detail?: unknown; message?: unknown }).detail;
      const message = (data as { detail?: unknown; message?: unknown }).message;
      if (typeof detail === "string" && detail.trim()) return detail;
      if (detail && typeof detail === "object") {
        const nested = (detail as { message?: unknown; code?: unknown }).message ?? (detail as { code?: unknown }).code;
        if (typeof nested === "string" && nested.trim()) return nested;
      }
      if (typeof message === "string" && message.trim()) return message;
    }
    return fallback;
  }

  private async resolveEmbedId(embedIdOrShort: string): Promise<string> {
    if (embedIdOrShort.length >= 32) return embedIdOrShort;
    const cache = await this.ensureSynced();
    const embed = cache.embeds.find(
      (entry) =>
        String(entry.embed_id ?? "").startsWith(embedIdOrShort) ||
        String(entry.id ?? "").startsWith(embedIdOrShort),
    );
    if (!embed) {
      throw new Error(`Embed '${embedIdOrShort}' not found in local cache. Run 'openmates chats list' to sync first.`);
    }
    return String(embed.embed_id ?? embed.id ?? "");
  }

  // ── Mention context builder ─────────────────────────────────────────

  /**
   * Build the context needed for CLI mention resolution.
   * Fetches apps (with skills, focus modes, memory categories) and
   * memory entries from the server, combines with static model/mate data.
   *
   * Mirrors: mentionSearchService.ts data sources
   */
  async buildMentionContext(): Promise<MentionContext> {
    // Fetch apps data (includes skills, focus modes, memory categories)
    let apps: AppInfo[] = [];
    try {
      const data = (await this.listApps()) as {
        apps?: AppInfo[];
      };
      apps = data.apps ?? (Array.isArray(data) ? (data as AppInfo[]) : []);
    } catch {
      // Not logged in or API error — proceed with empty apps
    }

    // Fetch memory entries for entry-level mentions
    let memoryEntries: MemoryEntryInfo[] = [];
    try {
      const memories = await this.listMemories();
      memoryEntries = memories.map((m) => ({
        id: m.id,
        app_id: m.app_id,
        item_type: m.item_type,
        title: (m.data as Record<string, unknown>)?.title as string | undefined,
      }));
    } catch {
      // Not logged in or decryption error — proceed without entries
    }

    return {
      models: CHAT_MODELS,
      mates: MATE_NAMES,
      apps,
      memoryEntries,
    };
  }

  private normalizePath(path: string): string {
    if (path.startsWith("http://") || path.startsWith("https://")) {
      const url = new URL(path);
      return `${url.pathname}${url.search}`;
    }
    // Already an absolute path — use as-is
    if (path.startsWith("/")) return path;
    // Short relative path (e.g. "billing", "usage/summaries") — prefix with settings base
    return `/v1/settings/${path}`;
  }

  private async downloadPaymentPdf(
    path: string,
    fallbackFilename: string,
  ): Promise<DownloadedDocument> {
    this.requireSession();
    const response = await this.http.getBinary(path, this.getCliRequestHeaders());
    if (!response.ok) {
      throw new Error(`Download failed (HTTP ${response.status})`);
    }
    return {
      filename: filenameFromContentDisposition(response.headers.get("content-disposition")) ?? fallbackFilename,
      data: response.data,
    };
  }

  private async ensureEmailEncryptionKey(session: OpenMatesSession): Promise<string> {
    if (session.emailEncryptionKeyB64) return session.emailEncryptionKeyB64;
    await this.hydrateEmailEncryptionKey(session);
    if (session.emailEncryptionKeyB64) return session.emailEncryptionKeyB64;
    throw new Error(
      "Email encryption key is missing. Run `openmates login` again to refresh your local encryption keys.",
    );
  }

  private async hydrateEmailEncryptionKey(session: OpenMatesSession): Promise<void> {
    const response = await this.http.post<{
      success?: boolean;
      user?: Record<string, unknown>;
    }>(
      "/v1/auth/session",
      { session_id: session.sessionId },
      this.getCliRequestHeaders(),
    );
    const encryptedEmail = response.data.user?.encrypted_email_with_master_key;
    if (!response.ok || !response.data.success || typeof encryptedEmail !== "string") {
      return;
    }
    const email = await decryptWithAesGcmCombined(
      encryptedEmail,
      base64ToBytes(session.masterKeyExportedB64),
    );
    if (!email) return;
    session.emailEncryptionKeyB64 = await deriveEmailEncryptionKeyB64(
      email,
      session.userEmailSalt,
    );
  }

  private requireSession(): OpenMatesSession {
    if (!this.session) {
      throw new Error("Not logged in. Run `openmates login`.");
    }
    return this.session;
  }

  getMasterKeyBytes(): Uint8Array {
    const session = this.requireSession();
    return base64ToBytes(session.masterKeyExportedB64);
  }

  private async decryptTopicPreferences(
    encryptedSettings: unknown,
  ): Promise<TopicPreferencesPayload | null> {
    const settings = await this.decryptSettingsRecord(encryptedSettings);
    return normalizeTopicPreferencesPayload(settings[TOPIC_PREFERENCES_SETTINGS_KEY]);
  }

  private async decryptSettingsRecord(
    encryptedSettings: unknown,
  ): Promise<Record<string, unknown>> {
    if (typeof encryptedSettings !== "string" || encryptedSettings.length === 0) {
      return {};
    }
    const decrypted = await decryptWithAesGcmCombined(
      encryptedSettings,
      this.getMasterKeyBytes(),
    );
    if (!decrypted) {
      throw new Error("Failed to decrypt encrypted account settings.");
    }
    const parsed = JSON.parse(decrypted) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return parsed as Record<string, unknown>;
  }

  private getValidSessionFromDisk(): OpenMatesSession | null {
    const session = loadSession();
    if (!session) return null;
    const required = [
      session.apiUrl,
      session.sessionId,
      session.masterKeyExportedB64,
      session.hashedEmail,
      session.userEmailSalt,
    ];
    if (required.some((v) => typeof v !== "string" || v.length === 0)) {
      return null;
    }
    return session;
  }

  private makeWsClient(session: OpenMatesSession): OpenMatesWsClient {
    return new OpenMatesWsClient({
      apiUrl: session.apiUrl,
      sessionId: randomUUID(),
      wsToken: session.wsToken,
      refreshToken: session.cookies.auth_refresh_token ?? null,
      // Same User-Agent as login so OS-based device fingerprint hash matches.
      userAgent: this.getCliUserAgent(),
      // Node.js ws library doesn't auto-send cookies on upgrade requests.
      cookies: session.cookies,
    });
  }

  /**
   * Refresh ws_token, then create and open a WebSocket client.
   * Combines refreshWsToken() + makeWsClient() + ws.open() into one call
   * so every WebSocket usage gets a fresh HMAC token automatically.
   */
  private async openWsClient(): Promise<{
    ws: OpenMatesWsClient;
    session: OpenMatesSession;
    ownerId: string | null;
  }> {
    const ownerId = await this.refreshWsToken();
    const session = this.requireSession();
    const ws = this.makeWsClient(session);
    await ws.open();
    return { ws, session, ownerId };
  }

  /**
   * Refresh the ws_token by calling /auth/session.
   * The HMAC ws_token has a 5-minute TTL — the web app refreshes it on every
   * /auth/session call, but the CLI stores it from login and never updates it.
   * This method fetches a fresh ws_token and captures any rotated cookies.
   */
  private async refreshWsToken(): Promise<string | null> {
    const session = this.requireSession();
    try {
      const res = await this.http.post<{
        success?: boolean;
        ws_token?: string;
        user?: { id?: string; user_id?: string };
      }>("/v1/auth/session", { session_id: session.sessionId }, this.getCliRequestHeaders());
      if (res.ok && res.data.ws_token) {
        session.wsToken = res.data.ws_token;
      }
      // Capture any rotated cookies from the response (HTTP client does this
      // automatically via captureCookies — just persist the updated map).
      session.cookies = this.http.getCookieMap();
      saveSession(session);
      return typeof res.data.user?.id === "string"
        ? res.data.user.id
        : typeof res.data.user?.user_id === "string"
          ? res.data.user.user_id
          : null;
    } catch {
      // Best-effort — if /auth/session fails, proceed with the existing
      // wsToken and let the WebSocket auth cookie fallback handle it.
      return null;
    }
  }

  /**
   * Ensure the local sync cache is up to date. If the cache is fresh,
   * return it directly. Otherwise, do a full WS sync and save to disk.
   *
   * The sync cache stores encrypted data — decryption is always on-demand.
   * SECURITY: decrypted user content is NEVER written to disk.
   */
  async ensureSynced(
    forceRefresh = false,
    refreshChatIds: string[] = [],
  ): Promise<SyncCache> {
    const refreshChatIdSet = new Set(refreshChatIds.filter(Boolean));
    if (!forceRefresh && refreshChatIdSet.size === 0 && isSyncCacheFresh()) {
      const cache = loadSyncCache();
      if (cache) return cache;
    }

    // Delta sync: load existing cache (even if stale) to extract version data.
    // Mirrors chatSyncService.ts:startPhasedSync — sends client_chat_versions
    // so the server skips unchanged chats instead of re-sending everything.
    const existingCache = loadSyncCache();

    // Build delta sync payload from cached data
    const clientChatVersions: Record<
      string,
      { messages_v: number; title_v: number; draft_v: number }
    > = {};
    const clientChatIds: string[] = [];
    const clientEmbedIds: string[] = [];

    if (existingCache) {
      for (const chat of existingCache.chats) {
        const id = String(chat.details.id ?? "");
        if (!id) continue;
        clientChatIds.push(id);
        if (refreshChatIdSet.has(id)) continue;
        clientChatVersions[id] = {
          messages_v: getClientMessagesVersionForSync(chat),
          title_v:
            typeof chat.details.title_v === "number"
              ? chat.details.title_v
              : 0,
          draft_v:
            typeof chat.details.draft_v === "number"
              ? chat.details.draft_v
              : 0,
        };
      }
      for (const embed of existingCache.embeds) {
        const embedId = String(
          (embed as Record<string, unknown>).id ?? "",
        );
        if (embedId) clientEmbedIds.push(embedId);
      }
    }

    const { ws } = await this.openWsClient();
    const chats: CachedChat[] = [];
    const embeds: Record<string, unknown>[] = [];
    const embedKeys: Record<string, unknown>[] = [];
    let newChatSuggestions: Record<string, unknown>[] = [];
    let totalChatCount = 0;
    let reconciliation: AuthoritativeChatReconciliation = { authoritative: false };
    const pendingAIResponses: PendingAIResponseFrame[] = [];
    let pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[] = [];

    try {
      // Send phase:all so the server runs all sync phases over a single WS
      // connection and terminates with phased_sync_complete.
      ws.send("phased_sync_request", {
        phase: "all",
        client_chat_versions: clientChatVersions,
        client_chat_ids: clientChatIds,
        client_embed_ids: clientEmbedIds,
      });

      // Collect every frame until phased_sync_complete (or 90s timeout).
      // Processing inline rather than per-event avoids race conditions where
      // a fast server response could arrive before a waitForMessage listener
      // is registered.
      const frames = await ws.collectMessages("phased_sync_complete", 90_000);

      // Messages keyed by chat_id — merged from phase_1b and background_message_sync.
      const messagesByChatId = new Map<string, string[]>();

      for (const frame of frames) {
        if (frame.type === "phase_1_last_chat_ready") {
          // Primary source for new_chat_suggestions (not included in phase2/3).
          const p = frame.payload as {
            new_chat_suggestions?: Record<string, unknown>[];
          };
          newChatSuggestions = p.new_chat_suggestions ?? [];

        } else if (frame.type === "phase_1b_chat_content_ready") {
          // Messages + embeds for the most recent ~11 chats.
          const p = frame.payload as {
            chats?: Array<{ chat_id: string; messages: string[] | null }>;
            embeds?: Record<string, unknown>[];
            embed_keys?: Record<string, unknown>[];
          };
          for (const c of (p.chats ?? [])) {
            if (c.chat_id && Array.isArray(c.messages) && c.messages.length > 0) {
              messagesByChatId.set(c.chat_id, c.messages);
            }
          }
          if (p.embeds) embeds.push(...p.embeds);
          if (p.embed_keys) embedKeys.push(...p.embed_keys);

        } else if (frame.type === "phase_2_last_20_chats_ready") {
          // Metadata (no messages) for up to 100 chats + authoritative total count.
          const p = frame.payload as {
            chats?: Array<Record<string, unknown>>;
            total_chat_count?: number;
            authoritative?: boolean;
            authoritative_chat_ids?: string[];
            deleted_chat_ids?: string[];
          };
          totalChatCount = p.total_chat_count ?? 0;
          reconciliation = {
            authoritative: p.authoritative === true,
            authoritative_chat_ids: p.authoritative_chat_ids,
            deleted_chat_ids: p.deleted_chat_ids,
          };
          for (const wrapper of (p.chats ?? [])) {
            const details = wrapper.chat_details as Record<string, unknown> | undefined;
            if (!details || typeof details.id !== "string") continue;
            chats.push({ details, messages: [] });
          }

        } else if (frame.type === "background_message_sync") {
          // Chunked message batches for chats not already covered by phase_1b.
          const p = frame.payload as {
            chats?: Array<{ chat_id: string; messages: string[] }>;
            embeds?: Record<string, unknown>[];
            embed_keys?: Record<string, unknown>[];
          };
          for (const c of (p.chats ?? [])) {
            if (c.chat_id && Array.isArray(c.messages) && c.messages.length > 0) {
              messagesByChatId.set(c.chat_id, c.messages);
            }
          }
          if (p.embeds) embeds.push(...p.embeds);
          if (p.embed_keys) embedKeys.push(...p.embed_keys);
        } else if (frame.type === "pending_ai_response") {
          pendingAIResponses.push(frame.payload as PendingAIResponseFrame);
        }
      }
      pendingTaskUpdateJobs = ws.drainPassiveTaskUpdateJobs();

      // Attach collected messages to their chat metadata entries.
      for (const chat of chats) {
        const id = typeof chat.details.id === "string" ? chat.details.id : "";
        const msgs = messagesByChatId.get(id);
        if (msgs && msgs.length > 0) {
          chat.messages = msgs;
        }
      }

      if (totalChatCount === 0) totalChatCount = chats.length;
    } catch (error) {
      ws.close();
      throw error;
    }

    // Delta merge: server only sent new/changed chats. Carry forward
    // unchanged chats from the existing cache so we don't lose them.
    // Also preserve cached messages when the server sends a chat update
    // without messages (delta optimization — messages_v unchanged).
    if (existingCache) {
      const cachedById = new Map(
        existingCache.chats.map((c) => [String(c.details.id ?? ""), c]),
      );
      const serverChatIds = new Set(
        chats.map((c) => String(c.details.id ?? "")),
      );

      // Preserve messages for chats the server sent without messages
      // (server skips messages when client's messages_v matches).
      for (const chat of chats) {
        const chatId = String(chat.details.id ?? "");
        const cached = cachedById.get(chatId);
        if (
          cached &&
          chat.messages.length === 0 &&
          cached.messages.length > 0
        ) {
          const serverV =
            typeof chat.details.messages_v === "number"
              ? chat.details.messages_v
              : 0;
          const cachedV =
            typeof cached.details.messages_v === "number"
              ? cached.details.messages_v
              : 0;
          if (serverV === cachedV) {
            chat.messages = cached.messages;
          }
        }
      }

      for (const cached of existingCache.chats) {
        const cachedId = String(cached.details.id ?? "");
        if (cachedId && !serverChatIds.has(cachedId)) {
          chats.push(cached);
        }
      }
      // Also carry forward embeds/embed_keys not already in the server response
      const serverEmbedIds = new Set(
        embeds.map((e) => String((e as Record<string, unknown>).id ?? "")),
      );
      for (const cached of existingCache.embeds) {
        const cachedId = String(
          (cached as Record<string, unknown>).id ?? "",
        );
        if (cachedId && !serverEmbedIds.has(cachedId)) {
          embeds.push(cached);
        }
      }
      const serverEmbedKeyIds = new Set(
        embedKeys.map((e) =>
          String((e as Record<string, unknown>).id ?? ""),
        ),
      );
      for (const cached of existingCache.embedKeys) {
        const cachedId = String(
          (cached as Record<string, unknown>).id ?? "",
        );
        if (cachedId && !serverEmbedKeyIds.has(cachedId)) {
          embedKeys.push(cached);
        }
      }
    }

    const reconciledChats = reconcileAuthoritativeChats(chats, reconciliation);
    chats.splice(0, chats.length, ...reconciledChats);

    if (reconciliation.deleted_chat_ids?.length) {
      const { createHash } = await import("node:crypto");
      const deletedHashes = new Set(
        reconciliation.deleted_chat_ids.map((id) => createHash("sha256").update(id).digest("hex")),
      );
      const keptEmbeds = embeds.filter((embed) => !deletedHashes.has(String(embed.hashed_chat_id ?? "")));
      const keptKeys = embedKeys.filter((key) => !deletedHashes.has(String(key.hashed_chat_id ?? "")));
      embeds.splice(0, embeds.length, ...keptEmbeds);
      embedKeys.splice(0, embedKeys.length, ...keptKeys);
    }

    // Sort by last_edited_overall_timestamp descending
    chats.sort(
      (a, b) =>
        (typeof b.details.last_edited_overall_timestamp === "number"
          ? b.details.last_edited_overall_timestamp
          : 0) -
        (typeof a.details.last_edited_overall_timestamp === "number"
          ? a.details.last_edited_overall_timestamp
          : 0),
    );

    let persistedTaskJobIds = new Set<string>();
    try {
      await this.persistPendingAIResponsesFromSync(ws, chats, pendingAIResponses);
      persistedTaskJobIds = await this.persistPendingTaskUpdateJobs({
        ws,
        jobs: pendingTaskUpdateJobs,
        events: [],
        activeChatId: null,
        activeChatKeyBytes: null,
        fallbackUserMessageId: null,
        syncedChats: chats,
        requireActiveTurnEvent: false,
      });
    } finally {
      ws.close();
    }

    if (persistedTaskJobIds.size > 0) {
      clearSyncCache();
      return this.ensureSynced(true, refreshChatIds);
    }

    const cache: SyncCache = {
      syncedAt: Date.now(),
      totalChatCount,
      loadedChatCount: chats.length,
      chats,
      embeds,
      embedKeys,
      newChatSuggestions,
    };

    saveSyncCache(cache);
    return cache;
  }

  private async persistPendingAIResponsesFromSync(
    ws: OpenMatesWsClient,
    chats: CachedChat[],
    pendingResponses: PendingAIResponseFrame[],
  ): Promise<void> {
    if (pendingResponses.length === 0) return;

    const masterKey = this.getMasterKeyBytes();

    for (const pending of pendingResponses) {
      const chatId = pending.chat_id;
      const messageId = pending.message_id;
      const content = pending.content;
      if (!chatId || !messageId || !content) continue;

      const chat = chats.find((candidate) => String(candidate.details.id ?? "") === chatId);
      if (!chat) continue;

      const existingIndex = chat.messages.findIndex((raw) => {
        try {
          const message = typeof raw === "string" ? JSON.parse(raw) : raw;
          return message?.message_id === messageId || message?.id === messageId;
        } catch {
          return false;
        }
      });
      if (existingIndex >= 0) {
        const existingRaw = chat.messages[existingIndex];
        try {
          const existing = typeof existingRaw === "string" ? JSON.parse(existingRaw) : existingRaw;
          if (existing?.role === "assistant" && existing?.encrypted_content) continue;
        } catch {
          // Replace malformed same-id rows with the pending authoritative response.
        }
      }

      const encryptedChatKey =
        typeof chat.details.encrypted_chat_key === "string"
          ? chat.details.encrypted_chat_key
          : null;
      if (!encryptedChatKey) continue;

      const chatKeyBytes = await this.decryptChatKey(encryptedChatKey, masterKey);
      if (!chatKeyBytes) continue;

      const completedAt = normalizeUnixSeconds(
        pending.fired_at,
        Math.floor(Date.now() / 1000),
      );
      const currentMessagesV =
        typeof chat.details.messages_v === "number" ? chat.details.messages_v : 0;
      const nextMessagesV = currentMessagesV + 1;
      const encryptedMessage = {
        message_id: messageId,
        chat_id: chatId,
        role: "assistant",
        created_at: completedAt,
        status: "synced",
        encrypted_content: await encryptWithAesGcmCombined(content, chatKeyBytes),
        encrypted_category: pending.category
          ? await encryptWithAesGcmCombined(pending.category, chatKeyBytes)
          : undefined,
        encrypted_model_name: pending.model_name
          ? await encryptWithAesGcmCombined(pending.model_name, chatKeyBytes)
          : undefined,
      };

      const confirmed = ws.waitForMessage(
        "ai_response_storage_confirmed",
        (payload) => {
          const p = payload as Record<string, unknown>;
          return p.message_id === messageId;
        },
        20_000,
      );
      // Legacy pending_ai_response sync compatibility only. Epoch-1 live sends
      // persist through the fenced recovery_job_persist transaction above.
      await ws.sendAsync("ai_response_completed", {
        chat_id: chatId,
        message: encryptedMessage,
        versions: {
          messages_v: nextMessagesV,
          last_edited_overall_timestamp: completedAt,
        },
      });
      await confirmed;

      const serializedMessage = JSON.stringify(encryptedMessage);
      if (existingIndex >= 0) chat.messages[existingIndex] = serializedMessage;
      else chat.messages.push(serializedMessage);
      chat.details.messages_v = nextMessagesV;
      chat.details.last_edited_overall_timestamp = completedAt;
    }
  }

  private async prompt(question: string): Promise<string> {
    const rl = createInterface({ input: stdin, output: stdout });
    try {
      return await rl.question(question);
    } finally {
      rl.close();
    }
  }

  private async waitForPairAuthorization(token: string): Promise<{
    authorizerDeviceName: string | null;
  }> {
    const exitState = this.installPairExitListener();
    let status = "waiting";
    let authorizerDeviceName: string | null = null;
    try {
      while (status === "waiting") {
        if (exitState.canceled) throw new Error("Pairing canceled by user");
        await sleep(2_000);
        if (exitState.canceled) throw new Error("Pairing canceled by user");
        const poll = await this.http.get<{
          status?: string;
          authorizer_device_name?: string;
        }>(`/v1/auth/pair/poll/${token}`, this.getCliRequestHeaders());
        if (!poll.ok) continue;
        status = poll.data.status ?? "waiting";
        authorizerDeviceName =
          typeof poll.data.authorizer_device_name === "string"
            ? poll.data.authorizer_device_name
            : null;
        if (status === "expired")
          throw new Error("Pair token expired before authorization");
      }
    } finally {
      exitState.cleanup();
    }
    return { authorizerDeviceName };
  }

  private installPairExitListener(): {
    canceled: boolean;
    cleanup: () => void;
  } {
    const state = { canceled: false };
    if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
      return { canceled: false, cleanup: () => undefined };
    }
    const wasRaw = stdin.isRaw === true;
    stdin.setRawMode(true);
    stdin.resume();

    const onData = (raw: Buffer | string) => {
      const value = typeof raw === "string" ? raw : raw.toString("utf8");
      const normalized = value.toLowerCase();
      if (normalized.includes("e") || value === "\u001b") state.canceled = true;
      if (value === "\u0003") state.canceled = true;
    };

    stdin.on("data", onData);
    return {
      get canceled() {
        return state.canceled;
      },
      cleanup: () => {
        stdin.off("data", onData);
        stdin.setRawMode(wasRaw);
      },
    };
  }

  private renderPairQrCode(loginUrl: string): void {
    stdout.write("Scan this QR code from your logged-in OpenMates device:\n");
    qrcode.generate(loginUrl, { small: true });
  }

  private getCliRequestHeaders(): Record<string, string> {
    return {
      "User-Agent": this.getCliUserAgent(),
      "X-OpenMates-SDK": "cli",
      "X-OpenMates-Device-Identity": this.getCliApiKeyDeviceIdentity(),
      Origin: deriveAppUrl(this.apiUrl),
    };
  }

  private getCliUserAgent(): string {
    return `${CLI_DEVICE_NAME_PREFIX}/0.1 (${platform()} ${release()})`;
  }

  private getLocalDeviceName(): string {
    return `${CLI_DEVICE_NAME_PREFIX} (${platform()} ${release()})`;
  }

  private getCliApiKeyDeviceIdentity(): string {
    return `cli:${platform()}:${arch()}`;
  }

  // -------------------------------------------------------------------------
  // Docs (public, no auth required)
  // -------------------------------------------------------------------------

  /** Fetch the full documentation tree structure. */
  async listDocs(): Promise<DocsTree> {
    const response = await this.http.get<DocsTree>("/v1/docs");
    if (!response.ok) {
      throw new Error(`Failed to list docs: HTTP ${response.status}`);
    }
    return response.data;
  }

  /** Fetch a single document's raw markdown by slug. */
  async getDoc(slug: string): Promise<string> {
    const url = `/v1/docs/${encodeURIComponent(slug)}`;
    const response = await this.http.get<string>(url);
    if (!response.ok) {
      throw new Error(
        response.status === 404
          ? `Document not found: ${slug}`
          : `Failed to get doc: HTTP ${response.status}`,
      );
    }
    // The response is plain text markdown
    return typeof response.data === "string"
      ? response.data
      : JSON.stringify(response.data);
  }

  /** Search docs by query string. Returns matching docs with snippets. */
  async searchDocs(query: string): Promise<DocsSearchResult[]> {
    const url = `/v1/docs/search?q=${encodeURIComponent(query)}`;
    const response = await this.http.get<DocsSearchResult[]>(url);
    if (!response.ok) {
      throw new Error(`Failed to search docs: HTTP ${response.status}`);
    }
    return response.data;
  }
}

// Docs types
export interface DocsTree {
  folders: DocsFolder[];
  files: DocsFile[];
}

export interface DocsFolder {
  path: string;
  title: string;
  folders: DocsFolder[];
  files: DocsFile[];
}

export interface DocsFile {
  slug: string;
  title: string;
  filename: string;
  wordCount: number;
}

export interface DocsSearchResult {
  slug: string;
  title: string;
  snippet: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse the YAML-like key:value format used by some embed content fields.
 *
 * Format (from backend embed_service.py text serialisation):
 *   type: sheet
 *   app_id: sheets
 *   table: "| Col | Col |\n| --- | --- |"
 *   row_count: 5
 *
 * Quoted string values (single or double) are unquoted.
 * Numeric values are coerced to numbers.
 * Multi-line values joined with real newlines.
 */
function parseYamlLikeContent(raw: string): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  // Split on lines that start a new key: "^key: " pattern
  // Keys are word chars / underscores / hyphens, followed by ": "
  const keyPattern = /^([\w-]+):\s*/;
  const lines = raw.split("\n");
  let currentKey: string | null = null;
  let currentValue = "";

  const flush = () => {
    if (currentKey === null) return;
    let v: unknown = currentValue.trim();
    // Unquote strings
    if (
      (typeof v === "string" && v.startsWith('"') && v.endsWith('"')) ||
      (typeof v === "string" && v.startsWith("'") && v.endsWith("'"))
    ) {
      v = (v as string).slice(1, -1).replace(/\\n/g, "\n").replace(/\\"/g, '"');
    }
    // Coerce numbers
    if (typeof v === "string" && v !== "" && !isNaN(Number(v))) {
      v = Number(v);
    }
    result[currentKey] = v;
    currentKey = null;
    currentValue = "";
  };

  for (const line of lines) {
    const m = keyPattern.exec(line);
    if (m) {
      flush();
      currentKey = m[1];
      currentValue = line.slice(m[0].length);
    } else if (currentKey !== null) {
      // Continuation line for a multi-line value
      currentValue += "\n" + line;
    }
  }
  flush();
  return result;
}

function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)?.[1];
  if (encoded) return decodeURIComponent(encoded);
  const quoted = /filename="([^"]+)"/i.exec(header)?.[1];
  if (quoted) return quoted;
  const plain = /filename=([^;]+)/i.exec(header)?.[1];
  return plain?.trim() ?? null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Print the OpenMates ASCII logo — "Open" in bold white, "Mates" in brand blue. */
function printLogo(): void {
  const W = "\x1b[1;37m"; // bold white
  const B = "\x1b[38;2;74;103;205m"; // brand blue #4A67CD
  const R = "\x1b[0m"; // reset
  const lines = [
    `${W} █▀▀█ █▀▀█ █▀▀ █▀▀▄${B} █▀▄▀█ █▀▀█ ▀▀█▀▀ █▀▀ █▀▀${R}`,
    `${W} █  █ █▄▄█ █▀▀ █  █${B} █ ▀ █ █▄▄█   █   █▀▀ ▀▀█${R}`,
    `${W} ▀▀▀▀ ▀    ▀▀▀ ▀  ▀${B} ▀   ▀ ▀  ▀   ▀   ▀▀▀ ▀▀▀${R}`,
  ];
  stdout.write(lines.join("\n") + "\n");
}
