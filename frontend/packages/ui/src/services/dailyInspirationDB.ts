// frontend/packages/ui/src/services/dailyInspirationDB.ts
//
// Client-side persistence layer for personalised Daily Inspiration entries.
//
// ARCHITECTURE:
// - Inspirations are stored encrypted in IndexedDB (master-key AES-GCM 256)
// - They are also synced to Directus via REST API for cross-device recovery
// - On page load / login, we restore from IndexedDB first (fastest) and fall
//   back to the API (cross-device / fresh device)
//
// ENCRYPTION STRATEGY:
// - Content fields (phrase, assistant_response, title, category, icon) are
//   encrypted with encryptWithMasterKey() before storage
// - The IndexedDB record stores both cleartext metadata (inspiration_id,
//   generated_at, content_type, embed_id, is_opened, opened_chat_id) and
//   encrypted blobs for the actual text content
// - The API payload mirrors the IndexedDB record — only encrypted blobs
//   are sent to the server, so the server never sees cleartext content
//
// TTL: Inspirations older than 3 days are pruned from IndexedDB on load.
// The API stores up to 10 (about 3 days at 3/day).

import { chatDB } from "./db";
import type { DailyInspiration } from "../stores/dailyInspirationStore";
import { getApiEndpoint } from "../config/api";

const LOG_PREFIX = "[dailyInspirationDB]";

/** How long personalised inspirations are kept locally (72 hours in ms) */
const INSPIRATION_TTL_MS = 72 * 60 * 60 * 1000;

// ─── IndexedDB record shape ───────────────────────────────────────────────────

/**
 * The shape of a record stored in the `daily_inspirations` IndexedDB object store.
 * Content fields are encrypted; structural fields are cleartext for indexing.
 */
export interface StoredDailyInspiration {
  /** Client-generated UUID — primary key */
  inspiration_id: string;
  /** UUID of the associated video embed, if any */
  embed_id: string | null;
  /** Unix timestamp (seconds) when generated — used for TTL and ordering */
  generated_at: number;
  /** Content type (currently always "video") */
  content_type: string;
  /** Whether the user has already started a chat from this inspiration */
  is_opened: boolean;
  /** Hashed chat ID created from this inspiration (or null) */
  opened_chat_id: string | null;
  // ─── Encrypted fields (base64 AES-GCM blobs) ─────────────────────────────
  encrypted_phrase: string;
  encrypted_assistant_response: string;
  encrypted_title: string;
  encrypted_category: string;
  encrypted_icon: string | null;
  // ─── Cleartext cached decrypted values (for in-memory use, NOT synced) ────
  // Populated after decryption; never written to server.
  _phrase?: string;
  _category?: string;
}

// ─── Write: save inspirations to IndexedDB ───────────────────────────────────

/**
 * Encrypt and save a single inspiration to IndexedDB.
 * Returns the StoredDailyInspiration on success, or null if encryption fails.
 */
export async function saveInspirationToIndexedDB(
  inspiration: DailyInspiration,
  assistantResponse: string,
): Promise<StoredDailyInspiration | null> {
  try {
    await chatDB.init();
    if (!chatDB.db) {
      console.error(`${LOG_PREFIX} DB not initialized`);
      return null;
    }

    const { encryptWithMasterKey } = await import("./cryptoService");

    // Encrypt the text content fields
    const [
      encrypted_phrase,
      encrypted_assistant_response,
      encrypted_title,
      encrypted_category,
    ] = await Promise.all([
      encryptWithMasterKey(inspiration.phrase),
      encryptWithMasterKey(assistantResponse),
      encryptWithMasterKey(inspiration.phrase), // title = phrase for inspirations
      encryptWithMasterKey(inspiration.category),
    ]);

    if (
      !encrypted_phrase ||
      !encrypted_assistant_response ||
      !encrypted_title ||
      !encrypted_category
    ) {
      console.error(
        `${LOG_PREFIX} Encryption failed for inspiration ${inspiration.inspiration_id}`,
      );
      return null;
    }

    const record: StoredDailyInspiration = {
      inspiration_id: inspiration.inspiration_id,
      embed_id: inspiration.embed_id ?? null,
      generated_at: inspiration.generated_at,
      content_type: inspiration.content_type,
      is_opened: inspiration.is_opened ?? false,
      opened_chat_id: inspiration.opened_chat_id ?? null,
      encrypted_phrase,
      encrypted_assistant_response,
      encrypted_title,
      encrypted_category,
      encrypted_icon: null, // icon not currently used
    };

    await new Promise<void>((resolve, reject) => {
      const tx = chatDB.db!.transaction(
        [chatDB.DAILY_INSPIRATIONS_STORE_NAME],
        "readwrite",
      );
      const store = tx.objectStore(chatDB.DAILY_INSPIRATIONS_STORE_NAME);
      const req = store.put(record);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });

    console.debug(
      `${LOG_PREFIX} Saved inspiration ${inspiration.inspiration_id} to IndexedDB`,
    );
    return record;
  } catch (error) {
    console.error(
      `${LOG_PREFIX} Failed to save inspiration to IndexedDB:`,
      error,
    );
    return null;
  }
}

