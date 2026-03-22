// frontend/packages/ui/src/services/db/index.ts
// Re-exports all database operation modules for cleaner imports.
// This allows importing from '@services/db' instead of individual files.

// New chat suggestions operations (encrypted suggestions for starting new conversations)
export * from './newChatSuggestions';

// App settings and memories operations (per-app user preferences and memories)
export * from './appSettingsMemories';

// Chat key management (encryption key cache and message encryption/decryption)
export * from './chatKeyManagement';

// Message operations (CRUD, duplicate detection, encryption)
export * from './messageOperations';

// Chat CRUD operations (create, read, update, delete, drafts)
export * from './chatCrudOperations';

// Offline changes and chat updates (sync queue, version updates)
export * from './offlineChangesAndUpdates';
