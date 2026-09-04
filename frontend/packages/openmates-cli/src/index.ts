/*
 * OpenMates CLI/SDK public entrypoint.
 *
 * Purpose: export the SDK client and storage types for Node integrations.
 * Architecture: thin barrel over the CLI package internals.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: pair-auth remains the primary login mechanism in client methods.
 * Tests: exercised via CLI and targeted crypto/storage tests.
 */

export {
  OpenMatesClient,
  deriveAppUrl,
  INTEREST_TAG_IDS,
  MEMORY_TYPE_REGISTRY,
  MATE_NAMES,
  normalizeInterestTagIds,
  reconcileAuthoritativeChats,
} from "./client.js";
export { serializeToYaml, getExtForLang } from "./cli.js";
export {
  projectAssistantSpeech,
  selectAssistantMessagesForSpeech,
  summarizeAssistantSpeech,
} from "./assistantSpeech.js";
export {
  buildImagesAiDetectionSummary,
  classifyImagesAiDetection,
  formatImagesAiDetectionLabel,
  type ImagesAiDetectionClassification,
  type ImagesAiDetectionSummary,
} from "./cli.js";
export { defaultCloneBranchForVersion } from "./server.js";
export { SUPPORT_URL, renderSupportInfo } from "./support.js";
export { OpenMates, OpenMatesApiError, OpenMatesConfigError } from "./sdk.js";
export { APP_SKILL_METADATA } from "./generated/appSkills.js";
export {
  buildCreatePlanCriterionInput,
  buildCreatePlanLearningInput,
  buildCreatePlanVerificationInput,
  buildCreateUserPlanInput,
  buildPlanVerificationEvidenceInput,
  buildUpdatePlanLearningInput,
  buildUpdatePlanVerificationInput,
  buildUpdateUserPlanInput,
  decryptPlanLearning,
  decryptPlanLearnings,
  decryptUserPlan,
  decryptUserPlans,
  findPlan,
  findPlanLearning,
  renderPlanDetail,
  renderPlanLearningDetail,
  renderPlanLearningList,
  renderPlanList,
} from "./plansCli.js";
export {
  ASSISTANT_FEEDBACK_REPORT_TITLE,
  ASSISTANT_FEEDBACK_THANKS,
  buildAssistantFeedbackDecision,
} from "./feedback.js";
export type { AssistantFeedbackDecision } from "./feedback.js";
export type {
  DecryptedMemoryEntry,
  DecryptedMessage,
  DecryptedEmbed,
  DecryptedNewChatSuggestion,
  DecryptedDraft,
  EncryptedDraft,
  AuthoritativeChatReconciliation,
  ChatListPage,
  MemoryTypeDef,
  MemoryFieldDef,
  OpenMatesClientOptions,
  BankTransferOrderDetails,
  BankTransferStatus,
  GiftCardBankTransferStatus,
  InterestTagId,
  TopicPreferencesPayload,
  WorkflowCapability,
  WorkflowDetail,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeRun,
  WorkflowNodeType,
  WorkflowRunContentRetention,
  WorkflowRunContentStorage,
  WorkflowRunDetail,
  WorkflowSummary,
  AuthMethodsStatus,
  CliSignupResult,
  TotpSetupStartResult,
  BackupCodesResult,
  DocsTree,
  DocsFolder,
  DocsFile,
  DocsSearchResult,
} from "./client.js";
export type {
  ChatCreateOptions,
  ChatListOptions,
  ChatResponse,
  ApiKeyCreateOptions,
  ApiKeyCreateResult,
  ApiKeyRecord,
  EncryptedChatMetadata,
  DraftRecord,
  EncryptedDraftRecord,
  FocusModeSelection,
  IdeaBucketAddInput,
  IdeaBucketProcessOptions,
  IdeaBucketResult,
  IdeaBucketSettings,
  IdeaBucketSettingsInput,
  OpenMatesOptions,
  TaskListFilters,
  PlanPlainCreateOptions,
  PlanPlainUpdateOptions,
  PlanRecord,
  ProjectPlainCreateOptions,
  ProjectPlainUpdateOptions,
  ProjectRecordPlain,
  TaskPlainCreateOptions,
  TaskPlainUpdateOptions,
  TaskRecord,
} from "./sdk.js";
export type {
  DesignIconExportFormat,
  DesignIconExportOptions,
  DesignIconExportResult,
} from "./designIcons.js";
export type { DecryptedUserTask } from "./tasksCli.js";
export type {
  OpenMatesSession,
  SyncCache,
  CachedChat,
  CachedNewChatSuggestion,
} from "./storage.js";
