// frontend/packages/ui/src/services/db.ts
// Manages IndexedDB storage for chat-related data.
//
// This file contains the core ChatDatabase class that manages IndexedDB operations.
// Specialized operations are extracted into separate modules in the ./db/ directory:
// - ./db/newChatSuggestions.ts - New chat suggestions CRUD operations
// - ./db/appSettingsMemories.ts - App settings and memories operations
// - ./db/chatKeyManagement.ts - Chat key cache and encryption operations
// - ./db/messageOperations.ts - Message CRUD, duplicate handling, encryption
// - ./db/chatCrudOperations.ts - Chat CRUD, encryption/decryption, drafts
// - ./db/offlineChangesAndUpdates.ts - Offline changes and chat updates
//
// This file contains:
// - Database initialization and migrations
// - Transaction management
// - Data clearing and database deletion
// - Public API methods that delegate to extracted modules

import type {
  Chat,
  Message,
  ChatComponentVersions,
  OfflineChange,
  NewChatSuggestion,
  StoreEmbedPayload,
} from "../types/chat";

// Import extracted modules for delegation
import * as newChatSuggestionsOps from "./db/newChatSuggestions";
import * as appSettingsMemoriesOps from "./db/appSettingsMemories";
import * as chatKeyManagementOps from "./db/chatKeyManagement";
import * as messageOps from "./db/messageOperations";
import * as chatCrudOps from "./db/chatCrudOperations";
import * as offlineOps from "./db/offlineChangesAndUpdates";

// Import logout state to prevent database re-initialization during logout
import { get } from "svelte/store";
import { forcedLogoutInProgress, isLoggingOut } from "../stores/signupState";

// Minimal type helpers for migration paths where IndexedDB records can include legacy fields.
type ChatRecordWithMessages = Chat & { messages?: Message[] };
type MessageRecordWithTimestamp = Message & { timestamp?: number };
type EmbedMigrationRecord = {
  data?: string;
  contentRef?: string;
  encrypted_content?: string | null;
  createdAt?: number;
  updatedAt?: number;
  embed_id?: string | null;
  encrypted_type?: string | null;
  encrypted_text_preview?: string | null;
  status?: string | null;
  hashed_chat_id?: string | null;
  hashed_message_id?: string | null;
  hashed_task_id?: string | null;
  hashed_user_id?: string | null;
  embed_ids?: string[] | string | null;
  parent_embed_id?: string | null;
  version_number?: number | null;
  file_path?: string | null;
  content_hash?: string | null;
  text_length_chars?: number | null;
  is_private?: boolean | null;
  is_shared?: boolean | null;
};

// Helper to safely detect Date values when legacy records store Date objects.
const isDateValue = (value: unknown): value is Date => value instanceof Date;

/**
 * Represents a pending embed operation queued in IndexedDB for offline sync.
 * When the WebSocket is disconnected during embed encryption, the operation
 * is stored here and flushed on reconnect.
 */
export interface PendingEmbedOperation {
  operation_id: string;
  embed_id: string;
  store_embed_payload: StoreEmbedPayload;
  store_embed_keys_payload?: { keys: Array<Record<string, unknown>> };
  created_at: number;
}

class ChatDatabase {
  // Database instance - public for extracted modules to access
  public db: IDBDatabase | null = null;

  // Database and store names
  private readonly DB_NAME = "chats_db";
  public readonly CHATS_STORE_NAME = "chats";
  private readonly MESSAGES_STORE_NAME = "messages";
  private readonly OFFLINE_CHANGES_STORE_NAME = "pending_sync_changes";
  public readonly NEW_CHAT_SUGGESTIONS_STORE_NAME = "new_chat_suggestions";
  public readonly APP_SETTINGS_MEMORIES_STORE_NAME = "app_settings_memories";
  private readonly PENDING_OG_METADATA_STORE_NAME =
    "pending_og_metadata_updates";
  private readonly PENDING_EMBED_OPERATIONS_STORE_NAME =
    "pending_embed_operations";
  private readonly PENDING_EMBED_SHARE_STORE_NAME =
    "pending_embed_share_updates";

  // Version incremented for various schema changes
  // Version 15: Added pinned field and index for chat pinning functionality
  // Version 16: Added hashed_chat_id index to embeds store for embed cleanup on chat deletion
  // Version 17: (Removed) Was app_settings_memories_actions store - now using system messages instead
  // Version 18: Added pending_embed_share_updates store for embed share metadata retry queue
  // Version 19: Added pending_embed_operations store for offline embed queue
  private readonly VERSION = 19;
  private initializationPromise: Promise<void> | null = null;

  // Flag to prevent new operations during database deletion
  private isDeleting: boolean = false;

  // Flag to skip orphan detection for shared chat sessions.
  // This is backed by sessionStorage to persist across page navigations within
  // the same browser session. This is needed because shared chats are stored
  // without a master key (they use URL-embedded encryption keys), so the
  // "no master key but has chats" condition is expected and NOT orphan data.
  private static readonly SKIP_ORPHAN_DETECTION_KEY =
    "openmates_skip_orphan_detection";

  // Chat key cache for performance - public for chatKeyManagement module to access
  public chatKeys: Map<string, Uint8Array> = new Map();

  // ============================================================================
  // DATABASE INITIALIZATION
  // ============================================================================

  /**
   * Check if skip orphan detection is enabled (via sessionStorage).
   * This persists across page navigations within the same browser session.
   */
  private isSkipOrphanDetectionEnabled(): boolean {
    if (typeof sessionStorage === "undefined") return false;
    return (
      sessionStorage.getItem(ChatDatabase.SKIP_ORPHAN_DETECTION_KEY) === "true"
    );
  }

  /**
   * Enable skip orphan detection mode for shared chat sessions.
   *
   * This should be called BEFORE any database operations to prevent the orphan
   * detection logic from incorrectly flagging shared chats as orphan data.
   *
   * Shared chats are stored without a master key (they use URL-embedded encryption keys),
   * so the "no master key but has chats" condition is expected and NOT orphan data.
   *
   * Once enabled, this flag persists in sessionStorage across page navigations
   * within the same browser session (but clears when the tab is closed).
   */
  public enableSkipOrphanDetection(): void {
    if (typeof sessionStorage !== "undefined") {
      sessionStorage.setItem(ChatDatabase.SKIP_ORPHAN_DETECTION_KEY, "true");
    }
    console.debug(
      "[ChatDatabase] Enabled skipOrphanDetection mode for shared chat session",
    );
  }

