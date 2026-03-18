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
  encryptWithAesGcmCombined,
  base64ToBytes,
  hashItemKey,
} from "./crypto.js";
import { OpenMatesHttpClient } from "./http.js";
import {
  type OpenMatesSession,
  type IncognitoHistoryItem,
  loadSession,
  saveSession,
  clearSession,
  loadIncognitoHistory,
  saveIncognitoHistory,
  clearIncognitoHistory,
} from "./storage.js";
import { OpenMatesWsClient } from "./ws.js";

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
}

export interface ChatListPage {
  chats: ChatListItem[];
  total: number;
  page: number;
  limit: number;
  hasMore: boolean;
}

interface ParsedChat {
  id: string;
  encryptedTitle: string | null;
  encryptedSummary: string | null;
  encryptedChatKey: string | null;
  encryptedCategory: string | null;
  lastEditedOverallTimestamp: number | null;
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

  async listChats(limit = 10, page = 1): Promise<ChatListPage> {
    const parsed = await this.fetchAllChatMetadata();
    const masterKey = this.getMasterKeyBytes();
    const total = parsed.length;
    const offset = (page - 1) * limit;
    const slice = parsed.slice(offset, offset + limit);
    const output: ChatListItem[] = [];
    for (const chat of slice) {
      const chatKey = chat.encryptedChatKey
        ? await decryptWithAesGcmCombined(chat.encryptedChatKey, masterKey)
        : null;
      const chatKeyBytes = chatKey ? base64ToBytes(chatKey) : null;
      const title =
        chat.encryptedTitle && chatKeyBytes
          ? await decryptWithAesGcmCombined(chat.encryptedTitle, chatKeyBytes)
          : null;
      const summary =
        chat.encryptedSummary && chatKeyBytes
          ? await decryptWithAesGcmCombined(chat.encryptedSummary, chatKeyBytes)
          : null;
      const category =
        chat.encryptedCategory && chatKeyBytes
          ? await decryptWithAesGcmCombined(
              chat.encryptedCategory,
              chatKeyBytes,
            )
          : null;
      output.push({
        id: chat.id,
        shortId: chat.id.slice(0, 8),
        title,
        summary,
        updatedAt: chat.lastEditedOverallTimestamp,
        category,
      });
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
    const normalized = query.trim().toLowerCase();
    const { chats } = await this.listChats(1000, 1);
    return chats.filter((chat) => {
      const title = (chat.title ?? "").toLowerCase();
      const summary = (chat.summary ?? "").toLowerCase();
      return (
        title.includes(normalized) ||
        summary.includes(normalized) ||
        chat.id.includes(normalized) ||
        (chat.category ?? "").toLowerCase().includes(normalized)
      );
    });
  }

  async sendMessage(params: {
    message: string;
    chatId?: string;
    incognito?: boolean;
  }): Promise<{ chatId: string; assistant: string }> {
    const session = this.requireSession();
    const chatId = params.chatId ?? randomUUID();
    const ws = this.makeWsClient(session);
    await ws.open();

    const messageId = randomUUID();
    ws.send("chat_message_added", {
      chat_id: chatId,
      is_incognito: Boolean(params.incognito),
      message: {
        message_id: messageId,
        chat_id: chatId,
        role: "user",
        sender_name: "User",
        status: "sent",
        content: params.message,
        created_at: Math.floor(Date.now() / 1000),
        chat_has_title: Boolean(params.chatId),
      },
    });

    let assistant = "";
    if (params.incognito) {
      const history = loadIncognitoHistory();
      history.push({
        role: "user",
        content: params.message,
        createdAt: Date.now(),
      });
      try {
        assistant = await ws.collectAiResponse(messageId);
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
        assistant = await ws.collectAiResponse(messageId);
      } finally {
        ws.close();
      }
    }

    return { chatId, assistant };
  }

  getIncognitoHistory(): IncognitoHistoryItem[] {
    return loadIncognitoHistory();
  }

  clearIncognitoHistory(): void {
    clearIncognitoHistory();
  }

  // -------------------------------------------------------------------------
  // Apps
  // -------------------------------------------------------------------------

  async listApps(apiKey?: string): Promise<unknown> {
    const headers: Record<string, string> = {
      ...this.getCliRequestHeaders(),
    };
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const response = await this.http.get("/v1/apps", headers);
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
    // Public metadata endpoint — no auth required
    const response = await this.http.get(
      `/v1/apps/${encodeURIComponent(appId)}/metadata`,
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

  private normalizePath(path: string): string {
    if (path.startsWith("http://") || path.startsWith("https://")) {
      const url = new URL(path);
      return `${url.pathname}${url.search}`;
    }
    return path.startsWith("/") ? path : `/${path}`;
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

  private async fetchAllChatMetadata(): Promise<ParsedChat[]> {
    const session = this.requireSession();
    const ws = this.makeWsClient(session);
    await ws.open();
    const chats: ParsedChat[] = [];

    try {
      ws.send("phased_sync_request", {
        phase: "phase3",
        client_chat_versions: {},
        client_chat_ids: [],
        client_embed_ids: [],
      });
      const initial = await ws.waitForMessage("phase_3_last_100_chats_ready");
      const initialPayload = initial.payload as {
        chats?: Array<{ chat_details?: Record<string, unknown> }>;
        total_chat_count?: number;
      };

      const firstChats = initialPayload.chats ?? [];
      chats.push(
        ...firstChats
          .map(extractChatFromPayload)
          .filter((item): item is ParsedChat => item !== null),
      );

      const total = initialPayload.total_chat_count ?? firstChats.length;
      let offset = 100;
      while (offset < total) {
        ws.send("load_more_chats", { offset, limit: 50 });
        const more = await ws.waitForMessage("load_more_chats_response");
        const payload = more.payload as {
          chats?: Array<{ chat_details?: Record<string, unknown> }>;
          has_more?: boolean;
        };
        const batch = payload.chats ?? [];
        chats.push(
          ...batch
            .map(extractChatFromPayload)
            .filter((item): item is ParsedChat => item !== null),
        );
        offset += batch.length;
        if (!payload.has_more || batch.length === 0) break;
      }
    } finally {
      ws.close();
    }

    chats.sort(
      (a, b) =>
        (b.lastEditedOverallTimestamp ?? 0) -
        (a.lastEditedOverallTimestamp ?? 0),
    );
    return chats;
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

function extractChatFromPayload(wrapper: {
  chat_details?: Record<string, unknown>;
}): ParsedChat | null {
  const details = wrapper.chat_details;
  if (!details || typeof details.id !== "string") return null;
  return {
    id: details.id,
    encryptedTitle:
      typeof details.encrypted_title === "string"
        ? details.encrypted_title
        : null,
    encryptedSummary:
      typeof details.encrypted_chat_summary === "string"
        ? details.encrypted_chat_summary
        : null,
    encryptedChatKey:
      typeof details.encrypted_chat_key === "string"
        ? details.encrypted_chat_key
        : null,
    encryptedCategory:
      typeof details.encrypted_category === "string"
        ? details.encrypted_category
        : null,
    lastEditedOverallTimestamp:
      typeof details.last_edited_overall_timestamp === "number"
        ? details.last_edited_overall_timestamp
        : null,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
