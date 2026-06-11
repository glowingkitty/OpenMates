/**
 * Unit tests for OpenMatesClient session target selection.
 *
 * Purpose: prevent persisted pair-login sessions from appearing logged out when
 * the CLI is run without OPENMATES_API_URL.
 * Security: uses a temporary HOME and fake legacy session data; no real CLI
 * session, cookies, master keys, or account identifiers are read.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/client.test.ts
 */

import { describe, it, beforeEach, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

const originalHome = process.env.HOME;
const originalApiUrl = process.env.OPENMATES_API_URL;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-client-"));
const stateDir = join(tempHome, ".openmates");
const sessionPath = join(stateDir, "session.json");
const serverConfigPath = join(stateDir, "server.json");
const sessionApiUrl = "https://api.dev.openmates.org";

process.env.HOME = tempHome;
delete process.env.OPENMATES_API_URL;

mkdirSync(stateDir, { recursive: true, mode: 0o700 });

function writeLegacySession(apiUrl = sessionApiUrl): void {
  writeFileSync(
    sessionPath,
    JSON.stringify(
      {
        apiUrl,
        sessionId: "test-session-id",
        wsToken: "test-ws-token",
        cookies: { auth_refresh_token: "test-refresh-token" },
        masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        hashedEmail: "test-hashed-email",
        userEmailSalt: "test-email-salt",
        createdAt: 1710000000000,
        authorizerDeviceName: "Test Browser",
        autoLogoutMinutes: null,
      },
      null,
      2,
    ),
    { mode: 0o600 },
  );
}

writeLegacySession();

const {
  OpenMatesClient,
  MEMORY_TYPE_REGISTRY,
  buildSubChatConfirmationPayload,
  buildSubChatEncryptedMetadataPayloads,
  getClientMessagesVersionForSync,
} = await import("../src/client.ts");
const { decryptWithAesGcmCombined } = await import("../src/crypto.ts");

after(() => {
  if (originalHome === undefined) {
    delete process.env.HOME;
  } else {
    process.env.HOME = originalHome;
  }
  if (originalApiUrl === undefined) {
    delete process.env.OPENMATES_API_URL;
  } else {
    process.env.OPENMATES_API_URL = originalApiUrl;
  }
  rmSync(tempHome, { recursive: true, force: true });
});

describe("OpenMatesClient session API URL", () => {
  beforeEach(() => {
    writeLegacySession();
    rmSync(serverConfigPath, { force: true });
  });

  it("uses the persisted session API URL when no override is set", () => {
    const client = OpenMatesClient.load();
    assert.strictEqual(client.apiUrl, sessionApiUrl);
  });

  it("keeps explicit API URL overrides higher priority than the persisted session", () => {
    const client = OpenMatesClient.load({ apiUrl: "http://127.0.0.1:8000" });
    assert.strictEqual(client.apiUrl, "http://127.0.0.1:8000");
  });

  it("uses installed self-host server API when no override or session exists", () => {
    rmSync(sessionPath, { force: true });
    writeFileSync(serverConfigPath, `${JSON.stringify({
      installPath: "/tmp/openmates-self-host",
      installedAt: Date.now(),
      composeProfile: "core",
      installMode: "image",
      apiUrl: "http://localhost:8000",
      appUrl: "http://localhost:5173",
    })}\n`);

    const client = OpenMatesClient.load();
    assert.strictEqual(client.apiUrl, "http://localhost:8000");
  });

  it("persists rotated auth cookies and ws tokens after whoami", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/session");
      response.writeHead(200, {
        "content-type": "application/json",
        "set-cookie": "auth_refresh_token=rotated-refresh-token; Path=/; HttpOnly",
      });
      response.end(
        JSON.stringify({
          success: true,
          ws_token: "rotated-ws-token",
          user: { id: "test-user-id" },
        }),
      );
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const user = await client.whoAmI();
      assert.deepEqual(user, { id: "test-user-id" });

      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.wsToken, "rotated-ws-token");
      assert.strictEqual(saved.cookies.auth_refresh_token, "rotated-refresh-token");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("memory type registry", () => {
  it("covers all production memory types needed by CLI memory commands", () => {
    assert.deepEqual(Object.keys(MEMORY_TYPE_REGISTRY).sort(), [
      "ai/communication_style",
      "ai/learning_preferences",
      "books/currently_reading",
      "books/favorite_books",
      "books/to_read_list",
      "code/coding_setup",
      "code/preferred_tech",
      "code/projects",
      "code/want_to_learn",
      "docs/writing_style",
      "events/saved_events",
      "health/appointments",
      "health/medical_history",
      "home/saved_listings",
      "images/preferred_styles",
      "mail/writing_styles",
      "reminder/saved_item_reminder_defaults",
      "study/learning_goals",
      "travel/preferred_activities",
      "travel/preferred_airlines",
      "travel/preferred_transport_methods",
      "travel/saved_connections",
      "travel/saved_stays",
      "travel/trips",
      "tv/to_watch_list",
      "tv/watched_movies",
      "tv/watched_tv_shows",
      "videos/to_watch_list",
      "web/bookmarks",
      "web/read_later",
    ]);
  });
});

describe("sub-chat encryption helpers", () => {
  it("encrypts child first-message metadata with the parent chat key", async () => {
    const parentKey = new Uint8Array(32).fill(7);
    const encryptedChatKey = "wrapped-parent-key";
    const payloads = await buildSubChatEncryptedMetadataPayloads({
      parentChatId: "parent-chat-id",
      parentChatKey: parentKey,
      encryptedParentChatKey: encryptedChatKey,
      createdAt: 1780000000,
      subChats: [
        {
          id: "child-chat-id",
          user_message_id: "child-user-message-id",
          prompt: "Research the counterargument.",
        },
      ],
    });

    assert.equal(payloads.length, 1);
    const payload = payloads[0];
    assert.equal(payload.chat_id, "child-chat-id");
    assert.equal(payload.parent_id, "parent-chat-id");
    assert.equal(payload.is_sub_chat, true);
    assert.equal(payload.message_id, "child-user-message-id");
    assert.equal(payload.encrypted_chat_key, encryptedChatKey);
    assert.equal(payload.versions.messages_v, 1);
    assert.equal(payload.versions.title_v, 0);

    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_content, parentKey),
      "Research the counterargument.",
    );
    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_sender_name, parentKey),
      "User",
    );
    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_title, parentKey),
      "Research the counterargument.",
    );
  });

  it("builds approval and cancellation payloads only from explicit decisions", () => {
    assert.deepEqual(
      buildSubChatConfirmationPayload({
        chatId: "parent-chat-id",
        taskId: "task-id",
        approved: true,
        approveCount: 2,
      }),
      {
        chat_id: "parent-chat-id",
        task_id: "task-id",
        action: "approve",
        approve_count: 2,
      },
    );

    assert.deepEqual(
      buildSubChatConfirmationPayload({
        chatId: "parent-chat-id",
        taskId: "task-id",
        approved: false,
      }),
      {
        chat_id: "parent-chat-id",
        task_id: "task-id",
        action: "cancel",
        approve_count: null,
      },
    );
  });
});

describe("sync delta request helpers", () => {
  it("forces a message refresh when cached metadata has no local messages", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: [],
      }),
      0,
    );
  });

  it("keeps the cached messages version when local messages are present", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id"}'],
      }),
      2,
    );
  });
});
