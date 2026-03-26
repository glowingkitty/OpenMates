/**
 * chatSyncServiceSenders.ts — Barrel re-export for backwards compatibility
 *
 * All sender implementations have been split into focused domain modules.
 * This file re-exports everything so existing `import { ... } from "./chatSyncServiceSenders"`
 * and `await import("./chatSyncServiceSenders")` calls continue working unchanged.
 *
 * Modules:
 *   sendersChatMessages.ts — Message sending + encrypted storage
 *   sendersChatManagement.ts — Chat CRUD operations
 *   sendersDrafts.ts — Draft management
 *   sendersEmbeds.ts — Embed operations
 *   sendersSync.ts — Sync utilities + misc senders
 */
export * from "./sendersChatMessages";
export * from "./sendersChatManagement";
export * from "./sendersDrafts";
export * from "./sendersEmbeds";
export * from "./sendersSync";