  /**
   * Disable skip orphan detection mode.
   * Called when user logs in (master key available) to restore normal orphan detection.
   */
  public disableSkipOrphanDetection(): void {
    if (typeof sessionStorage !== "undefined") {
      sessionStorage.removeItem(ChatDatabase.SKIP_ORPHAN_DETECTION_KEY);
    }
    console.debug("[ChatDatabase] Disabled skipOrphanDetection mode");
  }

  /**
   * Initialize the database.
   *
   * CRITICAL: This method prevents initialization during logout to avoid race conditions
   * where the database is re-opened after deletion has started but before it completes.
   * The forcedLogoutInProgress and isLoggingOut flags are checked to ensure the database
   * remains closed during the entire logout/deletion process.
   *
   * ORPHANED DATABASE DETECTION: On page reload, components may call database operations
   * BEFORE +page.svelte's onMount sets the forcedLogoutInProgress flag. This method now
   * detects the "orphaned database" scenario (profile exists but no master key) and sets
   * the flag itself, ensuring cleanup happens even if this is the first database operation.
   *
   * @param options.skipOrphanDetection - If true, skip orphan detection. Use for shared chat
   *        pages where chats are stored without a master key (they use URL-embedded keys).
   *        Default: false
   */
  async init(options: { skipOrphanDetection?: boolean } = {}): Promise<void> {
    const { skipOrphanDetection = false } = options;

    // Make skipOrphanDetection persistent via sessionStorage - once set to true, it
    // stays true for all subsequent init() calls AND survives page navigations.
    // This handles:
    // 1. Internal methods like getTransaction() calling init() without the flag
    // 2. Navigation from share chat page to main app (different page load)
    if (skipOrphanDetection) {
      this.enableSkipOrphanDetection();
    }
    const shouldSkipOrphanDetection = this.isSkipOrphanDetectionEnabled();

    // Prevent initialization during deletion
    if (this.isDeleting) {
      throw new Error("Database is being deleted and cannot be initialized");
    }

    // CRITICAL: Detect "orphaned database" scenario BEFORE checking flags or opening DB
    // This handles the race condition where components call database operations BEFORE
    // +page.svelte's onMount can set the forcedLogoutInProgress flag.
    //
    // Scenario: User reloads page with stayLoggedIn=false -> master key is gone but
    // IndexedDB still has encrypted chats from the previous session.
    //
    // Detection approach:
    // 1. Check if we've already detected cleanup is needed (via localStorage marker)
    // 2. If not, check if master key is missing AND database exists (contains encrypted data)
    // 3. If so, set the flag to trigger cleanup
    //
    // Note: We use localStorage 'openmates_needs_cleanup' as a marker because IndexedDB
    // profile check would require opening the database (chicken-and-egg problem).
    //
    // EXCEPTION: Skip orphan detection for shared chat pages. Shared chats are stored
    // without a master key (they use URL-embedded encryption keys), so the "no master key
    // but has chats" condition is expected and NOT an orphan scenario.
    if (
      !shouldSkipOrphanDetection &&
      !get(forcedLogoutInProgress) &&
      !get(isLoggingOut)
    ) {
      // Check if cleanup marker was already set by +page.svelte or a previous init() call
      const needsCleanup =
        typeof localStorage !== "undefined" &&
        localStorage.getItem("openmates_needs_cleanup") === "true";

      if (needsCleanup) {
        console.warn(
          "[ChatDatabase] CLEANUP MARKER FOUND - setting forcedLogoutInProgress",
        );
        forcedLogoutInProgress.set(true);
      } else {
        // Check if master key is missing - if so, we can't decrypt encrypted chats
        // Dynamically import to avoid circular dependencies
        const { getKeyFromStorage } = await import("./cryptoService");
        const hasMasterKey = await getKeyFromStorage();

        if (!hasMasterKey) {
          // Check if database exists and contains encrypted data
          // Only trigger cleanup if there are actual encrypted chats that can't be decrypted
          if (typeof indexedDB !== "undefined") {
            // Check if database exists and contains encrypted data
            // Only trigger cleanup if there are actual encrypted chats that can't be decrypted
            try {
              // Check localStorage marker for faster detection
              const dbInitialized =
                typeof localStorage !== "undefined" &&
                localStorage.getItem("openmates_chats_db_initialized") ===
                  "true";

              if (dbInitialized) {
                // Try to open database and check if it contains encrypted chats
                // This is a more precise check than just checking if DB exists
                const checkRequest = indexedDB.open(this.DB_NAME, this.VERSION);

                checkRequest.onsuccess = (event) => {
                  const db = (event.target as IDBOpenDBRequest).result;
                  const transaction = db.transaction(
                    [this.CHATS_STORE_NAME],
                    "readonly",
                  );
                  const store = transaction.objectStore(this.CHATS_STORE_NAME);
                  const countRequest = store.count();

                  countRequest.onsuccess = () => {
                    const chatCount = countRequest.result;
                    if (chatCount > 0) {
                      console.warn(
                        "[ChatDatabase] ORPHANED DATABASE DETECTED: No master key but found",
                        chatCount,
                        "encrypted chats",
                      );
                      console.warn(
                        "[ChatDatabase] Setting cleanup marker and forcedLogoutInProgress=true",
                      );
                      if (typeof localStorage !== "undefined") {
                        localStorage.setItem("openmates_needs_cleanup", "true");
                      }
                      forcedLogoutInProgress.set(true);
                    }
                    db.close();
                  };

                  countRequest.onerror = () => {
                    db.close();
                  };
                };

                checkRequest.onerror = () => {
                  // Database doesn't exist or can't be opened, no cleanup needed
                };
              }
            } catch {
              // Error checking database, assume no cleanup needed
            }
          }
        }
      }
    }

    // CRITICAL: Prevent initialization during logout to avoid race conditions
    // If forced logout is in progress (missing master key scenario), or if user is actively
    // logging out, we should NOT re-initialize the database. This prevents a race condition
    // where the database is re-opened after it was closed for deletion but before the
    // actual deleteDatabase() call completes. Without this check, database deletion fails
    // silently because there's a new open connection blocking it.
    //
    // EXCEPTIONS:
    // 1. Allow initialization during login/auth attempts to prevent blocking
    //    legitimate authentication flows (e.g., after server restart WebSocket auth errors)
    // 2. Allow initialization for shared chat sessions (skipOrphanDetectionPersistent=true)
    //    because shared chats use URL-embedded keys, not the master key
    const { isCheckingAuth } = await import("../stores/authState");
    const isAuthInProgress = get(isCheckingAuth);
    if (
      (get(forcedLogoutInProgress) || get(isLoggingOut)) &&
      !isAuthInProgress &&
      !shouldSkipOrphanDetection
    ) {
      console.debug(
        "[ChatDatabase] Skipping init() - logout in progress (forcedLogout:",
        get(forcedLogoutInProgress),
        ", isLoggingOut:",
        get(isLoggingOut),
        ", isCheckingAuth:",
        isAuthInProgress,
        ")",
      );
      throw new Error(
        "Database initialization blocked during logout - data will be deleted",
      );
    }

    if (this.initializationPromise) {
      return this.initializationPromise;
    }

    this.initializationPromise = new Promise((resolve, reject) => {
      console.debug(
        "[ChatDatabase] Initializing database, Version:",
        this.VERSION,
      );
      const request = indexedDB.open(this.DB_NAME, this.VERSION);

      request.onblocked = (event) => {
        console.error(
          `[ChatDatabase] CRITICAL: Database open blocked! Please close other tabs. Event:`,
          event,
        );
        reject(new Error("Database open request is blocked."));
      };

      request.onerror = () => {
        console.error("[ChatDatabase] Error opening database:", request.error);
        this.initializationPromise = null;
        reject(request.error);
      };

      request.onsuccess = async () => {
        console.debug("[ChatDatabase] Database opened successfully");
        this.db = request.result;

        // Set marker in localStorage to indicate database has been initialized
        // This is used by orphaned database detection to know if cleanup is needed
        if (typeof localStorage !== "undefined") {
          localStorage.setItem("openmates_chats_db_initialized", "true");
        }

        // Load chat keys from database into cache
        try {
          await this.loadChatKeysFromDatabase();
        } catch (error) {
          console.error(
            "[ChatDatabase] Error loading chat keys during initialization:",
            error,
          );
        }

        // Load shared chat keys from IndexedDB into memory cache
        // This enables shared chats to survive page reloads for unauthenticated users.
        // Shared chat keys are stored separately in openmates_shared_keys DB since they're
        // not wrapped with a master key (unauthenticated users have no master key).
        try {
          await this.loadSharedChatKeysFromStorage();
        } catch (error) {
          console.error(
            "[ChatDatabase] Error loading shared chat keys during initialization:",
            error,
          );
        }

        // Clean up duplicate messages on initialization
        try {
          await messageOps.cleanupDuplicateMessages(this);
        } catch (error) {
          console.error(
            "[ChatDatabase] Error during duplicate cleanup on initialization:",
            error,
          );
        }

        resolve();
      };

      request.onupgradeneeded = (event) => {
        console.debug("[ChatDatabase] Database upgrade needed");
        const db = (event.target as IDBOpenDBRequest).result;
        const transaction = (event.target as IDBOpenDBRequest).transaction;

        this.performMigrations(
          db,
          transaction,
          event.oldVersion,
          event.newVersion || this.VERSION,
        );
      };
    });
  }

