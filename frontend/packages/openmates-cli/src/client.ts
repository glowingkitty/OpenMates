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
import { platform, release } from "node:os";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import qrcode from "qrcode-terminal";

import {
  decryptBundle,
  decryptWithAesGcmCombined,
  decryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  base64ToBytes,
  bytesToBase64,
  hashItemKey,
} from "./crypto.js";
import { OpenMatesHttpClient } from "./http.js";
import {
  type OpenMatesSession,
  type IncognitoHistoryItem,
  type SyncCache,
  type CachedChat,
  loadSession,
  saveSession,
  clearSession,
  loadIncognitoHistory,
  saveIncognitoHistory,
  clearIncognitoHistory,
  loadSyncCache,
  saveSyncCache,
  clearSyncCache,
  isSyncCacheFresh,
} from "./storage.js";
import { OpenMatesWsClient } from "./ws.js";
import type { MentionContext, AppInfo, MemoryEntryInfo } from "./mentions.js";
import { CHAT_MODELS } from "./mentions.js";
import type { EncryptedEmbed } from "./embedCreator.js";
import {
  generateChatShareBlob,
  generateEmbedShareBlob,
  deriveWebOrigin,
  buildChatShareUrl,
  buildEmbedShareUrl,
  type ShareDuration,
} from "./shareEncryption.js";

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
        enum: ["formal", "casual", "friendly", "professional"],
      },
      verbosity: { type: "string", enum: ["concise", "balanced", "detailed"] },
      notes: { type: "string" },
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
        enum: ["visual", "reading", "hands_on", "audio", "mixed"],
      },
      preference_strength: {
        type: "string",
        enum: ["strong", "moderate", "slight"],
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
        enum: ["active", "paused", "completed", "archived"],
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
        enum: ["local", "remote", "cloud", "mixed"],
      },
      ai_level: { type: "string", enum: ["minimal", "moderate", "extensive"] },
      input_style: {
        type: "string",
        enum: ["keyboard_only", "mixed", "voice_primary"],
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
  "health/appointments": {
    appId: "health",
    itemType: "appointments",
    entryType: "list",
    required: ["appointment_type", "date"],
    properties: {
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
          "condition",
          "allergy",
          "medication",
          "vaccination",
          "other",
        ],
      },
      name: { type: "string" },
      date: { type: "string" },
      details: { type: "string" },
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
  "mail/proton_bridge_connection": {
    appId: "mail",
    itemType: "proton_bridge_connection",
    entryType: "list",
    required: ["title"],
    properties: { title: { type: "string" }, description: { type: "string" } },
  },
  "maps/favorite_places": {
    appId: "maps",
    itemType: "favorite_places",
    entryType: "list",
    required: ["name"],
    properties: { name: { type: "string" }, address: { type: "string" } },
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
    properties: { method: { type: "string" } },
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
      year: { type: "number" },
      director: { type: "string" },
      rating: { type: "number" },
      tmdb_id: { type: "number" },
      notes: { type: "string" },
      genre: { type: "string" },
    },
  },
  "tv/watched_tv_shows": {
    appId: "tv",
    itemType: "watched_tv_shows",
    entryType: "list",
    required: ["title"],
    properties: {
      title: { type: "string" },
      year: { type: "number" },
      tmdb_id: { type: "number" },
      status: {
        type: "string",
        enum: ["watching", "completed", "dropped", "on_hold"],
      },
      seasons_watched: { type: "number" },
      latest_episode: { type: "string" },
      rating: { type: "number" },
      notes: { type: "string" },
      genre: { type: "string" },
    },
  },
  "tv/to_watch_list": {
    appId: "tv",
    itemType: "to_watch_list",
    entryType: "list",
    required: ["title", "type"],
    properties: {
      title: { type: "string" },
      year: { type: "number" },
      type: { type: "string", enum: ["movie", "tv_show"] },
      tmdb_id: { type: "number" },
      director: { type: "string" },
      priority: { type: "string", enum: ["high", "medium", "low"] },
      genre: { type: "string" },
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

interface ChatListItem {
  id: string;
  shortId: string;
  title: string | null;
  summary: string | null;
  updatedAt: number | null;
  category: string | null;
  mateName: string | null;
}

/** A single parameter extracted from the OpenAPI skill schema. */
export interface SkillParam {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
}

export interface ChatListPage {
  chats: ChatListItem[];
  total: number;
  page: number;
  limit: number;
  hasMore: boolean;
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
 * The optional `appId` and `skillId` are parsed from the `[app-skill]` prefix
 * (e.g. "[web-search] What's the weather today?" → appId="web", skillId="search").
 */
export interface DecryptedNewChatSuggestion {
  id: string;
  chatId: string | null;
  body: string;
  /** App ID if the suggestion has an [app-skill] or [app] prefix. */
  appId: string | null;
  /** Skill ID if the suggestion has an [app-skill] prefix. */
  skillId: string | null;
  createdAt: number;
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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_API_URL =
  process.env.OPENMATES_API_URL ?? "https://api.openmates.org";

/**
 * Derive the web app URL from the API URL so the pair token is always looked
 * up on the same backend the CLI created it on.
 * Override with OPENMATES_APP_URL when using a custom setup.
 */
export function deriveAppUrl(apiUrl: string): string {
  if (process.env.OPENMATES_APP_URL) {
    return process.env.OPENMATES_APP_URL.replace(/\/$/, "");
  }
  if (apiUrl.includes("api.dev.openmates.org")) {
    return "https://app.dev.openmates.org";
  }
  if (apiUrl.includes("api.openmates.org")) {
    return "https://openmates.org";
  }
  if (apiUrl.includes("localhost")) {
    return "http://localhost:5173";
  }
  return "https://openmates.org";
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
]);

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class OpenMatesClient {
  readonly apiUrl: string;
  private readonly session: OpenMatesSession | null;
  private readonly http: OpenMatesHttpClient;

  constructor(options: OpenMatesClientOptions = {}) {
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    const diskSession = options.session ?? this.getValidSessionFromDisk();
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

    saveSession(session);
  }

  async whoAmI(): Promise<Record<string, unknown>> {
    const session = this.requireSession();
    const response = await this.http.post<{
      success?: boolean;
      user?: Record<string, unknown>;
    }>(
      "/v1/auth/session",
      { session_id: session.sessionId },
      this.getCliRequestHeaders(),
    );
    if (!response.ok || !response.data.success) {
      throw new Error("Session is invalid. Please run `openmates login`.");
    }
    return response.data.user ?? {};
  }

  async logout(): Promise<void> {
    if (this.session) {
      await this.http
        .post("/v1/auth/logout", {}, this.getCliRequestHeaders())
        .catch(() => undefined);
    }
    clearSession();
    clearIncognitoHistory();
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

  /**
   * Build a slug → DecryptedEmbed index for all embeds in the sync cache.
   *
   * Child embeds store an `embed_ref` slug in their encrypted content (e.g.
   * "youtube.com-p3f", "marineinsight.com-wrP"). This method decrypts all
   * embeds and builds a map from slug to the decrypted embed, so the chat
   * renderer can resolve `[text](embed:slug)` and `[!](embed:slug)` refs.
   *
   * Mirrors the web app's embedStore.embedRefToIdIndex (in-memory only).
   */
  async buildEmbedRefIndex(): Promise<Map<string, DecryptedEmbed>> {
    const cache = await this.ensureSynced();
    const index = new Map<string, DecryptedEmbed>();

    for (const rawEmbed of cache.embeds) {
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
    const cache = await this.ensureSynced();
    const lower = idOrShort.toLowerCase();
    for (const chat of cache.chats) {
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

      // Parse the [app-skill] or [app] prefix from the suggestion body.
      // Mirrors parseSuggestion() in NewChatSuggestions.svelte.
      const { body, appId, skillId } = parseNewChatSuggestionText(plaintext);

      results.push({
        id: typeof raw.id === "string" ? raw.id : String(raw.id ?? ""),
        chatId: typeof raw.chat_id === "string" ? raw.chat_id : null,
        body,
        appId,
        skillId,
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
    const cache = await this.ensureSynced();
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
        return (parsed as unknown[]).filter(
          (s): s is string => typeof s === "string" && s.length > 0,
        );
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
    /** Encrypted file embeds to attach to the message (code, images, PDFs). */
    encryptedEmbeds?: EncryptedEmbed[];
  }): Promise<{
    chatId: string;
    assistant: string;
    category: string | null;
    modelName: string | null;
    mateName: string | null;
    /** Follow-up suggestions from post-processing (may be empty for incognito chats). */
    followUpSuggestions: string[];
  }> {
    const session = this.requireSession();

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

    const ws = this.makeWsClient(session);
    await ws.open();

    const messageId = randomUUID();
    const createdAt = Math.floor(Date.now() / 1000);
    const isNewChat = !params.chatId;
    // Mark this chat as active so the server streams incremental chunks
    // rather than sending a single background-completion event.
    ws.send("set_active_chat", { chat_id: chatId });

    // ── Phase 1: Plaintext message for AI processing ──
    // Mirrors: chatSyncServiceSenders.ts sendMessageToServer()
    const messagePayload: Record<string, unknown> = {
      chat_id: chatId,
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

    // For non-incognito chats, resolve or generate the chat key and include
    // the encrypted_chat_key in Phase 1 so the server can store it for sync.
    // Mirrors: chatSyncServiceSenders.ts sendEncryptedStoragePackage() key logic
    let chatKeyBytes: Uint8Array | null = null;
    let encryptedChatKey: string | null = null;

    if (!params.incognito) {
      const masterKey = this.getMasterKeyBytes();

      if (isNewChat) {
        // New chat — generate a fresh 32-byte AES-256 key
        chatKeyBytes = globalThis.crypto
          ? new Uint8Array(globalThis.crypto.getRandomValues(new Uint8Array(32)))
          : new Uint8Array(
              (await import("node:crypto")).webcrypto.getRandomValues(
                new Uint8Array(32),
              ),
            );
        // Encrypt the chat key with the master key for server storage
        encryptedChatKey = await encryptBytesWithAesGcm(
          chatKeyBytes,
          masterKey,
        );
        messagePayload.encrypted_chat_key = encryptedChatKey;
      } else {
        // Existing chat — decrypt the chat key from the sync cache
        const cache = await this.ensureSynced();
        const chat = cache.chats.find(
          (c) =>
            String(c.details.id ?? "") === chatId ||
            String(c.details.id ?? "").startsWith(chatId),
        );
        if (chat) {
          const encKey =
            typeof chat.details.encrypted_chat_key === "string"
              ? chat.details.encrypted_chat_key
              : null;
          if (encKey) {
            chatKeyBytes = await decryptBytesWithAesGcm(encKey, masterKey);
            encryptedChatKey = encKey;
          }
        }
      }
    }

    // Attach encrypted file embeds if present
    // Mirrors: chatSyncServiceSenders.ts encrypted_embeds array
    if (params.encryptedEmbeds && params.encryptedEmbeds.length > 0) {
      messagePayload.encrypted_embeds = params.encryptedEmbeds;
    }

    ws.send("chat_message_added", messagePayload);

    // ── Phase 2: Encrypted metadata for Directus persistence + cross-device sync ──
    // Mirrors: chatSyncServiceSenders.ts sendEncryptedStoragePackage()
    // Without this, the message is only cached for AI but never persisted to Directus,
    // so the web app and other devices cannot sync the message.
    if (!params.incognito && chatKeyBytes) {
      const encryptedContent = await encryptWithAesGcmCombined(
        params.message,
        chatKeyBytes,
      );
      const encryptedSenderName = await encryptWithAesGcmCombined(
        "User",
        chatKeyBytes,
      );

      const metadataPayload: Record<string, unknown> = {
        chat_id: chatId,
        message_id: messageId,
        encrypted_content: encryptedContent,
        encrypted_sender_name: encryptedSenderName,
        created_at: createdAt,
        encrypted_chat_key: encryptedChatKey,
        versions: {
          messages_v: 0,
          title_v: 0,
          last_edited_overall_timestamp: createdAt,
        },
      };

      ws.send("encrypted_chat_metadata", metadataPayload);
    }

    let assistant = "";
    let category: string | null = null;
    let modelName: string | null = null;
    let followUpSuggestions: string[] = [];
    const streamOpts = { onStream: params.onStream };

    if (params.incognito) {
      const history = loadIncognitoHistory();
      history.push({
        role: "user",
        content: params.message,
        createdAt: Date.now(),
      });
      try {
        const resp = await ws.collectAiResponse(messageId, chatId, streamOpts);
        assistant = resp.content;
        category = resp.category;
        modelName = resp.modelName;
        // Incognito chats are not post-processed — follow-up suggestions are not stored.
      } finally {
        ws.close();
      }
      history.push({
        role: "assistant",
        content: assistant,
        createdAt: Date.now(),
      });
      saveIncognitoHistory(history);
    } else {
      try {
        const resp = await ws.collectAiResponse(messageId, chatId, streamOpts);
        assistant = resp.content;
        category = resp.category;
        modelName = resp.modelName;
        followUpSuggestions = resp.followUpSuggestions;
      } finally {
        ws.close();
      }
    }

    const mateName = category ? (MATE_NAMES[category] ?? null) : null;
    return {
      chatId,
      assistant,
      category,
      modelName,
      mateName,
      followUpSuggestions,
    };
  }

  getIncognitoHistory(): IncognitoHistoryItem[] {
    return loadIncognitoHistory();
  }

  clearIncognitoHistory(): void {
    clearIncognitoHistory();
  }

  /**
   * Delete a chat by ID.
   *
   * Mirrors the web app's sendDeleteChatImpl in chatSyncServiceSenders.ts.
   * Sends a delete_chat WebSocket message and waits for the server ack.
   */
  async deleteChat(chatIdInput: string): Promise<void> {
    const session = this.requireSession();

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

    const ws = this.makeWsClient(session);
    await ws.open();

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

    // The top-level schema has a "requests" array with items $ref →
    // navigate to the RequestItem_* schema which has the actual params.
    const requestsProp = (
      topSchema.properties as
        | Record<string, Record<string, unknown>>
        | undefined
    )?.requests;
    const itemsRef = requestsProp?.items as Record<string, unknown> | undefined;
    const itemSchema = itemsRef ? resolveSchema(itemsRef) : null;

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
      throw new Error(`Skill execution failed with HTTP ${response.status}`);
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
  // Settings (generic passthrough)
  // -------------------------------------------------------------------------

  async settingsGet(path: string): Promise<unknown> {
    this.requireSession();
    const normalizedPath = this.normalizePath(path);
    const response = await this.http.get(
      normalizedPath,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Settings GET failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async settingsPost(
    path: string,
    body: Record<string, unknown>,
  ): Promise<unknown> {
    this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const response = await this.http.post(
      normalizedPath,
      body,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Settings POST failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async settingsDelete(path: string): Promise<unknown> {
    this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const response = await this.http.delete(
      normalizedPath,
      this.getCliRequestHeaders(),
    );
    if (!response.ok) {
      throw new Error(`Settings DELETE failed with HTTP ${response.status}`);
    }
    return response.data;
  }

  async settingsPatch(
    path: string,
    body: Record<string, unknown>,
  ): Promise<unknown> {
    this.requireSession();
    const normalizedPath = this.normalizePath(path);
    if (BLOCKED_SETTINGS_MUTATE_PATHS.has(normalizedPath)) {
      throw new Error(`Blocked operation: ${normalizedPath}`);
    }
    const response = await this.http.patch(
      normalizedPath,
      body,
      this.getCliRequestHeaders(),
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
    this.requireSession();
    const response = await this.http.post(
      "/v1/payments/redeem-gift-card",
      { code },
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
    const session = this.requireSession();
    const ws = this.makeWsClient(session);
    await ws.open();

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
    const session = this.requireSession();
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

    const ws = this.makeWsClient(session);
    await ws.open();
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
    return this.requireSession();
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

  private requireSession(): OpenMatesSession {
    if (!this.session) {
      throw new Error("Not logged in. Run `openmates login`.");
    }
    return this.session;
  }

  private getMasterKeyBytes(): Uint8Array {
    const session = this.requireSession();
    return base64ToBytes(session.masterKeyExportedB64);
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
    });
  }

  /**
   * Ensure the local sync cache is up to date. If the cache is fresh,
   * return it directly. Otherwise, do a full WS sync and save to disk.
   *
   * The sync cache stores encrypted data — decryption is always on-demand.
   * SECURITY: decrypted user content is NEVER written to disk.
   */
  async ensureSynced(forceRefresh = false): Promise<SyncCache> {
    if (!forceRefresh && isSyncCacheFresh()) {
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
        clientChatVersions[id] = {
          messages_v:
            typeof chat.details.messages_v === "number"
              ? chat.details.messages_v
              : 0,
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

    const session = this.requireSession();
    const ws = this.makeWsClient(session);
    await ws.open();
    const chats: CachedChat[] = [];
    let embeds: Record<string, unknown>[] = [];
    let embedKeys: Record<string, unknown>[] = [];
    let newChatSuggestions: Record<string, unknown>[] = [];
    let totalChatCount = 0;

    try {
      ws.send("phased_sync_request", {
        phase: "phase3",
        client_chat_versions: clientChatVersions,
        client_chat_ids: clientChatIds,
        client_embed_ids: clientEmbedIds,
      });
      const initial = await ws.waitForMessage("phase_3_last_100_chats_ready");
      const initialPayload = initial.payload as {
        chats?: Array<Record<string, unknown>>;
        total_chat_count?: number;
        embeds?: Record<string, unknown>[];
        embed_keys?: Record<string, unknown>[];
        new_chat_suggestions?: Record<string, unknown>[];
      };

      const firstChats = initialPayload.chats ?? [];
      for (const wrapper of firstChats) {
        const details = wrapper.chat_details as
          | Record<string, unknown>
          | undefined;
        if (!details || typeof details.id !== "string") continue;
        const messages = Array.isArray(wrapper.messages)
          ? (wrapper.messages as string[])
          : [];
        chats.push({ details, messages });
      }

      totalChatCount = initialPayload.total_chat_count ?? firstChats.length;
      embeds = initialPayload.embeds ?? [];
      embedKeys = initialPayload.embed_keys ?? [];
      newChatSuggestions = initialPayload.new_chat_suggestions ?? [];

      // Load remaining chats if there are more
      let offset = firstChats.length;
      while (offset < totalChatCount) {
        ws.send("load_more_chats", { offset, limit: 50 });
        const more = await ws.waitForMessage("load_more_chats_response");
        const payload = more.payload as {
          chats?: Array<Record<string, unknown>>;
          has_more?: boolean;
          embeds?: Record<string, unknown>[];
          embed_keys?: Record<string, unknown>[];
        };
        const batch = payload.chats ?? [];
        for (const wrapper of batch) {
          const details = wrapper.chat_details as
            | Record<string, unknown>
            | undefined;
          if (!details || typeof details.id !== "string") continue;
          const messages = Array.isArray(wrapper.messages)
            ? (wrapper.messages as string[])
            : [];
          chats.push({ details, messages });
        }
        // Merge additional embeds/embed_keys from paginated responses
        if (payload.embeds) embeds.push(...payload.embeds);
        if (payload.embed_keys) embedKeys.push(...payload.embed_keys);
        offset += batch.length;
        if (!payload.has_more || batch.length === 0) break;
      }
    } finally {
      ws.close();
    }

    // Delta merge: server only sent new/changed chats. Carry forward
    // unchanged chats from the existing cache so we don't lose them.
    if (existingCache) {
      const serverChatIds = new Set(
        chats.map((c) => String(c.details.id ?? "")),
      );
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

    // Handle deleted chats: if merged count exceeds server total,
    // some chats were deleted server-side. Trim oldest (end of sorted list).
    if (totalChatCount > 0 && chats.length > totalChatCount) {
      chats.length = totalChatCount;
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
      Origin: deriveAppUrl(this.apiUrl),
    };
  }

  private getCliUserAgent(): string {
    return `${CLI_DEVICE_NAME_PREFIX}/0.1 (${platform()} ${release()})`;
  }

  private getLocalDeviceName(): string {
    return `${CLI_DEVICE_NAME_PREFIX} (${platform()} ${release()})`;
  }
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

/**
 * Parse the [app-skill] or [app] prefix from a new-chat suggestion text.
 *
 * Mirrors parseSuggestion() in NewChatSuggestions.svelte (web app).
 *
 * Examples:
 *   "[web-search] What's the weather today?" → { body: "What's the weather today?", appId: "web", skillId: "search" }
 *   "[images-generate] Draw a cat" → { body: "Draw a cat", appId: "images", skillId: "generate" }
 *   "[web] Open my bookmarks" → { body: "Open my bookmarks", appId: "web", skillId: null }
 *   "How do I fix this bug?" → { body: "How do I fix this bug?", appId: null, skillId: null }
 */
export function parseNewChatSuggestionText(text: string): {
  body: string;
  appId: string | null;
  skillId: string | null;
} {
  const prefixMatch = /^\[([a-z0-9_-]+(?:-[a-z0-9_]+)?)\]\s*/.exec(text);
  if (!prefixMatch) {
    return { body: text.trim(), appId: null, skillId: null };
  }

  const raw = prefixMatch[1]; // e.g. "web-search" or "images-generate" or "web"
  const body = text.slice(prefixMatch[0].length).trim();

  // Split on the last hyphen to separate app from skill.
  // App IDs that contain hyphens (e.g. "web") should not be split further
  // if there is no skill ID portion. We rely on the convention that the
  // prefix format is always [appId-skillId] or [appId].
  const dashIdx = raw.indexOf("-");
  if (dashIdx === -1) {
    return { body, appId: raw, skillId: null };
  }

  const appId = raw.slice(0, dashIdx);
  const skillId = raw.slice(dashIdx + 1);
  return { body, appId, skillId };
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
