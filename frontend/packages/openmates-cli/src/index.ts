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
} from "./client.js";
export type {
  DecryptedMemoryEntry,
  MemoryTypeDef,
  MemoryFieldDef,
  OpenMatesClientOptions,
} from "./client.js";
export type { OpenMatesSession } from "./storage.js";
