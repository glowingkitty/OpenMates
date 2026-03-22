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
  parseNewChatSuggestionText,
} from "./client.js";
export { serializeToYaml, getExtForLang } from "./cli.js";
export type {
  DecryptedMemoryEntry,
  DecryptedMessage,
  DecryptedEmbed,
  DecryptedNewChatSuggestion,
  ChatListPage,
  MemoryTypeDef,
  MemoryFieldDef,
  OpenMatesClientOptions,
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
