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
  MEMORY_TYPE_REGISTRY,
  MATE_NAMES,
} from "./client.js";
export { serializeToYaml, getExtForLang } from "./cli.js";
export { defaultCloneBranchForVersion } from "./server.js";
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
  ChatListPage,
  MemoryTypeDef,
  MemoryFieldDef,
  OpenMatesClientOptions,
  BankTransferOrderDetails,
  BankTransferStatus,
  GiftCardBankTransferStatus,
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
  OpenMatesSession,
  SyncCache,
  CachedChat,
  CachedNewChatSuggestion,
} from "./storage.js";
