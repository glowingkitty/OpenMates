/*
 * OpenMates CLI SDK client.
 *
 * Purpose: expose pair-auth, chat, app-skill, and settings operations.
 * Architecture: REST for auth/settings/apps + WebSocket for chat operations.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: pair-auth only for account login; no terminal credential prompts.
 * Tests: frontend/packages/openmates-cli/tests/crypto.test.ts
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
}

interface ParsedChat {
  id: string;
  encryptedTitle: string | null;
  encryptedSummary: string | null;
  encryptedChatKey: string | null;
  lastEditedOverallTimestamp: number | null;
}

interface OpenMatesClientOptions {
  apiUrl?: string;
  session?: OpenMatesSession;
}

const DEFAULT_API_URL =
  process.env.OPENMATES_API_URL ?? "https://api.openmates.org";

/**
 * Derive the web app URL from the API URL so the pair token is always looked
 * up on the same backend the CLI created it on.
 *
 * Override with OPENMATES_APP_URL when using a custom setup.
 */
function deriveAppUrl(apiUrl: string): string {
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
  // Unknown / self-hosted — fall back to production web app
  return "https://openmates.org";
}

const CLI_DEVICE_NAME_PREFIX = "OpenMates CLI";
const BLOCKED_SETTINGS_POST_PATHS = new Set<string>([
  "/v1/settings/api-keys",
  "/v1/settings/update-password",
  "/v1/auth/setup_password",
  "/v1/auth/2fa/setup/initiate",
  "/v1/auth/2fa/setup/provider",
  "/v1/auth/2fa/setup/verify-signup",
]);

export class OpenMatesClient {
  private readonly apiUrl: string;
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

  async listChats(): Promise<ChatListItem[]> {
    const parsed = await this.fetchAllChatMetadata();
    const masterKey = this.getMasterKeyBytes();
    const output: ChatListItem[] = [];
    for (const chat of parsed) {
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
      output.push({
        id: chat.id,
        shortId: chat.id.slice(0, 8),
        title,
        summary,
        updatedAt: chat.lastEditedOverallTimestamp,
      });
    }
    return output;
  }