  /**
   * Perform database migrations based on version changes
   */
  private performMigrations(
    db: IDBDatabase,
    transaction: IDBTransaction | null,
    oldVersion: number,
    newVersion: number,
  ): void {
    // Mark the version parameter as used to avoid linter noise when newVersion is only logged elsewhere.
    void newVersion;
    // Chats store
    if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
      const chatStore = db.createObjectStore(this.CHATS_STORE_NAME, {
        keyPath: "chat_id",
      });
      chatStore.createIndex(
        "last_edited_overall_timestamp",
        "last_edited_overall_timestamp",
        { unique: false },
      );
      chatStore.createIndex("updated_at", "updated_at", { unique: false });
      chatStore.createIndex("pinned", "pinned", { unique: false });
    } else if (transaction) {
      const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
      if (!chatStore.indexNames.contains("last_edited_overall_timestamp")) {
        chatStore.createIndex(
          "last_edited_overall_timestamp",
          "last_edited_overall_timestamp",
          { unique: false },
        );
      }
      if (!chatStore.indexNames.contains("updated_at")) {
        chatStore.createIndex("updated_at", "updated_at", { unique: false });
      }
      if (!chatStore.indexNames.contains("pinned")) {
        chatStore.createIndex("pinned", "pinned", { unique: false });
      }
      if (chatStore.indexNames.contains("updatedAt")) {
        chatStore.deleteIndex("updatedAt");
      }
    }

    // Messages store
    if (!db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
      const messagesStore = db.createObjectStore(this.MESSAGES_STORE_NAME, {
        keyPath: "message_id",
      });
      messagesStore.createIndex(
        "chat_id_created_at",
        ["chat_id", "created_at"],
        { unique: false },
      );
      messagesStore.createIndex("chat_id", "chat_id", { unique: false });
      messagesStore.createIndex("created_at", "created_at", { unique: false });
    } else if (transaction && oldVersion < 7) {
      const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
      if (messagesStore.indexNames.contains("chat_id_timestamp")) {
        messagesStore.deleteIndex("chat_id_timestamp");
      }
      if (messagesStore.indexNames.contains("timestamp")) {
        messagesStore.deleteIndex("timestamp");
      }
      if (!messagesStore.indexNames.contains("chat_id_created_at")) {
        messagesStore.createIndex(
          "chat_id_created_at",
          ["chat_id", "created_at"],
          { unique: false },
        );
      }
      if (!messagesStore.indexNames.contains("created_at")) {
        messagesStore.createIndex("created_at", "created_at", {
          unique: false,
        });
      }
    }

    // Data migrations for messages
    if (transaction && oldVersion < 6) {
      this.migrateMessagesFromChats(transaction);
    }
    if (transaction && oldVersion < 7) {
      this.migrateMessageTimestamps(transaction);
    }

    // Remove old User Drafts store if it exists
    const oldUserDraftsStoreName = "user_drafts";
    if (db.objectStoreNames.contains(oldUserDraftsStoreName)) {
      console.info(
        `[ChatDatabase] Deleting old store: ${oldUserDraftsStoreName}`,
      );
      db.deleteObjectStore(oldUserDraftsStoreName);
    }

    // Offline changes store
    if (!db.objectStoreNames.contains(this.OFFLINE_CHANGES_STORE_NAME)) {
      db.createObjectStore(this.OFFLINE_CHANGES_STORE_NAME, {
        keyPath: "change_id",
      });
    }