// ─── Read: load inspirations from IndexedDB ───────────────────────────────────

/**
 * Load and decrypt all stored inspirations from IndexedDB.
 * Automatically prunes entries older than INSPIRATION_TTL_MS.
 * Returns inspirations sorted newest-first.
 */
export async function loadInspirationsFromIndexedDB(): Promise<
  DailyInspiration[]
> {
  try {
    await chatDB.init();
    if (!chatDB.db) {
      console.error(`${LOG_PREFIX} DB not initialized`);
      return [];
    }

    const now = Date.now();
    const cutoffSeconds = Math.floor((now - INSPIRATION_TTL_MS) / 1000);

    // Read all records
    const records = await new Promise<StoredDailyInspiration[]>(
      (resolve, reject) => {
        const tx = chatDB.db!.transaction(
          [chatDB.DAILY_INSPIRATIONS_STORE_NAME],
          "readonly",
        );
        const store = tx.objectStore(chatDB.DAILY_INSPIRATIONS_STORE_NAME);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result as StoredDailyInspiration[]);
        req.onerror = () => reject(req.error);
      },
    );

    if (records.length === 0) return [];

    // Separate stale from fresh records
    const stale = records.filter((r) => r.generated_at < cutoffSeconds);
    const fresh = records.filter((r) => r.generated_at >= cutoffSeconds);

    // Prune stale records asynchronously (non-blocking)
    if (stale.length > 0) {
      pruneStaleInspirations(stale.map((r) => r.inspiration_id)).catch(
        (err) => {
          console.warn(
            `${LOG_PREFIX} Failed to prune stale inspirations:`,
            err,
          );
        },
      );
    }

    if (fresh.length === 0) return [];

    // Decrypt fresh records
    const { decryptWithMasterKey } = await import("./cryptoService");

    const decrypted: DailyInspiration[] = [];
    for (const record of fresh) {
      try {
        const [phrase, category] = await Promise.all([
          decryptWithMasterKey(record.encrypted_phrase),
          decryptWithMasterKey(record.encrypted_category),
        ]);

        if (!phrase || !category) {
          console.warn(
            `${LOG_PREFIX} Decryption failed for inspiration ${record.inspiration_id} — skipping`,
          );
          continue;
        }

        // Reconstruct DailyInspiration without the video metadata
        // (video metadata is ephemeral from the server; we don't store it locally
        //  because it's not needed to re-display the banner — only the phrase/category matters)
        decrypted.push({
          inspiration_id: record.inspiration_id,
          phrase,
          category,
          content_type: record.content_type,
          video: null, // Not persisted locally — re-fetched from server on next WS connect
          generated_at: record.generated_at,
          embed_id: record.embed_id,
          is_opened: record.is_opened,
          opened_chat_id: record.opened_chat_id,
        });
      } catch (decryptErr) {
        console.error(
          `${LOG_PREFIX} Error decrypting inspiration ${record.inspiration_id}:`,
          decryptErr,
        );
      }
    }

    // Sort newest first
    decrypted.sort((a, b) => b.generated_at - a.generated_at);

    console.debug(
      `${LOG_PREFIX} Loaded ${decrypted.length} inspirations from IndexedDB`,
    );
    return decrypted.slice(0, 3);
  } catch (error) {
    console.error(
      `${LOG_PREFIX} Failed to load inspirations from IndexedDB:`,
      error,
    );
    return [];
  }
}

// ─── Update: mark opened in IndexedDB ────────────────────────────────────────

/**
 * Mark a single inspiration as opened in IndexedDB.
 * Does NOT call the API — that is handled by the caller separately.
 */