  async searchChats(query: string): Promise<ChatListItem[]> {
    const normalized = query.trim().toLowerCase();
    const chats = await this.listChats();
    return chats.filter((chat) => {
      const title = (chat.title ?? "").toLowerCase();
      const summary = (chat.summary ?? "").toLowerCase();
      return (
        title.includes(normalized) ||
        summary.includes(normalized) ||
        chat.id.includes(normalized)
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
    const ws = new OpenMatesWsClient({
      apiUrl: session.apiUrl,
      sessionId: randomUUID(),
      wsToken: session.wsToken,
      refreshToken: session.cookies.auth_refresh_token ?? null,
    });
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

  async listApps(apiKey: string): Promise<unknown> {
    const response = await this.http.get("/v1/apps", {
      ...this.getCliRequestHeaders(),
      Authorization: `Bearer ${apiKey}`,
    });
    if (!response.ok) {
      throw new Error("Failed to list apps. Ensure API key has app scope.");
    }
    return response.data;
  }

  async runSkill(params: {
    app: string;
    skill: string;
    inputData: Record<string, unknown>;
    apiKey: string;
  }): Promise<unknown> {
    const response = await this.http.post(
      `/v1/apps/${params.app}/skills/${params.skill}`,
      {
        input_data: params.inputData,
        parameters: {},
      },
      {
        ...this.getCliRequestHeaders(),
        Authorization: `Bearer ${params.apiKey}`,
      },
    );
    if (!response.ok) {
      throw new Error(`Skill execution failed with HTTP ${response.status}`);
    }
    return response.data;
  }

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
    if (BLOCKED_SETTINGS_POST_PATHS.has(normalizedPath)) {
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

  async listMemories(): Promise<unknown[]> {
    const data = (await this.settingsGet(
      "/v1/settings/export-account-data?include_usage=false&include_invoices=false",
    )) as { data?: { app_settings_memories?: unknown[] } };
    return data.data?.app_settings_memories ?? [];
  }

  async createMemory(params: {
    appId: string;
    itemKey: string;
    itemType: string;
    content: string;
  }): Promise<{ success: boolean; id: string }> {
    const session = this.requireSession();
    const masterKey = this.getMasterKeyBytes();
    const entryId = randomUUID();
    const now = Math.floor(Date.now() / 1000);
    const encryptedItemJson = await encryptWithAesGcmCombined(
      JSON.stringify({ content: params.content }),
      masterKey,
    );

    const ws = new OpenMatesWsClient({
      apiUrl: session.apiUrl,
      sessionId: randomUUID(),
      wsToken: session.wsToken,
      refreshToken: session.cookies.auth_refresh_token ?? null,
    });
    await ws.open();
    ws.send("store_app_settings_memories_entry", {
      entry: {
        id: entryId,
        app_id: params.appId,
        item_key: params.itemKey,
        item_type: params.itemType,
        encrypted_item_json: encryptedItemJson,
        encrypted_app_key: "",
        created_at: now,
        updated_at: now,
        item_version: 1,
      },
    });

    try {
      await ws.waitForMessage(
        "app_settings_memories_entry_stored",
        (payload) => {
          const parsed = payload as Record<string, unknown>;
          return parsed.entry_id === entryId;
        },
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
    if (!session) {
      return null;
    }
    const required = [
      session.apiUrl,
      session.sessionId,
      session.masterKeyExportedB64,
      session.hashedEmail,
      session.userEmailSalt,
    ];
    if (
      required.some((value) => typeof value !== "string" || value.length === 0)
    ) {
      return null;
    }
    return session;
  }

  private async fetchAllChatMetadata(): Promise<ParsedChat[]> {
    const session = this.requireSession();
    const ws = new OpenMatesWsClient({
      apiUrl: session.apiUrl,
      sessionId: randomUUID(),
      wsToken: session.wsToken,
      refreshToken: session.cookies.auth_refresh_token ?? null,
    });
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
        if (!payload.has_more || batch.length === 0) {
          break;
        }
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
        if (exitState.canceled) {
          throw new Error("Pairing canceled by user");
        }
        await sleep(2_000);
        if (exitState.canceled) {
          throw new Error("Pairing canceled by user");
        }
        const poll = await this.http.get<{
          status?: string;
          authorizer_device_name?: string;
        }>(`/v1/auth/pair/poll/${token}`, this.getCliRequestHeaders());
        if (!poll.ok) {
          continue;
        }
        status = poll.data.status ?? "waiting";
        authorizerDeviceName =
          typeof poll.data.authorizer_device_name === "string"
            ? poll.data.authorizer_device_name
            : null;
        if (status === "expired") {
          throw new Error("Pair token expired before authorization");
        }
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
      return {
        canceled: false,
        cleanup: () => undefined,
      };
    }
    const wasRaw = stdin.isRaw === true;
    stdin.setRawMode(true);
    stdin.resume();

    const onData = (raw: Buffer | string) => {
      const value = typeof raw === "string" ? raw : raw.toString("utf8");
      const normalized = value.toLowerCase();
      if (normalized.includes("e") || value === "\u001b") {
        state.canceled = true;
      }
      if (value === "\u0003") {
        state.canceled = true;
      }
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
    // Origin is required by verify_allowed_origin on auth endpoints (login, lookup).
    // The CLI acts on behalf of the web app, so we send the derived app URL as Origin.
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

function extractChatFromPayload(wrapper: {
  chat_details?: Record<string, unknown>;
}): ParsedChat | null {
  const details = wrapper.chat_details;
  if (!details || typeof details.id !== "string") {
    return null;
  }
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
    lastEditedOverallTimestamp:
      typeof details.last_edited_overall_timestamp === "number"
        ? details.last_edited_overall_timestamp
        : null,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