    // New chat suggestions store
    if (!db.objectStoreNames.contains(this.NEW_CHAT_SUGGESTIONS_STORE_NAME)) {
      const suggestionsStore = db.createObjectStore(
        this.NEW_CHAT_SUGGESTIONS_STORE_NAME,
        { keyPath: "id" },
      );
      suggestionsStore.createIndex("created_at", "created_at", {
        unique: false,
      });
      suggestionsStore.createIndex("chat_id", "chat_id", { unique: false });
      console.debug("[ChatDatabase] Created new_chat_suggestions store");
    }

    // Embeds store
    const EMBEDS_STORE_NAME = "embeds";
    if (!db.objectStoreNames.contains(EMBEDS_STORE_NAME)) {
      const embedsStore = db.createObjectStore(EMBEDS_STORE_NAME, {
        keyPath: "contentRef",
      });
      embedsStore.createIndex("type", "type", { unique: false });
      embedsStore.createIndex("createdAt", "createdAt", { unique: false });
      embedsStore.createIndex("app_id", "app_id", { unique: false });
      embedsStore.createIndex("skill_id", "skill_id", { unique: false });
      embedsStore.createIndex("hashed_chat_id", "hashed_chat_id", {
        unique: false,
      });
      console.debug("[ChatDatabase] Created embeds store for unified parsing");
    } else if (transaction) {
      const embedsStore = transaction.objectStore(EMBEDS_STORE_NAME);
      if (!embedsStore.indexNames.contains("app_id")) {
        embedsStore.createIndex("app_id", "app_id", { unique: false });
        console.debug("[ChatDatabase] Added app_id index to embeds store");
      }
      if (!embedsStore.indexNames.contains("skill_id")) {
        embedsStore.createIndex("skill_id", "skill_id", { unique: false });
        console.debug("[ChatDatabase] Added skill_id index to embeds store");
      }
      // Version 16: Add hashed_chat_id index for embed cleanup on chat deletion
      if (!embedsStore.indexNames.contains("hashed_chat_id")) {
        embedsStore.createIndex("hashed_chat_id", "hashed_chat_id", {
          unique: false,
        });
        console.debug(
          "[ChatDatabase] Added hashed_chat_id index to embeds store",
        );
      }
    }

    // Embed keys store
    const EMBED_KEYS_STORE_NAME = "embed_keys";
    if (!db.objectStoreNames.contains(EMBED_KEYS_STORE_NAME)) {
      const embedKeysStore = db.createObjectStore(EMBED_KEYS_STORE_NAME, {
        keyPath: "id",
      });
      embedKeysStore.createIndex("hashed_embed_id", "hashed_embed_id", {
        unique: false,
      });
      embedKeysStore.createIndex("key_type", "key_type", { unique: false });
      embedKeysStore.createIndex("hashed_chat_id", "hashed_chat_id", {
        unique: false,
      });
      console.debug(
        "[ChatDatabase] Created embed_keys store for wrapped key architecture",
      );
    }

    // App settings and memories store
    if (!db.objectStoreNames.contains(this.APP_SETTINGS_MEMORIES_STORE_NAME)) {
      const appSettingsStore = db.createObjectStore(
        this.APP_SETTINGS_MEMORIES_STORE_NAME,
        { keyPath: "id" },
      );
      appSettingsStore.createIndex("app_id", "app_id", { unique: false });
      appSettingsStore.createIndex("item_key", "item_key", { unique: false });
      appSettingsStore.createIndex("updated_at", "updated_at", {
        unique: false,
      });
      appSettingsStore.createIndex("item_version", "item_version", {
        unique: false,
      });
      console.debug("[ChatDatabase] Created app_settings_memories store");
    }

    // Pending OG metadata updates store
    if (!db.objectStoreNames.contains(this.PENDING_OG_METADATA_STORE_NAME)) {
      const ogMetadataStore = db.createObjectStore(
        this.PENDING_OG_METADATA_STORE_NAME,
        { keyPath: "update_id" },
      );
      ogMetadataStore.createIndex("chat_id", "chat_id", { unique: false });
      ogMetadataStore.createIndex("created_at", "created_at", {
        unique: false,
      });
      console.debug("[ChatDatabase] Created pending_og_metadata_updates store");
    }

    // Pending embed share updates store (v18)
    if (!db.objectStoreNames.contains(this.PENDING_EMBED_SHARE_STORE_NAME)) {
      const embedShareStore = db.createObjectStore(
        this.PENDING_EMBED_SHARE_STORE_NAME,
        { keyPath: "update_id" },
      );
      embedShareStore.createIndex("embed_id", "embed_id", { unique: false });
      embedShareStore.createIndex("created_at", "created_at", {
        unique: false,
      });
      console.debug("[ChatDatabase] Created pending_embed_share_updates store");
    }

    // Pending embed operations store (v19) - offline queue for embed encryption
    if (!db.objectStoreNames.contains(this.PENDING_EMBED_OPERATIONS_STORE_NAME)) {
      const pendingEmbedOpsStore = db.createObjectStore(
        this.PENDING_EMBED_OPERATIONS_STORE_NAME,
        { keyPath: "operation_id" },
      );
      pendingEmbedOpsStore.createIndex("embed_id", "embed_id", { unique: false });
      pendingEmbedOpsStore.createIndex("created_at", "created_at", {
        unique: false,
      });
      console.debug("[ChatDatabase] Created pending_embed_operations store");
    }

    // Note: app_settings_memories_actions store was removed in favor of system messages
    // The store may still exist in some databases but is no longer used