export async function markInspirationOpenedInIndexedDB(
  inspirationId: string,
  openedChatId?: string,
): Promise<void> {
  try {
    await chatDB.init();
    if (!chatDB.db) {
      console.error(`${LOG_PREFIX} DB not initialized`);
      return;
    }

    await new Promise<void>((resolve, reject) => {
      const tx = chatDB.db!.transaction(
        [chatDB.DAILY_INSPIRATIONS_STORE_NAME],
        "readwrite",
      );
      const store = tx.objectStore(chatDB.DAILY_INSPIRATIONS_STORE_NAME);
      const getReq = store.get(inspirationId);

      getReq.onsuccess = () => {
        const record = getReq.result as StoredDailyInspiration | undefined;
        if (!record) {
          // Record not found — not an error (could be a default inspiration)
          console.debug(
            `${LOG_PREFIX} markOpened: inspiration ${inspirationId} not in IndexedDB (may be a default) — skipping`,
          );
          resolve();
          return;
        }

        record.is_opened = true;
        if (openedChatId) {
          record.opened_chat_id = openedChatId;
        }

        const putReq = store.put(record);
        putReq.onsuccess = () => resolve();
        putReq.onerror = () => reject(putReq.error);
      };

      getReq.onerror = () => reject(getReq.error);
    });

    console.debug(
      `${LOG_PREFIX} Marked inspiration ${inspirationId} as opened in IndexedDB`,
    );
  } catch (error) {
    console.error(
      `${LOG_PREFIX} Failed to mark inspiration as opened in IndexedDB:`,
      error,
    );
  }
}

// ─── Prune: delete stale records ─────────────────────────────────────────────

async function pruneStaleInspirations(ids: string[]): Promise<void> {
  if (!chatDB.db) return;
  await new Promise<void>((resolve, reject) => {
    const tx = chatDB.db!.transaction(
      [chatDB.DAILY_INSPIRATIONS_STORE_NAME],
      "readwrite",
    );
    const store = tx.objectStore(chatDB.DAILY_INSPIRATIONS_STORE_NAME);
    let pending = ids.length;
    if (pending === 0) {
      resolve();
      return;
    }
    for (const id of ids) {
      const req = store.delete(id);
      req.onsuccess = () => {
        pending--;
        if (pending === 0) resolve();
      };
      req.onerror = () => {
        pending--;
        if (pending === 0) resolve(); // Non-fatal
      };
    }
    tx.onerror = () => reject(tx.error);
  });
  console.debug(
    `${LOG_PREFIX} Pruned ${ids.length} stale inspiration(s) from IndexedDB`,
  );
}

// ─── API sync: persist to Directus ───────────────────────────────────────────

/**
 * POST /v1/daily-inspirations — sync encrypted inspirations to the server.
 *
 * Called after saving to IndexedDB to ensure cross-device recovery.
 * Failures are non-fatal (IndexedDB is the primary source of truth).
 *
 * @param records - The IndexedDB records to sync (already encrypted)
 */
export async function syncInspirationsToAPI(
  records: StoredDailyInspiration[],
): Promise<void> {
  if (records.length === 0) return;

  try {
    const url = getApiEndpoint("/v1/daily-inspirations");
    const body = {
      inspirations: records.map((r) => ({
        daily_inspiration_id: r.inspiration_id,
        embed_id: r.embed_id ?? null,
        encrypted_phrase: r.encrypted_phrase,
        encrypted_assistant_response: r.encrypted_assistant_response,
        encrypted_title: r.encrypted_title,
        encrypted_category: r.encrypted_category,
        encrypted_icon: r.encrypted_icon ?? null,
        is_opened: r.is_opened,
        opened_chat_id: r.opened_chat_id ?? null,
        generated_at: r.generated_at,
        content_type: r.content_type,
      })),
    };

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      console.error(
        `${LOG_PREFIX} API sync failed: ${response.status} ${response.statusText}`,
      );
      return;
    }

    const data = (await response.json()) as { stored: number; total: number };
    console.debug(
      `${LOG_PREFIX} API sync: stored ${data.stored}/${data.total} inspirations`,
    );
  } catch (error) {
    console.error(`${LOG_PREFIX} Failed to sync inspirations to API:`, error);
  }
}

/**
 * POST /v1/daily-inspirations/{id}/opened — notify server that user started a chat.
 * Failures are non-fatal.
 */
export async function markInspirationOpenedOnAPI(
  inspirationId: string,
  openedChatId?: string,
): Promise<void> {
  try {
    const url = getApiEndpoint(
      `/v1/daily-inspirations/${inspirationId}/opened`,
    );
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ opened_chat_id: openedChatId ?? null }),
    });

    if (!response.ok) {
      console.error(
        `${LOG_PREFIX} markOpened API call failed: ${response.status} ${response.statusText}`,
      );
    } else {
      console.debug(
        `${LOG_PREFIX} Marked inspiration ${inspirationId} as opened on API`,
      );
    }
  } catch (error) {
    console.error(
      `${LOG_PREFIX} Failed to call markOpened API for ${inspirationId}:`,
      error,
    );
  }
}

// ─── Login sync: restore from API to IndexedDB ───────────────────────────────

