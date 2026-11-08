/*
 * OpenMates CLI/SDK public entrypoint.
 *
 * Purpose: export the SDK client and storage types for Node integrations.
 * Architecture: thin barrel over the CLI package internals.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: pair-auth remains the primary login mechanism in client methods.
 * Tests: exercised via CLI and targeted crypto/storage tests.
 */

// SDK root export: implicit stored-CLI-login loading emits a one-time
// DeprecationWarning (OPENMATES_SDK_CLI_SESSION). The CLI imports ./client.js.
export { OpenMatesClient, OpenMatesApiKeyRequiredError, SDK_API_KEY_REQUIRED_CODE } from "./sdkRootClient.js";
export type { OpenMatesClientOptions } from "./sdkRootClient.js";
export {
  deriveAppUrl,
  INTEREST_TAG_IDS,
  MATE_NAMES,
  normalizeInterestTagIds,
  reconcileAuthoritativeChats,
} from "./client.js";
export { serializeToYaml, getExtForLang } from "./cli.js";
export { createChatModelPreferences } from "./chatModelPreferences.js";
export { buildCalendarEventFile } from "../../ui/src/utils/calendarDownload.js";
export type { CalendarEvent, CalendarEventDocument } from "../../ui/src/utils/calendarEvent.js";
export type {
  ChatModelCatalog, ChatModelCatalogEntry, ChatModelPreferenceState, ChatModelPreferences,
  ChatModelSelection, ChatModelValidation,
} from "./chatModelPreferences.js";
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
export { OpenMates, OpenMatesSignupRequiredError, OpenMatesApiError, OpenMatesConfigError, OpenMatesUnavailableError } from "./sdk.js";
export { APP_SKILL_METADATA } from "./generated/appSkills.js";
export { SessionClient, SessionClientError, SessionTasks, SessionProjects } from "./sdkSession.js";
export type { SessionSavedChatReadMetadata, SessionSavedChatMessageMetadata, SessionSavedChatReadOptions, SessionSavedChatRead, SessionSavedChatExactOptions, SessionSavedChatExactMessage, SessionMessageWindowCursor, SessionMessageWindowOptions, SessionMessageWindow, SessionClientOptions, SessionChatWithMetadata, SessionChat, SessionStreamEvent, SessionWorkScope, SessionTaskFilters, SessionProjectFilters, SessionExternalChat, SessionTaskCreate, SessionTaskPatch, SessionProjectCreate, SessionProjectPatch, SessionProjectUnlinkInput, SessionAnonymousOptions, SessionAnonymousOutcome, SessionAnonymousStreamEvent } from "./sdkSession.js";
export { sortTasks } from "./sdkTaskOrder.js";
export type { TaskOrderRow, TaskOrderOptions } from "./sdkTaskOrder.js";
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
  WorkflowRunOptions,
  WorkflowRunOnceOptions,
  WorkflowRunRouting,
  WorkflowReturnedOutputReference,
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
  RawDownload,
  AnonymousUsageStatus,
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

export type { BuyerAddress } from "./billingAddress.js";

export type { CliTurnMetadata } from "./ownedTurnMetadata.js";

export type { SessionFirstPageOptions, SessionFirstPagePublication, SessionFirstPageStore } from "./sdkFirstPage.js";
export type { SessionChatDetailsHistory, SessionChatDetailsOptions, SessionChatDetailsMetadata, SessionChatDetailsMessage, SessionChatDetailsRead } from "./sdkSession.js";
export { RustApiKeyClient, RustApiKeyClientError } from "./sdkApiKeyRust.js";
export type { RustApiKeyOptions, RustApiKeyCallOptions } from "./sdkApiKeyRust.js";