    // Embed data migration (v14)
    if (transaction && oldVersion < 14) {
      this.migrateEmbedData(transaction, EMBEDS_STORE_NAME);
    }
  }

  /**
   * Migrate messages from Chat.messages to separate messages store (v6)
   */
  private migrateMessagesFromChats(transaction: IDBTransaction): void {
    console.info(
      `[ChatDatabase] Migrating messages from chats to messages store`,
    );
    const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

    const cursorRequest = chatStore.openCursor();
    cursorRequest.onsuccess = (e) => {
      const cursor = (e.target as IDBRequest<IDBCursorWithValue>).result;
      if (cursor) {
        const chatData = cursor.value as ChatRecordWithMessages;
        if (chatData.messages && Array.isArray(chatData.messages)) {
          for (const message of chatData.messages) {
            if (!message.chat_id) message.chat_id = chatData.chat_id;
            messagesStore.put(message);
          }
          delete chatData.messages;
          cursor.update(chatData);
        }
        cursor.continue();
      } else {
        console.info("[ChatDatabase] Message migration completed.");
      }
    };
    cursorRequest.onerror = (e) => {
      console.error(
        "[ChatDatabase] CRITICAL: Error during message migration cursor:",
        (e.target as IDBRequest).error,
      );
    };
  }

  /**
   * Migrate message timestamps from timestamp to created_at (v7)
   */
  private migrateMessageTimestamps(transaction: IDBTransaction): void {
    console.info(
      `[ChatDatabase] Migrating message timestamps: renaming timestamp to created_at`,
    );
    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
    const cursorRequest = messagesStore.openCursor();
    cursorRequest.onsuccess = (e) => {
      const cursor = (e.target as IDBRequest<IDBCursorWithValue | null>)
        ?.result;
      if (cursor) {
        const message = cursor.value as MessageRecordWithTimestamp;
        if (message.timestamp !== undefined) {
          message.created_at = message.timestamp;
          delete message.timestamp;
          cursor.update(message);
        }
        cursor.continue();
      } else {
        console.info("[ChatDatabase] Message timestamp migration completed.");
      }
    };
    cursorRequest.onerror = (e) => {
      console.error(
        "[ChatDatabase] CRITICAL: Error during message timestamp migration cursor:",
        (e.target as IDBRequest).error,
      );
    };
  }

  /**
   * Migrate embed data from JSON string to separate fields (v14)
   */
  private migrateEmbedData(
    transaction: IDBTransaction,
    embedsStoreName: string,
  ): void {
    console.info(
      `[ChatDatabase] Migrating embeds: converting JSON string to separate fields`,
    );
    const embedsStore = transaction.objectStore(embedsStoreName);
    const cursorRequest = embedsStore.openCursor();
    let migratedCount = 0;
    let skippedCount = 0;

    cursorRequest.onsuccess = (e) => {
      const cursor = (e.target as IDBRequest<IDBCursorWithValue | null>)
        ?.result;
      if (cursor) {
        const entry = cursor.value as EmbedMigrationRecord;

        const needsMigration =
          entry.data &&
          typeof entry.data === "string" &&
          (entry.data.trim().startsWith("{") ||
            entry.data.trim().startsWith("[")) &&
          !entry.encrypted_content;

        if (needsMigration) {
          try {
            const parsedData = JSON.parse(
              entry.data,
            ) as Partial<EmbedMigrationRecord> & {
              content?: unknown;
              type?: unknown;
              text_preview?: unknown;
            };
            const parsedContent =
              typeof parsedData.content === "string"
                ? parsedData.content
                : undefined;
            const parsedType =
              typeof parsedData.type === "string" ? parsedData.type : undefined;
            const parsedTextPreview =
              typeof parsedData.text_preview === "string"
                ? parsedData.text_preview
                : undefined;

            if (parsedData.createdAt !== undefined)
              entry.createdAt = parsedData.createdAt;
            if (parsedData.updatedAt !== undefined)
              entry.updatedAt = parsedData.updatedAt;

            entry.embed_id = parsedData.embed_id || entry.embed_id;
            entry.encrypted_content =
              parsedData.encrypted_content || parsedContent;
            entry.encrypted_type = parsedData.encrypted_type || parsedType;
            entry.encrypted_text_preview =
              parsedData.encrypted_text_preview || parsedTextPreview;
            entry.status = parsedData.status || entry.status;
            entry.hashed_chat_id = parsedData.hashed_chat_id;
            entry.hashed_message_id = parsedData.hashed_message_id;
            entry.hashed_task_id = parsedData.hashed_task_id;
            entry.hashed_user_id = parsedData.hashed_user_id;
            entry.embed_ids = parsedData.embed_ids;
            entry.parent_embed_id = parsedData.parent_embed_id;
            entry.version_number = parsedData.version_number;
            entry.file_path = parsedData.file_path;
            entry.content_hash = parsedData.content_hash;
            entry.text_length_chars = parsedData.text_length_chars;
            entry.is_private = parsedData.is_private ?? false;
            entry.is_shared = parsedData.is_shared ?? false;

            cursor.update(entry);
            migratedCount++;

            if (migratedCount % 10 === 0) {
              console.debug(
                `[ChatDatabase] Migrated ${migratedCount} embeds...`,
              );
            }
          } catch (parseError) {
            console.warn(
              `[ChatDatabase] Failed to parse embed data for ${entry.contentRef}:`,
              parseError,
            );
            skippedCount++;
          }
        } else {
          skippedCount++;
        }

        cursor.continue();
      } else {
        console.info(
          `[ChatDatabase] Embed migration completed. Migrated: ${migratedCount}, Skipped: ${skippedCount}`,
        );
      }
    };

    cursorRequest.onerror = (e) => {
      console.error(
        "[ChatDatabase] CRITICAL: Error during embed migration cursor:",
        (e.target as IDBRequest).error,
      );
    };
  }

  // ============================================================================
  // TRANSACTION MANAGEMENT
  // ============================================================================

  /**
   * Creates a new transaction.
   */
  public async getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode,
  ): Promise<IDBTransaction> {
    await this.init();
    if (!this.db) {
      console.error(
        "[ChatDatabase] getTransaction called but DB is still null after init.",
      );
      throw new Error("Database not initialized despite awaiting init()");
    }
    return this.db.transaction(storeNames, mode);
  }

  // ============================================================================
  // CHAT CRUD OPERATIONS (delegated to chatCrudOperations.ts)
  // ============================================================================

  async addChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
    return chatCrudOps.addChat(this, chat, transaction);
  }

  async getAllChats(transaction?: IDBTransaction): Promise<Chat[]> {
    return chatCrudOps.getAllChats(this, transaction);
  }

  async getChat(
    chat_id: string,
    transaction?: IDBTransaction,
  ): Promise<Chat | null> {
    return chatCrudOps.getChat(this, chat_id, transaction);
  }

  async saveCurrentUserChatDraft(
    chat_id: string,
    draft_content: string | null,
    draft_preview: string | null = null,
  ): Promise<Chat | null> {
    return chatCrudOps.saveCurrentUserChatDraft(
      this,
      chat_id,
      draft_content,
      draft_preview,
    );
  }

  async createNewChatWithCurrentUserDraft(
    draft_content: string,
    draft_preview: string | null = null,
  ): Promise<Chat> {
    return chatCrudOps.createNewChatWithCurrentUserDraft(
      this,
      draft_content,
      draft_preview,
    );
  }

  async clearCurrentUserChatDraft(chat_id: string): Promise<Chat | null> {
    return chatCrudOps.clearCurrentUserChatDraft(this, chat_id);
  }

  async deleteChat(
    chat_id: string,
    transaction?: IDBTransaction,
  ): Promise<{ deletedEmbedIds: string[] }> {
    return chatCrudOps.deleteChat(this, chat_id, transaction);
  }

  async updateChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
    return this.addChat(chat, transaction);
  }

  async addOrUpdateChatWithFullData(
    chatData: Chat,
    messages: Message[] = [],
    transaction?: IDBTransaction,
  ): Promise<void> {
    return chatCrudOps.addOrUpdateChatWithFullData(
      this,
      chatData,
      messages,
      transaction,
      (msg, tx) => this.saveMessage(msg, tx),
    );
  }

  // ============================================================================
  // MESSAGE OPERATIONS (delegated to messageOperations.ts)
  // ============================================================================

  async saveMessage(
    message: Message,
    transaction?: IDBTransaction,
  ): Promise<void> {
    return messageOps.saveMessage(this, message, transaction);
  }

  async batchSaveMessages(messages: Message[]): Promise<void> {
    return messageOps.batchSaveMessages(this, messages);
  }

  async getMessagesForChat(
    chat_id: string,
    transaction?: IDBTransaction,
  ): Promise<Message[]> {
    return messageOps.getMessagesForChat(this, chat_id, transaction);
  }

  async getMessage(
    message_id: string,
    transaction?: IDBTransaction,
  ): Promise<Message | null> {
    return messageOps.getMessage(this, message_id, transaction);
  }

  async getLastMessageForChat(
    chat_id: string,
    transaction?: IDBTransaction,
  ): Promise<Message | null> {
    return messageOps.getLastMessageForChat(this, chat_id, transaction);
  }

  async getAllMessages(duringInit: boolean = false): Promise<Message[]> {
    return messageOps.getAllMessages(this, duringInit);
  }

  async deleteMessage(
    message_id: string,
    transaction?: IDBTransaction,
  ): Promise<void> {
    return messageOps.deleteMessage(this, message_id, transaction);
  }

  async cleanupDuplicateMessages(): Promise<void> {
    return messageOps.cleanupDuplicateMessages(this);
  }

  // ============================================================================
  // BATCH OPERATIONS
  // ============================================================================

  /**
   * Performs batch updates and deletions for chats and messages within a single transaction.
   */
  batchProcessChatData(
    chatsToUpdate: Array<Chat>,
    messagesToSave: Array<Message>,
    chatIdsToDelete: string[],
    messageIdsToDelete: string[],
    transaction: IDBTransaction,
  ): Promise<void> {
    console.debug(
      `[ChatDatabase] Batch processing: ${chatsToUpdate.length} chat updates, ${messagesToSave.length} message saves, ${chatIdsToDelete.length} chat deletions, ${messageIdsToDelete.length} message deletions.`,
    );

    const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

    // Use Promise<unknown> to accommodate different return types (void, { deletedEmbedIds })
    const promises: Promise<unknown>[] = [];

    // Process chat updates
    chatsToUpdate.forEach((chatToUpdate) => {
      const chatMetadata: ChatRecordWithMessages = { ...chatToUpdate };
      delete chatMetadata.messages;
      const createdAtValue = chatMetadata.created_at;
      if (typeof createdAtValue === "string" || isDateValue(createdAtValue)) {
        chatMetadata.created_at = Math.floor(
          new Date(createdAtValue).getTime() / 1000,
        );
      }
      const updatedAtValue = chatMetadata.updated_at;
      if (typeof updatedAtValue === "string" || isDateValue(updatedAtValue)) {
        chatMetadata.updated_at = Math.floor(
          new Date(updatedAtValue).getTime() / 1000,
        );
      }
      if (chatMetadata.encrypted_draft_md === undefined)
        chatMetadata.encrypted_draft_md = null;
      if (chatMetadata.draft_v === undefined) chatMetadata.draft_v = 0;

      promises.push(
        new Promise<void>((resolve, reject) => {
          const request = chatStore.put(chatMetadata);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        }),
      );
    });

    // Process message saves/updates
    messagesToSave.forEach((message) => {
      promises.push(this.saveMessage(message, transaction));
    });

    // Process chat deletions (which includes their messages)
    chatIdsToDelete.forEach((chat_id) => {
      promises.push(this.deleteChat(chat_id, transaction));
    });

    // Process specific message deletions
    messageIdsToDelete.forEach((message_id) => {
      promises.push(
        new Promise<void>((resolve, reject) => {
          const request = messagesStore.delete(message_id);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        }),
      );
    });

    return Promise.all(promises).then(() => {});
  }

  // ============================================================================
  // OFFLINE CHANGES OPERATIONS (delegated to offlineChangesAndUpdates.ts)
  // ============================================================================

  async addOfflineChange(
    change: OfflineChange,
    transaction?: IDBTransaction,
  ): Promise<void> {
    return offlineOps.addOfflineChange(this, change, transaction);
  }

  async getOfflineChanges(
    transaction?: IDBTransaction,
  ): Promise<OfflineChange[]> {
    return offlineOps.getOfflineChanges(this, transaction);
  }

  async deleteOfflineChange(
    change_id: string,
    transaction?: IDBTransaction,
  ): Promise<void> {
    return offlineOps.deleteOfflineChange(this, change_id, transaction);
  }

  // ============================================================================
  // CHAT UPDATE OPERATIONS (delegated to offlineChangesAndUpdates.ts)
  // ============================================================================

  async updateChatComponentVersion(
    chat_id: string,
    component: keyof ChatComponentVersions,
    version: number,
  ): Promise<void> {
    return offlineOps.updateChatComponentVersion(
      this,
      chat_id,
      component,
      version,
    );
  }

  async updateChatLastEditedTimestamp(
    chat_id: string,
    timestamp: number,
  ): Promise<void> {
    return offlineOps.updateChatLastEditedTimestamp(this, chat_id, timestamp);
  }

  async updateChatScrollPosition(
    chat_id: string,
    message_id: string,
  ): Promise<void> {
    return offlineOps.updateChatScrollPosition(this, chat_id, message_id);
  }

  async updateChatReadStatus(
    chat_id: string,
    unread_count: number,
  ): Promise<void> {
    return offlineOps.updateChatReadStatus(this, chat_id, unread_count);
  }

  // ============================================================================
  // DATA CLEARING AND DATABASE MANAGEMENT
  // ============================================================================

  async clearAllChatData(): Promise<void> {
    await this.init();
    console.debug(
      "[ChatDatabase] Clearing all chat data (chats, messages, pending_sync_changes).",
    );
    if (!this.db) {
      console.warn(
        "[ChatDatabase] Database not initialized after init(), skipping clear.",
      );
      return Promise.resolve();
    }

    const storesToClear = [
      this.CHATS_STORE_NAME,
      this.MESSAGES_STORE_NAME,
      this.OFFLINE_CHANGES_STORE_NAME,
    ];

    const transaction = await this.getTransaction(storesToClear, "readwrite");
    return new Promise((resolve, reject) => {
      transaction.oncomplete = () => {
        console.debug(
          "[ChatDatabase] All chat data stores cleared successfully.",
        );
        resolve();
      };
      transaction.onerror = () => {
        console.error(
          "[ChatDatabase] Error clearing chat data stores:",
          transaction.error,
        );
        reject(transaction.error);
      };

      storesToClear.forEach((storeName) => {
        if (this.db?.objectStoreNames.contains(storeName)) {
          const store = transaction.objectStore(storeName);
          store.clear();
        } else {
          console.warn(
            `[ChatDatabase] Store ${storeName} not found during clearAllChatData. Skipping.`,
          );
        }
      });
    });
  }

  /**
   * Deletes the IndexedDB database.
   */
  async deleteDatabase(): Promise<void> {
    console.debug(
      `[ChatDatabase] Attempting to delete database: ${this.DB_NAME}`,
    );

    this.isDeleting = true;

    return new Promise((resolve, reject) => {
      if (this.db) {
        this.db.close();
        this.db = null;
        console.debug(
          `[ChatDatabase] Database connection closed for ${this.DB_NAME}.`,
        );
      }
      this.initializationPromise = null;

      setTimeout(() => {
        const request = indexedDB.deleteDatabase(this.DB_NAME);

        request.onsuccess = () => {
          console.debug(
            `[ChatDatabase] Database ${this.DB_NAME} deleted successfully.`,
          );
          this.isDeleting = false;

          // Clear localStorage markers used for orphaned database detection
          if (typeof localStorage !== "undefined") {
            localStorage.removeItem("openmates_chats_db_initialized");
            localStorage.removeItem("openmates_needs_cleanup");
            console.debug(
              "[ChatDatabase] Cleared localStorage markers after database deletion",
            );
          }

          resolve();
        };

        request.onerror = (event) => {
          console.error(
            `[ChatDatabase] Error deleting database ${this.DB_NAME}:`,
            (event.target as IDBOpenDBRequest).error,
          );
          this.isDeleting = false;
          reject((event.target as IDBOpenDBRequest).error);
        };

        request.onblocked = (event) => {
          console.warn(
            `[ChatDatabase] Deletion of database ${this.DB_NAME} is waiting for other connections to close.`,
            event,
          );
        };
      }, 100);
    });
  }

  // ============================================================================
  // CHAT KEY MANAGEMENT (delegated to chatKeyManagement.ts)
  // ============================================================================

  public getChatKey(chatId: string): Uint8Array | null {
    return chatKeyManagementOps.getChatKey(this, chatId);
  }

  public setChatKey(chatId: string, chatKey: Uint8Array): void {
    chatKeyManagementOps.setChatKey(this, chatId, chatKey);
  }

  public async loadChatKeysFromDatabase(): Promise<void> {
    return chatKeyManagementOps.loadChatKeysFromDatabase(this);
  }

  public clearChatKey(chatId: string): void {
    chatKeyManagementOps.clearChatKey(this, chatId);
  }

  public clearAllChatKeys(): void {
    chatKeyManagementOps.clearAllChatKeys(this);
  }

  /**
   * Load shared chat keys from IndexedDB into memory cache.
   *
   * This enables shared chats to survive page reloads for unauthenticated users.
   * Shared chat keys are stored separately from regular chat keys because:
   * - Regular chat keys are wrapped with the user's master key (requires authentication)
   * - Shared chat keys are stored as raw key bytes (no master key for unauthenticated users)
   *
   * The keys are loaded into the same chatKeys Map used for regular chats,
   * allowing seamless decryption of both owned and shared chats.
   */
  public async loadSharedChatKeysFromStorage(): Promise<void> {
    try {
      const { getAllSharedChatKeys } = await import("./sharedChatKeyStorage");
      const sharedKeys = await getAllSharedChatKeys();

      if (sharedKeys.size > 0) {
        // Merge shared keys into the chat keys cache
        // Don't overwrite existing keys (from master key decryption)
        let loadedCount = 0;
        // Use Array.from() for compatibility with older TypeScript targets
        const entries = Array.from(sharedKeys.entries());
        for (const [chatId, keyBytes] of entries) {
          if (!this.chatKeys.has(chatId)) {
            this.chatKeys.set(chatId, keyBytes);
            loadedCount++;
          }
        }
        console.debug(
          `[ChatDatabase] Loaded ${loadedCount} shared chat keys from storage`,
        );
      }
    } catch (error) {
      // Non-critical: shared key storage might not exist yet (first visit)
      console.debug(
        "[ChatDatabase] Could not load shared chat keys (may not exist yet):",
        error,
      );
    }
  }

  public getOrGenerateChatKey(chatId: string): Uint8Array {
    return chatKeyManagementOps.getOrGenerateChatKey(this, chatId);
  }

  public async encryptMessageFields(
    message: Message,
    chatId: string,
  ): Promise<Message> {
    return chatKeyManagementOps.encryptMessageFields(this, message, chatId);
  }

  public async getEncryptedFields(
    message: Message,
    chatId: string,
  ): Promise<{
    encrypted_content?: string;
    encrypted_sender_name?: string;
    encrypted_category?: string;
    encrypted_model_name?: string;
    encrypted_thinking_content?: string;
    encrypted_thinking_signature?: string;
    encrypted_pii_mappings?: string;
  }> {
    return chatKeyManagementOps.getEncryptedFields(this, message, chatId);
  }

  public async getEncryptedChatKey(chatId: string): Promise<string | null> {
    return chatKeyManagementOps.getEncryptedChatKey(this, chatId);
  }

  public async decryptMessageFields(
    message: Message,
    chatId: string,
  ): Promise<Message> {
    return chatKeyManagementOps.decryptMessageFields(this, message, chatId);
  }

  // ============================================================================
  // NEW CHAT SUGGESTIONS (delegated to newChatSuggestions.ts)
  // ============================================================================

  async saveNewChatSuggestions(
    suggestions: string[],
    chatId: string,
  ): Promise<void> {
    return newChatSuggestionsOps.saveNewChatSuggestions(
      this,
      suggestions,
      chatId,
    );
  }

  async saveEncryptedNewChatSuggestions(
    suggestions: NewChatSuggestion[] | string[],
    chatId: string,
  ): Promise<void> {
    return newChatSuggestionsOps.saveEncryptedNewChatSuggestions(
      this,
      suggestions,
      chatId,
    );
  }

  async getAllNewChatSuggestions(
    includeHidden: boolean = false,
  ): Promise<NewChatSuggestion[]> {
    return newChatSuggestionsOps.getAllNewChatSuggestions(this, includeHidden);
  }

  async getRandomNewChatSuggestions(count: number = 3): Promise<string[]> {
    return newChatSuggestionsOps.getRandomNewChatSuggestions(this, count);
  }

  async deleteNewChatSuggestionByText(
    suggestionText: string,
  ): Promise<boolean> {
    return newChatSuggestionsOps.deleteNewChatSuggestionByText(
      this,
      suggestionText,
    );
  }

  async deleteNewChatSuggestionById(suggestionId: string): Promise<boolean> {
    return newChatSuggestionsOps.deleteNewChatSuggestionById(
      this,
      suggestionId,
    );
  }

  async deleteNewChatSuggestionByEncrypted(
    encryptedSuggestion: string,
  ): Promise<boolean> {
    return newChatSuggestionsOps.deleteNewChatSuggestionByEncrypted(
      this,
      encryptedSuggestion,
    );
  }

  async hideNewChatSuggestionsForChat(chatId: string): Promise<void> {
    return newChatSuggestionsOps.hideNewChatSuggestionsForChat(this, chatId);
  }

  async unhideNewChatSuggestionsForChat(chatId: string): Promise<void> {
    return newChatSuggestionsOps.unhideNewChatSuggestionsForChat(this, chatId);
  }

  // ============================================================================
  // APP SETTINGS AND MEMORIES (delegated to appSettingsMemories.ts)
  // ============================================================================

  async storeAppSettingsMemoriesEntries(
    entries: appSettingsMemoriesOps.AppSettingsMemoriesEntry[],
  ): Promise<void> {
    return appSettingsMemoriesOps.storeAppSettingsMemoriesEntries(
      this,
      entries,
    );
  }

  async getAppSettingsMemoriesEntry(
    entryId: string,
  ): Promise<appSettingsMemoriesOps.AppSettingsMemoriesEntry | null> {
    return appSettingsMemoriesOps.getAppSettingsMemoriesEntry(this, entryId);
  }

  async getAllAppSettingsMemoriesEntries(): Promise<
    appSettingsMemoriesOps.AppSettingsMemoriesEntry[]
  > {
    return appSettingsMemoriesOps.getAllAppSettingsMemoriesEntries(this);
  }

  async getAppSettingsMemoriesEntriesByApp(
    appId: string,
  ): Promise<appSettingsMemoriesOps.AppSettingsMemoriesEntry[]> {
    return appSettingsMemoriesOps.getAppSettingsMemoriesEntriesByApp(
      this,
      appId,
    );
  }

  async deleteAppSettingsMemoriesEntry(entryId: string): Promise<boolean> {
    return appSettingsMemoriesOps.deleteAppSettingsMemoriesEntry(this, entryId);
  }

  async deleteAppSettingsMemoriesEntriesByApp(appId: string): Promise<number> {
    return appSettingsMemoriesOps.deleteAppSettingsMemoriesEntriesByApp(
      this,
      appId,
    );
  }

  /**
   * Get metadata keys for all app settings/memories.
   * Returns array of unique keys in "app_id-item_type" format.
   * Used to tell server what app settings/memories exist without sending content.
   */
  async getAppSettingsMemoriesMetadataKeys(): Promise<string[]> {
    return appSettingsMemoriesOps.getAppSettingsMemoriesMetadataKeys(this);
  }

  /**
   * Get entry counts per app_id-item_type combination.
   * Used to show counts in permission dialog (e.g., "Favorite tech (6 entries)").
   */
  async getAppSettingsMemoriesEntryCounts(): Promise<Map<string, number>> {
    return appSettingsMemoriesOps.getAppSettingsMemoriesEntryCounts(this);
  }

  /**
   * Get all entries for a specific app_id-item_type combination.
   * Used to retrieve entries when user confirms sharing with AI.
   */
  async getAppSettingsMemoriesEntriesByAppAndType(
    appId: string,
    itemType: string,
  ): Promise<appSettingsMemoriesOps.AppSettingsMemoriesEntry[]> {
    return appSettingsMemoriesOps.getAppSettingsMemoriesEntriesByAppAndType(
      this,
      appId,
      itemType,
    );
  }

  // ============================================================================
  // APP SETTINGS MEMORIES ACTIONS (Included/Rejected tracking)
  // ============================================================================

  // ============================================================================
  // PENDING EMBED OPERATIONS (offline queue for embed encryption)
  // ============================================================================

  /**
   * Add a pending embed operation to the offline queue.
   * Called when the WebSocket is disconnected during embed encryption.
   */
  async addPendingEmbedOperation(operation: PendingEmbedOperation): Promise<void> {
    await this.init();
    const transaction = await this.getTransaction(
      this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      "readwrite",
    );
    return new Promise((resolve, reject) => {
      const store = transaction.objectStore(
        this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      );
      const request = store.put(operation);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get all pending embed operations from the offline queue.
   */
  async getPendingEmbedOperations(): Promise<PendingEmbedOperation[]> {
    await this.init();
    const transaction = await this.getTransaction(
      this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      "readonly",
    );
    return new Promise((resolve, reject) => {
      const store = transaction.objectStore(
        this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      );
      const request = store.getAll();
      request.onsuccess = () =>
        resolve((request.result as PendingEmbedOperation[]) || []);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Remove a single pending embed operation by its operation_id.
   */
  async removePendingEmbedOperation(operationId: string): Promise<void> {
    await this.init();
    const transaction = await this.getTransaction(
      this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      "readwrite",
    );
    return new Promise((resolve, reject) => {
      const store = transaction.objectStore(
        this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      );
      const request = store.delete(operationId);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Clear all pending embed operations (e.g., on logout).
   */
  async clearPendingEmbedOperations(): Promise<void> {
    await this.init();
    const transaction = await this.getTransaction(
      this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      "readwrite",
    );
    return new Promise((resolve, reject) => {
      const store = transaction.objectStore(
        this.PENDING_EMBED_OPERATIONS_STORE_NAME,
      );
      const request = store.clear();
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }
}

export const chatDB = new ChatDatabase();