/**
 * GET /v1/daily-inspirations — fetch saved inspirations from Directus on login.
 *
 * Called during phased sync (phasedSyncComplete) when IndexedDB has no
 * personalised inspirations (fresh device or cleared browser data).
 *
 * Returns a list of decrypted DailyInspiration objects (newest first, max 3)
 * that the caller should push into the store.
 *
 * IMPORTANT: This should only be called when the user is authenticated
 * (auth cookie present) and IndexedDB is empty.
 */
export async function loadInspirationsFromAPI(): Promise<DailyInspiration[]> {
  try {
    const url = getApiEndpoint("/v1/daily-inspirations");
    const response = await fetch(url, {
      method: "GET",
      credentials: "include",
    });

    if (!response.ok) {
      if (response.status === 401) {
        // User not authenticated yet — skip silently
        console.debug(
          `${LOG_PREFIX} loadInspirationsFromAPI: not authenticated (401) — skipping`,
        );
      } else {
        console.error(
          `${LOG_PREFIX} loadInspirationsFromAPI failed: ${response.status}`,
        );
      }
      return [];
    }

    const data = (await response.json()) as {
      inspirations: Array<Record<string, unknown>>;
    };
    const apiRecords = data.inspirations || [];

    if (apiRecords.length === 0) {
      console.debug(`${LOG_PREFIX} No saved inspirations on server`);
      return [];
    }

    const { decryptWithMasterKey } = await import("./cryptoService");

    const decrypted: DailyInspiration[] = [];
    for (const record of apiRecords) {
      try {
        const encPhrase = record.encrypted_phrase as string;
        const encCategory = record.encrypted_category as string;
        const encAssistant = record.encrypted_assistant_response as string;
        const encTitle = record.encrypted_title as string;

        if (!encPhrase || !encCategory || !encAssistant || !encTitle) {
          console.warn(
            `${LOG_PREFIX} Skipping API inspiration with missing encrypted fields`,
          );
          continue;
        }

        const [phrase, category] = await Promise.all([
          decryptWithMasterKey(encPhrase),
          decryptWithMasterKey(encCategory),
        ]);

        if (!phrase || !category) {
          console.warn(
            `${LOG_PREFIX} Decryption failed for API inspiration — skipping`,
          );
          continue;
        }

        const inspiration: DailyInspiration = {
          inspiration_id: record.daily_inspiration_id as string,
          phrase,
          category,
          content_type: (record.content_type as string) || "video",
          video: null, // Not stored on server
          generated_at: record.generated_at as number,
          embed_id: (record.embed_id as string | null) ?? null,
          is_opened: (record.is_opened as boolean) ?? false,
          opened_chat_id: (record.opened_chat_id as string | null) ?? null,
        };

        decrypted.push(inspiration);

        // Also persist back to IndexedDB so next load is local
        const idbRecord: StoredDailyInspiration = {
          inspiration_id: inspiration.inspiration_id,
          embed_id: inspiration.embed_id ?? null,
          generated_at: inspiration.generated_at,
          content_type: inspiration.content_type,
          is_opened: inspiration.is_opened ?? false,
          opened_chat_id: inspiration.opened_chat_id ?? null,
          encrypted_phrase: encPhrase,
          encrypted_assistant_response: encAssistant,
          encrypted_title: encTitle,
          encrypted_category: encCategory,
          encrypted_icon: (record.encrypted_icon as string | null) ?? null,
        };

        // Save to IndexedDB (non-blocking, non-fatal)
        saveStoredInspirationToIndexedDB(idbRecord).catch((err) => {
          console.warn(
            `${LOG_PREFIX} Failed to cache API inspiration in IndexedDB:`,
            err,
          );
        });
      } catch (err) {
        console.error(`${LOG_PREFIX} Error processing API inspiration:`, err);
      }
    }

    decrypted.sort((a, b) => b.generated_at - a.generated_at);
    console.debug(
      `${LOG_PREFIX} Loaded ${decrypted.length} inspirations from API`,
    );
    return decrypted.slice(0, 3);
  } catch (error) {
    console.error(`${LOG_PREFIX} Failed to load inspirations from API:`, error);
    return [];
  }
}

// ─── Helper: save pre-encrypted record directly ───────────────────────────────

/**
 * Save a pre-encrypted IndexedDB record (from API sync) without re-encrypting.
 */
async function saveStoredInspirationToIndexedDB(
  record: StoredDailyInspiration,
): Promise<void> {
  await chatDB.init();
  if (!chatDB.db) return;

  await new Promise<void>((resolve, reject) => {
    const tx = chatDB.db!.transaction(
      [chatDB.DAILY_INSPIRATIONS_STORE_NAME],
      "readwrite",
    );
    const store = tx.objectStore(chatDB.DAILY_INSPIRATIONS_STORE_NAME);
    const req = store.put(record);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}
