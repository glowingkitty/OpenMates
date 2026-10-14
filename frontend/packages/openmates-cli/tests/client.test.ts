/**
 * Unit tests for OpenMatesClient session target selection.
 *
 * Purpose: prevent persisted pair-login sessions from appearing logged out when
 * the CLI is run without OPENMATES_API_URL.
 * Security: uses a temporary HOME and fake legacy session data; no real CLI
 * session, cookies, master keys, or account identifiers are read.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/client.test.ts
 */

import { execFile } from "node:child_process";
import { describe, it, beforeEach, after } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { createRequire } from "node:module";
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
        emailEncryptionKeyB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
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

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");

const {
  OpenMatesClient,
  nextPersonalUserCreatedAt,
  MEMORY_TYPE_REGISTRY,
  buildAppSettingsMemoryRequestSystemMessage,
  buildAppSettingsMemoryResponseSystemMessage,
	buildInferenceHistoryMessage,
  buildSavedChatMessageHistory,
  canonicalSavedChatMessageId,
  buildTaskEventSystemMessage,
  buildTaskUpdateJobPersistPayload,
  messageExplicitlyRequestsTasksAppSkill,
  taskUpdateJobBelongsToActiveTurn,
  buildConnectedAccountDirectoryPayload,
  buildSubChatConfirmationPayload,
  buildSubChatEncryptedMetadataPayloads,
  buildTurnTokenRefsRequestPayload,
  getClientMessagesVersionForSync,
  parseEmbedContentObject,
  selectNewChatSlugValue,
  stageCliTeamNotificationPreview,
} = await import("../src/client.ts");

describe("Team notification preview transport", () => {
  // contract-test: supporting surface=cli assertions=notifications.content.privacy-boundary
  it("does not upload plaintext without a fresh opted-in recipient capability", async () => {
    const frames: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const ws = {
      waitForMessage: async (_type: string, _match: unknown) => ({ payload: { capability_id: null, recipient_count: 0 } }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => { frames.push({ type, payload }); },
    } as unknown as Parameters<typeof stageCliTeamNotificationPreview>[0];
    await stageCliTeamNotificationPreview(ws, { teamId: "team", chatId: "chat", messageId: "message", content: "private text" });
    assert.deepEqual(frames.map((frame) => frame.type), ["team_notification_preview_capabilities"]);
    assert.equal(JSON.stringify(frames).includes("private text"), false);
  });

  // contract-test: supporting surface=cli assertions=notifications.content.privacy-boundary,notifications.surface.semantic-parity
  it("stages at most ten lines, 2000 characters and a 60 character title after consent", async () => {
    const frames: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const ws = {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        await new Promise<void>((resolve) => setImmediate(resolve));
        const sent = frames.at(-1);
        assert.ok(sent && match({ request_id: sent.payload.request_id }));
        return { payload: type.endsWith("capabilities_result")
          ? { request_id: sent.payload.request_id, capability_id: "fresh-capability", recipient_count: 1 }
          : { request_id: sent.payload.request_id, staged: 1 } };
      },
      sendAsync: async (type: string, payload: Record<string, unknown>) => { frames.push({ type, payload }); },
    } as unknown as Parameters<typeof stageCliTeamNotificationPreview>[0];
    await stageCliTeamNotificationPreview(ws, {
      teamId: "team", chatId: "chat", messageId: "message",
      content: Array.from({ length: 12 }, (_, index) => `${index}: ${"x".repeat(300)}`).join("\n"),
      title: "T".repeat(80),
    });
    assert.equal(frames[1]?.type, "team_notification_preview_stage");
    assert.equal(String(frames[1]?.payload.preview).length, 2000);
    assert.ok(String(frames[1]?.payload.preview).split("\n").length <= 10);
    assert.equal(String(frames[1]?.payload.title).length, 60);
    assert.equal(frames[1]?.payload.capability_id, "fresh-capability");
  });

  // contract-test: supporting surface=cli assertions=notifications.content.privacy-boundary
  it("treats a failed preview request as a generic notification fallback", async () => {
    const frames: string[] = [];
    const ws = {
      waitForMessage: async () => { throw new Error("unavailable"); },
      sendAsync: async (type: string) => { frames.push(type); },
    } as unknown as Parameters<typeof stageCliTeamNotificationPreview>[0];
    await assert.doesNotReject(stageCliTeamNotificationPreview(ws, {
      teamId: "team", chatId: "chat", messageId: "message", content: "private text",
    }));
    assert.deepEqual(frames, ["team_notification_preview_capabilities"]);
  });

  // contract-test: supporting surface=cli assertions=notifications.content.privacy-boundary
  it("falls back when the socket send callback stalls until the reply times out", async () => {
    const frames: string[] = [];
    const ws = {
      waitForMessage: () => new Promise((_, reject) => {
        setTimeout(() => reject(new Error("reply timed out")), 10);
      }),
      sendAsync: (type: string) => {
        frames.push(type);
        return new Promise<void>(() => {});
      },
    } as unknown as Parameters<typeof stageCliTeamNotificationPreview>[0];
    await Promise.race([
      stageCliTeamNotificationPreview(ws, {
        teamId: "team", chatId: "chat", messageId: "message", content: "private text",
      }),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error("preview fallback stalled")), 100)),
    ]);
    assert.deepEqual(frames, ["team_notification_preview_capabilities"]);
  });
});
const {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  createApiKeyCryptoMaterial,
  hashEmail,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  sealChatCompletionRecoveryPayload,
} = await import("../src/crypto.ts");
const {
  clearSession,
  loadSession: loadStoredSession,
  loadSyncCache,
  saveLocalTeamKey,
  saveSyncCache,
} = await import("../src/storage.ts");
const { OpenMatesWsClient } = await import("../src/ws.ts");
const { createPairApprover, createPairContext, generateGrantSecret } = await import("@repo/pairing-crypto");

describe("saved embed content decoding", () => {
  // contract-test: direct surface=sdks.npm assertions=app-skills.media.parent-children-and-attribution,app-skills.media.visible-assistant-results
  it("retains generated-media file variants from Python keyed-tabular TOON", () => {
    const raw = "type: generated_image\nstatus: finished\n" +
      "files[3:]{s3_key,width,height,size_bytes,format,encryption}:\n" +
      "  original: unit/original.png,1024,1024,12000,png,aes-gcm\n" +
      "  preview: unit/preview.webp,512,512,6000,webp,aes-gcm\n" +
      "  thumbnail: unit/thumbnail.webp,256,256,3000,webp,aes-gcm\n" +
      "prompt: A sunflower illustration\nmodel: unit-image-model";
    const decoded = parseEmbedContentObject(raw);
    assert.equal(decoded.status, "finished");
    assert.deepEqual(decoded.files, {
      original: { s3_key: "unit/original.png", width: 1024, height: 1024, size_bytes: 12000, format: "png", encryption: "aes-gcm" },
      preview: { s3_key: "unit/preview.webp", width: 512, height: 512, size_bytes: 6000, format: "webp", encryption: "aes-gcm" },
      thumbnail: { s3_key: "unit/thumbnail.webp", width: 256, height: 256, size_bytes: 3000, format: "webp", encryption: "aes-gcm" },
    });
    assert.equal(decoded.prompt, "A sunflower illustration");
    assert.equal(decoded.model, "unit-image-model");
  });

  // contract-test: supporting surface=sdks.npm assertions=hosting-domains.embeds.parent-child,hosting-domains.surface-parity
  it("retains nested TOON domain results without absorbing them into skill_id", () => {
    const raw = "type: app_skill_use\napp_id: hosting\nskill_id: search_domains\nquery: meetly\n" +
      "results[2]:\n  - type: domain_result\n    domain_ascii: meetly.com\n" +
      "    availability: unavailable\n  - type: domain_result\n" +
      "    domain_ascii: meet-there.com\n    availability: available\n" +
      "    renewal_tiers[1]:\n      - duration_unit: y\n        min_duration: 1\n" +
      "        price_including_tax: 23.68";
    const decoded = parseEmbedContentObject(raw);
    assert.equal(decoded.skill_id, "search_domains");
    assert.deepEqual(decoded.results, [
      { type: "domain_result", domain_ascii: "meetly.com", availability: "unavailable" },
      { type: "domain_result", domain_ascii: "meet-there.com", availability: "available",
        renewal_tiers: [{ duration_unit: "y", min_duration: 1, price_including_tax: 23.68 }] },
    ]);
  });

  // contract-test: supporting surface=sdks.npm assertions=hosting-domains.surface-parity
  it("keeps JSON and informal legacy key:value embed content readable", () => {
    assert.deepEqual(parseEmbedContentObject('{"skill_id":"search_domains","results":[]}'),
      { skill_id: "search_domains", results: [] });
    assert.deepEqual(parseEmbedContentObject("type: sheet\ncontent: first line\nsecond line\nrow_count: 5"),
      { type: "sheet", content: "first line\nsecond line", row_count: 5 });
  });
});

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
  // contract-test: supporting surface=sdks.npm assertions=storage.export.persisted-bounded-complete,teams.workspace.surface-parity
  it("shows why a Team content import was rejected without dumping response data", async () => {
    const client = OpenMatesClient.load();
    const internals = client as unknown as { http: { post: (...args: unknown[]) => Promise<unknown> } };
    internals.http.post = async () => ({
      ok: false, status: 400,
      data: { detail: "Team content restore is unsupported for chats; no rows were imported", private_payload: "private-ciphertext" },
    });
    await assert.rejects(client.importTeamData("team-1", {}),
      /HTTP 400: Team content restore is unsupported for chats; no rows were imported/);
    internals.http.post = async () => ({ ok: false, status: 400, data: { detail: { private_payload: "private-ciphertext" } } });
    await assert.rejects(client.importTeamData("team-1", {}), /^Error: Team import failed with HTTP 400$/);
  });

  beforeEach(() => {
    writeLegacySession();
    rmSync(serverConfigPath, { force: true });
  });

  // contract-test: supporting surface=sdks.npm assertions=cli.slugs.encrypted-stable
  it("adds a length-safe chat ID suffix only to automatic new-chat slugs", () => {
    const repeatedPrompt = "Compare these apartment listings in detail ".repeat(8);
    const firstChatId = "11111111-1111-4111-8111-111111111111";
    const secondChatId = "22222222-2222-4222-8222-222222222222";
    const firstSlug = selectNewChatSlugValue({
      message: repeatedPrompt,
      chatId: firstChatId,
    });
    const secondSlug = selectNewChatSlugValue({
      message: repeatedPrompt,
      chatId: secondChatId,
    });

    assert.notEqual(firstSlug, secondSlug);
    assert.ok(firstSlug.length <= 80);
    assert.ok(secondSlug.length <= 80);
    assert.equal(firstSlug.endsWith(firstChatId), true);
    assert.equal(secondSlug.endsWith(secondChatId), true);
    assert.equal(selectNewChatSlugValue({
      message: repeatedPrompt,
      chatId: firstChatId,
      explicitSlug: "My Explicit Chat!",
    }), "My Explicit Chat!");
    assert.equal(selectNewChatSlugValue({
      message: "東京でおすすめの喫茶店を探して ☕",
      chatId: firstChatId,
    }), `chat-${firstChatId}`);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("shares original PII only with an explicit opt-in", async () => {
    const client = OpenMatesClient.load();
    const chatId = "11111111-1111-4111-8111-111111111111";
    const encryptedChatKey = await encryptBytesWithAesGcm(new Uint8Array(32), new Uint8Array(32));
    const internals = client as unknown as {
      ensureSynced: () => Promise<unknown>;
      http: { post: (path: string, body: Record<string, unknown>) => Promise<unknown> };
    };
    internals.ensureSynced = async () => ({ chats: [{ details: { id: chatId, encrypted_chat_key: encryptedChatKey } }] });
    const requests: Record<string, unknown>[] = [];
    internals.http.post = async (path, body) => {
      assert.equal(path, "/v1/share/chat/metadata");
      requests.push(body);
      return { ok: true, data: { success: true } };
    };
    await client.createChatShareLink(chatId);
    await client.createChatShareLink(chatId, 0, undefined, { includeSensitiveData: true });
    await client.createChatShareLink(chatId);
    assert.deepEqual(requests.map((body) => body.share_pii), [false, true, false]);
    assert.equal(requests.some((body) => "piiMappings" in body), false);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("keeps authentication capability discovery out of payment routes", () => {
    const source = readFileSync(new URL("../src/client.ts", import.meta.url), "utf8");
    const methodStart = source.indexOf("async getAuthMethodsStatus");
    const methodEnd = source.indexOf("async requestActionEmailCode", methodStart);
    const methodSource = source.slice(methodStart, methodEnd);

    assert.ok(methodStart >= 0, "getAuthMethodsStatus should remain available");
    assert.match(methodSource, /\/v1\/auth\/methods/);
    assert.doesNotMatch(methodSource, /\/v1\/payments\//);
  });

  // contract-test: supporting surface=cli assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant,auth.pair-login.lifecycle
  it("keeps a completed v2 pair-login session active and never sends the PIN or login bypass", async () => {
    const token = "PAIR12";
    const userId = "personal-account-id";
    const email = "paired@example.com";
    const masterKey = Buffer.alloc(32).toString("base64");
    const emailSalt = Buffer.alloc(16).toString("base64");
    const hashedEmail = await hashEmail(email);
    const encryptedEmail = await encryptWithAesGcmCombined(email, new Uint8Array(32));
    const grant = await generateGrantSecret();
    const requests: Array<{ url: string; body: Record<string, unknown>; capability: string }> = [];
    const sessionCookies: string[] = [];
    let approver: Awaited<ReturnType<typeof createPairApprover>> | null = null;
    let pin = "";
    let contextFields: { session_id: string; receiver_token_hash: string } | null = null;
    let responseMessage = "";
    let encrypted: { encrypted_bundle: string; iv: string } | null = null;
    let acknowledged = false;
    let acknowledgementReads = 0;
    const expiresAt = Math.floor(Date.now() / 1000) + 120;
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", chunk => { raw += chunk; });
      request.on("end", async () => {
        try {
          const body = raw ? JSON.parse(raw) as Record<string, unknown> : {};
          requests.push({ url: request.url ?? "", body, capability: String(request.headers["x-openmates-pair-receiver"] ?? "") });
          response.setHeader("content-type", "application/json");
          if (request.url === "/v1/auth/pair/v2/initiate") {
            contextFields = { session_id: String(body.session_id), receiver_token_hash: String(body.receiver_token_hash) };
            approver = await createPairApprover(createPairContext({
              token, ...contextFields, authorizer_user_id: userId, auto_logout_minutes: 30,
            }));
            pin = approver.pin;
            response.end(JSON.stringify({ protocol_version: 2, token, expires_at: expiresAt }));
          } else if (request.url === `/v1/auth/pair/v2/receiver/${token}`) {
            const status = acknowledged ? "acknowledged" : encrypted ? "ready" : responseMessage ? "response" : "approved";
            if (acknowledged) acknowledgementReads++;
            response.end(JSON.stringify({ status, expires_at: expiresAt,
              ...contextFields, authorizer_user_id: userId, authorizer_device_name: "Test Browser",
              auto_logout_minutes: 30, message: status === "response" ? responseMessage : undefined,
              ...encrypted,
            }));
          } else if (request.url === `/v1/auth/pair/v2/receiver/${token}/message`) {
            assert.ok(approver);
            if (body.stage === "request") responseMessage = await approver.receiveRequest(String(body.message));
            else if (body.stage === "finish") {
              await approver.verifyFinish(String(body.message));
              encrypted = await approver.encryptBundle({ protocol_version: 2,
                master_key_exported: masterKey,
                hashed_email: hashedEmail, user_email_salt: emailSalt,
                user_id: userId, grant_secret: grant.secret,
                account_context: { encrypted_email_with_master_key: encryptedEmail },
              });
            }
            response.end(JSON.stringify({ success: true }));
          } else if (request.url === `/v1/auth/pair/v2/complete/${token}`) {
            assert.equal(body.grant_secret, grant.secret);
            response.setHeader("set-cookie", "auth_refresh_token=test-refresh-token; Path=/; HttpOnly");
            response.end(JSON.stringify({ success: true, user: { id: userId }, ws_token: "test-ws-token", pair_expires_at: Math.floor(Date.now() / 1000) + 1800 }));
          } else if (request.url === `/v1/auth/pair/v2/acknowledge/${token}`) {
            assert.ok(loadStoredSession(), "receiver must persist session before acknowledgement");
            assert.ok(loadStoredSession()?.emailEncryptionKeyB64, "receiver must store its verified email key before acknowledgement");
            acknowledged = true;
            // Simulate an ACK committed by the server whose HTTP response is lost.
            response.destroy();
          } else if (request.url === "/v1/auth/session") {
            assert.equal(acknowledged, true, "session auth must wait for durable receiver acknowledgement");
            sessionCookies.push(String(request.headers.cookie ?? ""));
            response.end(JSON.stringify({ success: true, user: { id: userId } }));
          } else {
            response.statusCode = 404;
            response.end(JSON.stringify({ success: false }));
          }
        } catch (error) {
          response.statusCode = 500;
          response.end(JSON.stringify({ message: String(error) }));
        }
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    rmSync(sessionPath, { force: true });

    try {
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const interactiveClient = client as unknown as { prompt: () => Promise<string>; renderPairQrCode: () => void };
      interactiveClient.prompt = async () => pin;
      interactiveClient.renderPairQrCode = () => undefined;
      await client.loginWithPairAuth();
      assert.equal(acknowledged, true);
      assert.equal(acknowledgementReads, 1, "receiver must confirm durable ACK through readback");
      assert.ok(requests.every(request => request.url !== "/v1/auth/login"));
      assert.ok(requests.every(request => !Object.keys(request.body).some(key => /pin|lookup_hash|hashed_email/.test(key))));
      assert.ok(requests.every(request => !JSON.stringify(request.body).includes(pin)));
      assert.ok(requests.every(request => !JSON.stringify(request.body).includes(request.capability) || !request.capability));
      assert.ok(requests.filter(request => request.body.grant_secret !== undefined)
        .every(request => request.url === `/v1/auth/pair/v2/complete/${token}`));
      assert.ok(requests.every(request => !/^\/v1\/auth\/pair\/(?!v2\/)/.test(request.url)));
      assert.ok(requests.filter(request => request.url.includes(`/receiver/${token}`) || request.url.includes(`/complete/${token}`))
        .every(request => request.capability.length === 43));
      assert.equal((await client.whoAmI()).id, userId);
      assert.equal((await OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` }).whoAmI()).id, userId);
      assert.match(sessionCookies.at(-1) ?? "", /auth_refresh_token=test-refresh-token/);
      assert.ok((loadStoredSession()?.pairedSessionExpiresAt ?? 0) > Date.now());
    } finally {
      clearSession();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.pair-login.lifecycle,auth.pair-login.session-grant
  it("reports terminal pairing states without dropping context checks for live states", async () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 120;
    const approved = {
      status: "approved", expires_at: expiresAt,
      session_id: "receiver-session", receiver_token_hash: "a".repeat(64),
      authorizer_user_id: "approver-user", auto_logout_minutes: null,
    };
    let pollState: Record<string, unknown> = { status: "cancelled", expires_at: expiresAt };
    const server = createServer((_request, response) => {
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify(pollState));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const internal = client as unknown as {
        waitForPairState: (
          token: string, headers: Record<string, string>, expiresAt: number,
          wanted: ReadonlySet<string>, approved: typeof approved,
        ) => Promise<unknown>;
      };
      await assert.rejects(
        internal.waitForPairState("ABCDEF", {}, expiresAt, new Set(["ready"]), approved),
        /Pairing cancelled\. Start a new pairing\./,
      );

      pollState = { ...approved, status: "response", session_id: "different-session" };
      await assert.rejects(
        internal.waitForPairState("ABCDEF", {}, expiresAt, new Set(["ready"]), approved),
        /Pairing context changed during the exchange\./,
      );
    } finally {
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=cli.pairing.expiry-upgrade,auth.pair-login.expiry
  it("stops using an in-memory paired session after its absolute deadline", () => {
    const saved = JSON.parse(readFileSync(sessionPath, "utf8"));
    saved.pairedSessionExpiresAt = Date.now() + 60_000;
    writeFileSync(sessionPath, JSON.stringify(saved), { mode: 0o600 });
    const client = OpenMatesClient.load();
    assert.equal(client.hasSession(), true);
    const active = client as unknown as { session: { pairedSessionExpiresAt: number } | null };
    assert.ok(active.session);
    active.session.pairedSessionExpiresAt = Date.now() - 1;
    assert.equal(client.hasSession(), false);
    assert.equal(loadStoredSession(), null);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("manages application preview lifecycle through authenticated embed preview endpoints", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown>; cookie?: string }> = [];
    const embedId = "12345678-1234-4234-9234-123456789abc";
    const sessionId = "87654321-1234-4234-9234-123456789abc";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        requests.push({
          method: request.method,
          url: request.url,
          body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined,
          cookie: String(request.headers.cookie ?? ""),
        });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.url === `/v1/applications/${embedId}/preview/start`) {
          response.end(JSON.stringify({ session_id: sessionId, preview_url: "https://preview.example/t/token/", status: "queued", credits_per_minute: 5 }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "running", events: [], auto_started: false }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}/open`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "running", events: [], auto_started: false }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}/stop`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "stopped", charged_credits: 5 }));
          return;
        }
        response.writeHead(404);
        response.end(JSON.stringify({ detail: "not found" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.startApplicationPreview({ embedId, chatId: "chat-1", requestedRuntime: "svelte" });
      await client.getApplicationPreviewStatus(sessionId);
      await client.openApplicationPreview(sessionId);
      await client.stopApplicationPreview(sessionId);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      `POST /v1/applications/${embedId}/preview/start`,
      `GET /v1/applications/preview/${sessionId}`,
      `POST /v1/applications/preview/${sessionId}/open`,
      `POST /v1/applications/preview/${sessionId}/stop`,
    ]);
    assert.deepEqual(requests[0].body, { chat_id: "chat-1", requested_runtime: "svelte" });
    assert.ok(requests.every((request) => request.cookie?.includes("auth_refresh_token=test-refresh-token")));
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("uses the persisted session API URL when no override is set", () => {
    const client = OpenMatesClient.load();
    assert.strictEqual(client.apiUrl, sessionApiUrl);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("routes deterministic Project CRUD, children, source removal, and remote requests through one explicit context", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.method === "GET" && request.url?.startsWith("/v1/projects/project-1/sources/source-1/requests/request-1")) {
          response.end(JSON.stringify({ status: "completed", encrypted_envelope: "opaque-result" }));
        } else if (request.method === "GET" && request.url?.includes("/items")) {
          response.end(JSON.stringify({ folders: [], items: [] }));
        } else if (request.method === "GET" && request.url?.includes("/sources")) {
          response.end(JSON.stringify({ sources: [] }));
        } else if (request.method === "GET" && request.url?.includes("project-1")) {
          response.end(JSON.stringify({ project: { project_id: "project-1" }, folders: [], items: [] }));
        } else if (request.method === "POST" && request.url?.includes("/requests")) {
          response.end(JSON.stringify({ request_id: "request-1", status: "delivered" }));
        } else if (request.method === "DELETE") {
          response.end(JSON.stringify({ deleted: true }));
        } else {
          response.end(JSON.stringify({ project: { project_id: "project-1" } }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const context = { teamId: "team-1" };
      await client.getProject("project-1", context);
      await client.createProject({ project_id: "project-1" }, context);
      await client.updateProject("project-1", { pinned: true }, context);
      await client.deleteProject("project-1", "project-1", context);
      await client.listProjectItems("project-1", context);
      await client.listProjectSources("project-1", context);
      await client.deleteProjectSource("project-1", "source-1", "source-1", context);
      await client.createProjectRemoteAccessRequest("project-1", "source-1", {
        request_id: "request-1",
        requesting_client_id: "requester-1",
        operation: "list",
        key_epoch: 1,
        encrypted_envelope: "opaque-request",
      }, context);
      await client.getProjectRemoteAccessResult("project-1", "source-1", "request-1", "requester-1", context);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      "GET /v1/projects/project-1?team_id=team-1",
      "POST /v1/projects?team_id=team-1",
      "PATCH /v1/projects/project-1?team_id=team-1",
      "DELETE /v1/projects/project-1?confirmation_project_id=project-1&team_id=team-1",
      "GET /v1/projects/project-1/items?team_id=team-1",
      "GET /v1/projects/project-1/sources?team_id=team-1",
      "DELETE /v1/projects/project-1/sources/source-1?confirmation_source_id=source-1&team_id=team-1",
      "POST /v1/projects/project-1/sources/source-1/requests?team_id=team-1",
      "GET /v1/projects/project-1/sources/source-1/requests/request-1?requesting_client_id=requester-1&team_id=team-1",
    ]);
    assert.equal(requests[7]?.body?.encrypted_envelope, "opaque-request");
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("keeps explicit API URL overrides higher priority than the persisted session", () => {
    const client = OpenMatesClient.load({ apiUrl: "http://127.0.0.1:8000" });
    assert.strictEqual(client.apiUrl, "http://127.0.0.1:8000");
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
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

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("persists an ordinary API cookie rotation for the next CLI process", async () => {
    const seen: string[] = [];
    const server = createServer((request, response) => {
      seen.push(String(request.headers.cookie ?? ""));
      const first = seen.length === 1;
      response.writeHead(200, {
        "content-type": "application/json",
        ...(first ? { "set-cookie": "auth_refresh_token=ordinary-rotated; Path=/; HttpOnly" } : {}),
      });
      response.end(JSON.stringify({ apps: [] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      await OpenMatesClient.load({ apiUrl }).listApps();
      assert.equal(JSON.parse(readFileSync(sessionPath, "utf8")).cookies.auth_refresh_token, "ordinary-rotated");
      await new Promise<void>((resolve, reject) => {
        execFile(process.execPath, ["--experimental-strip-types", "--loader", "./tests/loader.mjs", "--input-type=module", "-e",
          "import { OpenMatesClient } from './src/client.ts'; await OpenMatesClient.load().listApps();"],
        { env: { ...process.env }, timeout: 30_000 }, error => error ? reject(error) : resolve());
      });
      assert.deepEqual(seen, ["auth_refresh_token=test-refresh-token", "auth_refresh_token=ordinary-rotated"]);
    } finally { await new Promise<void>((resolve) => server.close(() => resolve())); }
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("coalesces parallel ordinary rotations without restoring the sent cookie", async () => {
    const seen: string[] = [];
    const server = createServer((request, response) => {
      seen.push(String(request.headers.cookie ?? ""));
      setTimeout(() => {
        response.writeHead(200, {
          "content-type": "application/json",
          "set-cookie": "auth_refresh_token=shared-rotated; Path=/; HttpOnly",
        });
        response.end(JSON.stringify({ apps: [] }));
      }, 20);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      await Promise.all([client.listApps(), client.listApps()]);
      assert.deepEqual(seen, ["auth_refresh_token=test-refresh-token", "auth_refresh_token=test-refresh-token"]);
      assert.equal(JSON.parse(readFileSync(sessionPath, "utf8")).cookies.auth_refresh_token, "shared-rotated");
      assert.equal(client.getSession().cookies.auth_refresh_token, "shared-rotated");
    } finally { await new Promise<void>((resolve) => server.close(() => resolve())); }
  });

  // contract-test: supporting surface=sdks.npm assertions=auth.session.lifecycle
  it("does not persist a stale ordinary response after logout or account replacement", async () => {
    const pending: Array<() => void> = [];
    const server = createServer((_request, response) => {
      pending.push(() => {
        response.writeHead(200, { "content-type": "application/json", "set-cookie": "auth_refresh_token=late-token; Path=/; HttpOnly" });
        response.end(JSON.stringify({ apps: [] }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const request = client.listApps();
      while (!pending.length) await new Promise(resolve => setTimeout(resolve, 1));
      clearSession();
      pending.shift()!();
      await request;
      assert.equal(loadStoredSession(), null);

      writeLegacySession(apiUrl);
      const oldClient = OpenMatesClient.load({ apiUrl });
      const second = oldClient.listApps();
      while (!pending.length) await new Promise(resolve => setTimeout(resolve, 1));
      const replacement = JSON.parse(readFileSync(sessionPath, "utf8"));
      replacement.sessionId = "replacement-session";
      replacement.cookies.auth_refresh_token = "replacement-token";
      writeFileSync(sessionPath, JSON.stringify(replacement), { mode: 0o600 });
      pending.shift()!();
      await second;
      assert.equal(JSON.parse(readFileSync(sessionPath, "utf8")).cookies.auth_refresh_token, "replacement-token");
    } finally { await new Promise<void>((resolve) => server.close(() => resolve())); }
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle,auth.session.isolation
  it("does not persist response cookies for explicit or unauthenticated clients", async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, {
        "content-type": "application/json",
        "set-cookie": "auth_refresh_token=should-not-persist; Path=/; HttpOnly",
      });
      response.end(JSON.stringify({ apps: [] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const explicit = loadStoredSession()!;
      await OpenMatesClient.load({ apiUrl, session: explicit }).listApps();
      assert.equal(JSON.parse(readFileSync(sessionPath, "utf8")).cookies.auth_refresh_token, "test-refresh-token");
      clearSession();
      await OpenMatesClient.load({ apiUrl }).listApps();
      assert.equal(loadStoredSession(), null);
    } finally { await new Promise<void>((resolve) => server.close(() => resolve())); }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle,auth.session.isolation,chats.completion.lease-fenced
  it("keeps a Personal batch distinct from a pending home identity validation", async () => {
    let authCalls = 0;
    const batchFlags: boolean[] = [];
    let resolveFirstRequest!: () => void;
    const firstRequest = new Promise<void>(resolve => { resolveFirstRequest = resolve; });
    let releaseFirstResponse!: () => void;
    const firstResponse = new Promise<void>(resolve => { releaseFirstResponse = resolve; });
    const server = createServer((request, response) => {
      response.setHeader("content-type", "application/json");
      if (request.url === "/v1/auth/session") {
        authCalls++;
        let body = "";
        request.on("data", chunk => { body += chunk.toString(); });
        request.on("end", () => {
          batchFlags.push(JSON.parse(body).include_personal_memories === true);
        if (authCalls === 1) {
          resolveFirstRequest();
          void firstResponse.then(() => response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "owner-id" } })));
        } else response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "owner-id" },
          personal_memories: { encrypted_settings: null, memories: [] } }));
        });
      } else if (request.url === "/v1/sdk/memories") response.end(JSON.stringify({ memories: [] }));
      else { response.writeHead(404); response.end(JSON.stringify({})); }
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const homeIdentity = client.whoAmI();
      await firstRequest;
      const memories = client.listMemories({ personal: true });
      releaseFirstResponse();
      assert.equal((await homeIdentity).id, "owner-id");
      assert.deepEqual(await memories, []);
      assert.deepEqual(batchFlags, [false, true]);
      assert.equal(authCalls, 2);
      await client.whoAmI();
      assert.equal(authCalls, 3, "a completed validation must not be reused");
    } finally {
      releaseFirstResponse();
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("serializes refreshes and reloads credentials for clients created before rotation", async () => {
    let token = "test-refresh-token";
    let rejected = 0;
    const server = createServer((request, response) => {
      const accepted = request.headers.cookie === `auth_refresh_token=${token}`;
      if (accepted) token = `rotated-${Date.now()}-${Math.random()}`;
      else rejected++;
      const replacement = token;
      setTimeout(() => {
        response.setHeader("content-type", "application/json");
        if (accepted) response.setHeader("set-cookie", `auth_refresh_token=${replacement}; Path=/; HttpOnly`);
        response.end(JSON.stringify({ success: accepted, message: accepted ? "valid" : "Session expired", user: { id: "test-user" } }));
      }, 30);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const clients = Array.from({ length: 4 }, () => OpenMatesClient.load());
      await Promise.all(clients.map((client) => client.whoAmI()));
      await Promise.all(Array.from({ length: 4 }, () => new Promise<void>((resolve, reject) => {
        execFile(process.execPath, ["--experimental-strip-types", "--loader", "./tests/loader.mjs", "--input-type=module", "-e",
          "import { OpenMatesClient } from './src/client.ts'; await OpenMatesClient.load().whoAmI();"],
          { env: { ...process.env }, timeout: 30_000 }, (error) => error ? reject(error) : resolve());
      })));
      assert.equal(rejected, 0);
      assert.equal(JSON.parse(readFileSync(sessionPath, "utf8")).cookies.auth_refresh_token, token);
    } finally { await new Promise<void>((resolve) => server.close(() => resolve())); }
  });

  // contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
  it("reports gateway restarts as temporary instead of invalidating login", async () => {
    const server = createServer((_request: IncomingMessage, response: ServerResponse) => {
      response.writeHead(502, { "content-type": "application/json" });
      response.end(JSON.stringify({ message: "invalid session" }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      await assert.rejects(
        client.whoAmI(),
        /temporarily unavailable \(HTTP 502\).*retry shortly/i,
      );
      assert.ok(loadStoredSession(), "transient gateway failure must preserve the login session");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("purges local private data when session refresh is explicitly invalid", async () => {
    const emptyCache = {
      syncedAt: Date.now(),
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/session");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: false, message: "not authenticated" }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      saveSyncCache(emptyCache);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });

      await assert.rejects(
        client.ensureSynced(true),
        /Session expired or invalid/,
      );

      assert.strictEqual(loadStoredSession(), null);
      assert.strictEqual(loadSyncCache(), null);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("uses destructive local purge for manual logout", async () => {
    const emptyCache = {
      syncedAt: Date.now(),
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/logout");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      saveSyncCache(emptyCache);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });

      await client.logout();

      assert.strictEqual(client.hasSession(), false);
      assert.strictEqual(loadStoredSession(), null);
      assert.strictEqual(loadSyncCache(), null);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("uses destructive local purge after account deletion", async () => {
    const emptyCache = {
      syncedAt: Date.now(),
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/settings/delete-account");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, message: "deletion queued" }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      saveSyncCache(emptyCache);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });

      await client.deleteAccountWithCliVerification("654321");

      assert.strictEqual(client.hasSession(), false);
      assert.strictEqual(loadStoredSession(), null);
      assert.strictEqual(loadSyncCache(), null);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("returns the current rotated cookie jar for upload authentication", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps?include_unavailable=true");
      response.writeHead(200, {
        "content-type": "application/json",
        "set-cookie": "auth_refresh_token=rotated-upload-token; Path=/; HttpOnly",
      });
      response.end(JSON.stringify({ apps: [] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.listApps();

      const uploadSession = client.getSession();
      assert.strictEqual(uploadSession.cookies.auth_refresh_token, "rotated-upload-token");

      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.cookies.auth_refresh_token, "rotated-upload-token");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("includes session_id when refreshing the WebSocket token", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/session");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await (client as unknown as { refreshWsToken(): Promise<void> }).refreshWsToken();

      assert.deepEqual(JSON.parse(requestBody), { session_id: "test-session-id" });
      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.wsToken, "fresh-ws-token");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("creates API keys through the audited typed path while generic settings POST stays blocked", async () => {
    let seenBody: Record<string, unknown> | null = null;
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/settings/api-keys");
      assert.strictEqual(request.method, "POST");
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        raw += chunk;
      });
      request.on("end", () => {
        seenBody = JSON.parse(raw) as Record<string, unknown>;
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ id: "key-1", full_access: true, scopes: {} }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        () => client.settingsPost("api-keys", {}),
        /Blocked operation: \/v1\/settings\/api-keys/,
      );
      const result = await client.createApiKey({ name: "SDK live test" });

      assert.match(result.api_key, /^sk-api-[A-Za-z0-9]{32}$/);
      assert.deepEqual(result.key, { id: "key-1", full_access: true, scopes: {} });
      assert.ok(seenBody);
      assert.equal(seenBody.encrypted_name, result.crypto.encryptedName);
      assert.equal(seenBody.api_key_hash, result.crypto.apiKeyHash);
      assert.equal(seenBody.encrypted_key_prefix, result.crypto.encryptedKeyPrefix);
      assert.equal(seenBody.encrypted_master_key, result.crypto.encryptedMasterKey);
      assert.equal(seenBody.full_access, true);
      assert.deepEqual(seenBody.scopes, {});
      assert.equal(seenBody.credit_limit, null);
      assert.equal(seenBody.expires_at, null);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("lists API keys with decrypted display fields and pending device counts", async () => {
    const material = await createApiKeyCryptoMaterial("CLI Listed Key", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
    const server = createServer((_request: IncomingMessage, response: ServerResponse) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({
        api_keys: [{
          id: "key-1",
          encrypted_name: material.encryptedName,
          encrypted_key_prefix: material.encryptedKeyPrefix,
          created_at: "2026-07-15T10:00:00Z",
          last_used_at: null,
          full_access: true,
          scopes: {},
          credit_limit: null,
          pending_device_count: 1,
        }],
      }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.listApiKeys();

      assert.equal(result.api_keys[0].name, "CLI Listed Key");
      assert.match(result.api_keys[0].key_prefix, /^sk-api-.+\.\.\.$/);
      assert.equal(result.api_keys[0].last_used_at, null);
      assert.equal(result.api_keys[0].pending_device_count, 1);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("sends stable CLI API-key device headers for app-skill execution", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps/code/skills/get_docs");
      assert.strictEqual(request.method, "POST");
      assert.strictEqual(request.headers.authorization, "Bearer sk-api-test-key");
      assert.strictEqual(request.headers["x-openmates-sdk"], "cli");
      assert.match(String(request.headers["x-openmates-device-identity"]), /^cli:.+:.+$/);
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { ok: true } }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.runSkill({
        app: "code",
        skill: "get_docs",
        inputData: { library: "React", question: "useState" },
        apiKey: "sk-api-test-key",
      });

      assert.deepEqual(result, { success: true, data: { ok: true } });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("rejects app-skill responses that carry skill-level errors", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps/news/skills/search");
      assert.strictEqual(request.method, "POST");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { results: [], error: "provider quota exceeded" } }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        client.runSkill({
          app: "news",
          skill: "search",
          inputData: { requests: [{ query: "OpenMates" }] },
        }),
        /Skill execution failed: provider quota exceeded/,
      );
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("uses action-code and TOTP endpoints for destructive CLI step-up", async () => {
    const seen: Array<{ method: string | undefined; url: string | undefined; body: unknown }> = [];
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: request.method, url: request.url, body });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });

      await client.requestActionEmailCode("delete_team");
      await client.verifyActionEmailCode("delete_team", "123456");
      await client.verifyTotpForCurrentSession("654321");

      assert.deepEqual(seen.map((request) => [request.method, request.url, request.body]), [
        ["POST", "/v1/settings/request-action-verification", { action: "delete_team", email_encryption_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" }],
        ["POST", "/v1/settings/verify-action-code", { action: "delete_team", code: "123456" }],
        ["POST", "/v1/auth/2fa/verify/device", { tfa_code: "654321" }],
      ]);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("keeps polling app-skill tasks after transient task status failures", async () => {
    let taskPolls = 0;
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/apps/models3d/skills/generate") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, data: { task_id: "task-1" } }));
        return;
      }

      if (request.url === "/v1/tasks/task-1") {
        taskPolls += 1;
        if (taskPolls === 1) {
          response.writeHead(502, { "content-type": "application/json" });
          response.end(JSON.stringify({ detail: "temporary gateway error" }));
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ task_id: "task-1", status: "completed", result: { ok: true } }));
        return;
      }

      response.writeHead(404);
      response.end();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.runSkill({
        app: "models3d",
        skill: "generate",
        inputData: { image: "embed:test" },
      });

      assert.deepEqual(result, { success: true, data: { ok: true } });
      assert.equal(taskPolls, 2);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("persists pending AI responses during CLI sync", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const chatKey = new Uint8Array(32).fill(7);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    let completedPayload: Record<string, any> | null = null;

    wsServer.once("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "pending_ai_response",
            payload: {
              chat_id: "chat-1",
              message_id: "assistant-1",
              content: "Completed while the first client was gone.",
              fired_at: 1780000000,
              category: "general_knowledge",
              model_name: "Gemini 3 Flash",
            },
          }));
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              total_chat_count: 1,
              chats: [{
                chat_details: {
                  id: "chat-1",
                  encrypted_chat_key: encryptedChatKey,
                  messages_v: 1,
                  title_v: 0,
                  draft_v: 0,
                  last_edited_overall_timestamp: 1779999999,
                },
              }],
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }
        if (frame.type === "ai_response_completed") {
          completedPayload = frame.payload;
          socket.send(JSON.stringify({
            type: "ai_response_storage_confirmed",
            payload: { message_id: "assistant-1" },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const cache = await client.ensureSynced(true);

      assert.ok(completedPayload);
      assert.equal(completedPayload.chat_id, "chat-1");
      assert.equal(completedPayload.message.message_id, "assistant-1");
      assert.equal(completedPayload.versions.messages_v, 2);
      assert.equal(
        await decryptWithAesGcmCombined(completedPayload.message.encrypted_content, chatKey),
        "Completed while the first client was gone.",
      );
      assert.equal(cache.chats[0]?.messages.length, 1);
      const cachedMessage = JSON.parse(cache.chats[0]?.messages[0] as string);
      assert.equal(cachedMessage.message_id, "assistant-1");
      assert.equal(
        await decryptWithAesGcmCombined(cachedMessage.encrypted_content, chatKey),
        "Completed while the first client was gone.",
      );
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("refreshes exact chat messages before showing a selected chat", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const chatId = "22222222-2222-4222-8222-222222222222";
    const chatKey = new Uint8Array(32).fill(8);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedMessage = await encryptWithAesGcmCombined("Persisted fallback chat message", chatKey);
    const syncPayloads: Record<string, any>[] = [];

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        if (frame.type !== "phased_sync_request") return;
        syncPayloads.push(frame.payload);
        const isTargetedMetadataRefresh = Array.isArray(frame.payload?.refresh_chat_ids)
          && frame.payload.refresh_chat_ids.includes(chatId);
        if (frame.payload?.phase === "all" && !isTargetedMetadataRefresh) {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              total_chat_count: 1,
              chats: [{
                chat_details: {
                  id: chatId,
                  encrypted_chat_key: encryptedChatKey,
                  messages_v: 1,
                  title_v: 0,
                  draft_v: 0,
                  last_edited_overall_timestamp: 1780000000,
                },
              }],
            },
          }));
        }
        if (frame.payload?.phase === "phase3") {
          socket.send(JSON.stringify({
            type: "background_message_sync",
            payload: {
              chats: [{
                chat_id: chatId,
                messages: [JSON.stringify({
                  client_message_id: "message-1",
                  chat_id: chatId,
                  encrypted_content: encryptedMessage,
                  role: "assistant",
                  created_at: 1780000000,
                })],
              }],
            },
          }));
        }
        socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.getChatMessages(chatId);

      assert.equal(syncPayloads.length, 3);
      assert.deepEqual(syncPayloads[1]?.refresh_chat_ids, [chatId]);
      assert.equal(syncPayloads[2]?.phase, "phase3");
      assert.equal(syncPayloads[2]?.client_chat_versions?.[chatId], undefined);
      assert.equal(result.messages.length, 1);
      assert.equal(result.messages[0]?.content, "Persisted fallback chat message");
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("persists passive task update jobs advertised during CLI reconnect sync", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const chatKey = new Uint8Array(32).fill(9);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    let syncRequests = 0;
    const captured: { frameTypes: string[]; persistPayload?: Record<string, any>; systemMessage?: Record<string, any> } = {
      frameTypes: [],
    };

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        captured.frameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              total_chat_count: 1,
              chats: [{
                chat_details: {
                  id: "chat-1",
                  encrypted_chat_key: encryptedChatKey,
                  messages_v: 1,
                  title_v: 0,
                  draft_v: 0,
                  last_edited_overall_timestamp: 1780000000,
                },
              }],
            },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-reconnect",
                  task_id: "task-reconnect-1",
                  chat_id: "chat-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "task_update_job_claimed",
            payload: {
              job_id: "task-update-job-reconnect",
              task_id: "task-reconnect-1",
              chat_id: "chat-1",
              message_id: "user-message-1",
              operation: "create",
              state: "LEASED",
              lease_token: "lease-token",
              lease_generation: 1,
              expected_task_version: 0,
              private_patch: {
                title: "Reconnect task title",
                description: "Reconnect task description",
              },
              safe_metadata: {
                status: "todo",
                assignee_type: "user",
                primary_chat_id: null,
                position: 1780000001,
                created_at: 1780000001,
                updated_at: 1780000001,
              },
            },
          }));
        }

        if (frame.type === "task_update_job_persist") {
          captured.persistPayload = frame.payload;
          socket.send(JSON.stringify({
            type: "task_update_job_persisted",
            payload: { job_id: "task-update-job-reconnect" },
          }));
        }

        if (frame.type === "chat_system_message_added") {
          captured.systemMessage = frame.payload.message;
          socket.send(JSON.stringify({
            type: "system_message_confirmed",
            payload: { message_id: frame.payload.message.message_id },
          }));
        }

        if (frame.type === "task_update_job_event_confirmed") {
          socket.send(JSON.stringify({
            type: "task_update_job_event_confirmed",
            payload: { job_id: "task-update-job-reconnect" },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        captured.frameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        [
          "task_update_job_claim",
          "task_update_job_persist",
          "chat_system_message_added",
          "task_update_job_event_confirmed",
        ],
      );
      assert.ok(captured.persistPayload);
      const serializedPersistPayload = JSON.stringify(captured.persistPayload);
      assert.equal(serializedPersistPayload.includes("Reconnect task title"), false);
      assert.equal(serializedPersistPayload.includes("Reconnect task description"), false);
      assert.equal(captured.persistPayload.encrypted_task_payload.task_id, "task-reconnect-1");
      assert.equal(captured.persistPayload.encrypted_task_payload.primary_chat_id, null);
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_task_key);
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_title);
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_description);
      assert.ok(captured.systemMessage?.encrypted_content);
      assert.equal(captured.systemMessage.encrypted_content.includes("Reconnect task title"), false);
      const eventText = await decryptWithAesGcmCombined(captured.systemMessage.encrypted_content, chatKey);
      assert.match(eventText, /Reconnect task title/);
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("skips passive task update jobs that do not include source chat context", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const capturedFrameTypes: string[] = [];
    let syncRequests = 0;

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        capturedFrameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: { total_chat_count: 0, chats: [] },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-no-source",
                  task_id: "task-no-source-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "task_update_job_claimed",
            payload: {
              job_id: "task-update-job-no-source",
              task_id: "task-no-source-1",
              message_id: "user-message-1",
              operation: "create",
              state: "LEASED",
              lease_token: "lease-token",
              lease_generation: 1,
              expected_task_version: 0,
              private_patch: { title: "No source title" },
              safe_metadata: { status: "todo", assignee_type: "user" },
            },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        capturedFrameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        ["task_update_job_claim"],
      );
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("skips passive task update jobs already leased by another device", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const capturedFrameTypes: string[] = [];
    let syncRequests = 0;

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        capturedFrameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: { total_chat_count: 0, chats: [] },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-leased",
                  task_id: "task-leased-1",
                  chat_id: "chat-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "error",
            payload: {
              code: "task_update_job_lease_conflict",
              message: "Task update job is leased by another device",
            },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        capturedFrameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        ["task_update_job_claim"],
      );
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("memory type registry", () => {
  // contract-test: direct surface=sdks.npm assertions=app-memories.catalog.declared-types-only,app-memories.surface.semantic-parity
  it("covers all production memory types needed by CLI memory commands", () => {
    assert.deepEqual(Object.keys(MEMORY_TYPE_REGISTRY).sort(), [
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
      "ideabucket/processing_settings",
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

  // contract-test: direct surface=cli assertions=app-memories.surface.semantic-parity
  it("loads Personal rows and account documents from one fresh auth batch", async () => {
    const key = new Uint8Array(32);
    const encryptedItem = await encryptWithAesGcmCombined(JSON.stringify({ title: "Private preference" }), key);
    const document = "title: 'Private document'\nKeep Personal context private.";
    const encryptedSettings = await encryptWithAesGcmCombined(JSON.stringify({
      memory_documents: [{ id: "personal:note", source: "personal", document }],
    }), key);
    const requestPaths: string[] = [];
    const requestBodies: Array<Record<string, unknown>> = [];
    const server = createServer((request, response) => {
      requestPaths.push(`${request.method ?? "GET"} ${request.url ?? ""}`);
      if (request.method !== "POST" || request.url !== "/v1/auth/session") {
        response.writeHead(404); response.end(JSON.stringify({})); return;
      }
      let body = "";
      request.on("data", chunk => { body += chunk.toString(); });
      request.on("end", () => {
        requestBodies.push(JSON.parse(body) as Record<string, unknown>);
        response.writeHead(200, { "content-type": "application/json",
          "set-cookie": "auth_refresh_token=batched-cookie; Path=/; HttpOnly" });
        response.end(JSON.stringify({ success: true, ws_token: "batched-ws-token", user: { id: "owner-id" },
          personal_memories: { encrypted_settings: encryptedSettings, memories: [
            { id: "row-id", app_id: "code", item_type: "preferred_tech", item_key: "key-hash",
              encrypted_item_json: encryptedItem, item_version: 3, created_at: 1710000000, updated_at: 1710000100 },
            { id: "null-row", encrypted_item_json: null },
            { id: "corrupt-row", encrypted_item_json: "bad-ciphertext" },
          ] } }));
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const memories = await client.listMemories({ personal: true });
      assert.deepEqual(requestPaths, ["POST /v1/auth/session"]);
      assert.deepEqual(requestBodies, [{ session_id: "test-session-id", include_personal_memories: true }]);
      assert.deepEqual(memories.map(row => [row.id, row.data.title]), [
        ["row-id", "Private preference"], ["account-memory-note", "Private document"],
      ]);
      assert.equal(memories[1]?.data.document, document);
      const internal = client as unknown as { personalMemoryAuthHandoff: {
        snapshot: WeakRef<unknown[]>; auth: { cookieFingerprint: string; wsToken: string };
      } | null };
      assert.equal(internal.personalMemoryAuthHandoff?.snapshot.deref(), memories);
      assert.equal(internal.personalMemoryAuthHandoff?.auth.wsToken, "batched-ws-token");
      assert.equal(client.getSession()?.cookies.auth_refresh_token, "batched-cookie");
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=app-memories.surface.semantic-parity,auth.session.isolation
  it("decrypts socket snapshot rows and account documents without another HTTP read", async () => {
    const key = new Uint8Array(32);
    const document = "title: Socket document\nPrivate context.";
    const encryptedItem = await encryptWithAesGcmCombined(JSON.stringify({ title: "Socket row" }), key);
    const encryptedSettings = await encryptWithAesGcmCombined(JSON.stringify({
      memory_documents: [{ id: "personal:socket", source: "personal", document }],
    }), key);
    const apiUrl = "http://127.0.0.1:1";
    writeLegacySession(apiUrl);
    const client = OpenMatesClient.load({ apiUrl });
    const internal = client as unknown as { listMemoriesUnshared: (options: { personal: boolean },
      snapshot: { encrypted_settings: string | null; memories: Array<Record<string, unknown>> }) => Promise<Array<{
        id: string; data: { title: string; document?: string };
      }>> };
    const rows = await internal.listMemoriesUnshared({ personal: true }, {
      encrypted_settings: encryptedSettings,
      memories: [{ id: "socket-row", app_id: "code", item_type: "preferred_tech",
        item_key: "key-hash", encrypted_item_json: encryptedItem }],
    });
    assert.deepEqual(rows.map(row => [row.id, row.data.title]), [
      ["socket-row", "Socket row"], ["account-memory-socket", "Socket document"],
    ]);
    assert.equal(rows[1]?.data.document, document);
  });

  // contract-test: supporting surface=cli assertions=app-memories.surface.semantic-parity,auth.session.isolation
  it("keeps decrypted row Memories when batched account documents cannot decrypt", async () => {
    const encryptedItem = await encryptWithAesGcmCombined(JSON.stringify({ title: "Retained row" }), new Uint8Array(32));
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, ws_token: "fresh-token", user: { id: "owner-id" },
        personal_memories: { encrypted_settings: "corrupt-settings", memories: [
          { id: "retained-row", app_id: "code", item_type: "preferred_tech", item_key: "key-hash",
            encrypted_item_json: encryptedItem, item_version: 1, created_at: 1, updated_at: 1 },
        ] } }));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const memories = await client.listMemories({ personal: true });
      assert.deepEqual(memories.map(row => row.id), ["retained-row"]);
      const internal = client as unknown as { personalMemoryAuthHandoff: unknown };
      assert.equal(internal.personalMemoryAuthHandoff, null,
        "an incomplete account document snapshot must not become a send auth receipt");
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: direct surface=cli assertions=app-memories.surface.semantic-parity
  it("loads personal memories from the owner-scoped memory endpoint without account export", async () => {
    const encryptedItem = await encryptWithAesGcmCombined(
      JSON.stringify({
        title: "Private preference",
        settings_group: "code",
        _original_item_key: "preferred_tech",
      }),
      new Uint8Array(32),
    );
    const requestPaths: string[] = [];
    const server = createServer((request, response) => {
      requestPaths.push(`${request.method ?? "GET"} ${request.url ?? ""}`);
      if (request.method === "GET" && request.url === "/v1/sdk/memories") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          memories: [{
            id: "11111111-1111-4111-8111-111111111111",
            app_id: "code",
            item_type: "preferred_tech",
            item_key: "hashed-memory-key",
            item_version: 3,
            created_at: 1710000000,
            updated_at: 1710000100,
            encrypted_item_json: encryptedItem,
          }],
        }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "legacy-token", user: { id: "owner-id" } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const memories = await client.listMemories({ personal: true });

      assert.equal(memories.length, 1);
      assert.equal(memories[0]?.data.title, "Private preference");
      assert.deepEqual(requestPaths, ["POST /v1/auth/session", "GET /v1/sdk/memories", "POST /v1/auth/session"]);
      assert.equal(requestPaths.some((path) => path.includes("export-account-data")), false);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,app-memories.surface.semantic-parity
  for (const status of [401, 403, 429, 503] as const) it(`does not fall back from failed Personal batch auth: ${status}`, async () => {
    const requestPaths: string[] = [];
    const server = createServer((request, response) => {
      requestPaths.push(`${request.method ?? "GET"} ${request.url ?? ""}`);
      response.writeHead(status, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: false }));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      await assert.rejects(OpenMatesClient.load({ apiUrl }).listMemories({ personal: true }),
        new RegExp(`Personal memory session validation failed with HTTP ${status}`));
      assert.deepEqual(requestPaths, ["POST /v1/auth/session"]);
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,app-memories.surface.semantic-parity
  for (const batch of [null, { encrypted_settings: null, memories: {} },
    { encrypted_settings: 5, memories: [] }, { memories: [] }] as const) {
    it(`rejects a present malformed Personal batch without fallback: ${JSON.stringify(batch)}`, async () => {
      const requestPaths: string[] = [];
      const server = createServer((request, response) => {
        requestPaths.push(`${request.method ?? "GET"} ${request.url ?? ""}`);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token", user: { id: "owner-id" },
          personal_memories: batch }));
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      try {
        const apiUrl = `http://127.0.0.1:${address.port}`;
        writeLegacySession(apiUrl);
        await assert.rejects(OpenMatesClient.load({ apiUrl }).listMemories({ personal: true }),
          /Invalid Personal memory batch response/);
        assert.deepEqual(requestPaths, ["POST /v1/auth/session"]);
      } finally {
        server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,teams.workspace.surface-parity
  it("rejects a Personal batch if workspace ownership changes during auth", async () => {
    let releaseResponse!: () => void;
    const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
    let authRequested!: () => void;
    const authGate = new Promise<void>(resolve => { authRequested = resolve; });
    const server = createServer((request, response) => {
      if (request.url !== "/v1/auth/session") { response.writeHead(404); response.end(); return; }
      authRequested();
      void responseGate.then(() => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token", user: { id: "owner-id" },
          personal_memories: { encrypted_settings: null, memories: [] } }));
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const read = client.listMemories({ personal: true });
      await authGate;
      client.setActiveTeamId("other-team");
      releaseResponse();
      await assert.rejects(read, /Personal memory owner changed during preparation/);
      assert.equal(client.getSession()?.activeTeamId, "other-team");
    } finally {
      releaseResponse();
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  it("rejects a wrong trusted owner before persisting rotated batch credentials", async () => {
    const trustedPath = join(stateDir, "trusted_account.json");
    const requestBodies: Array<Record<string, unknown>> = [];
    const server = createServer((request, response) => {
      assert.equal(request.url, "/v1/auth/session");
      let body = "";
      request.on("data", chunk => { body += chunk.toString(); });
      request.on("end", () => {
        requestBodies.push(JSON.parse(body) as Record<string, unknown>);
        response.writeHead(200, { "content-type": "application/json",
          "set-cookie": "auth_refresh_token=wrong-owner-cookie; Path=/; HttpOnly" });
        response.end(JSON.stringify({ success: true, ws_token: "wrong-owner-ws-token",
          user: { id: "wrong-owner" },
          personal_memories: { encrypted_settings: null, memories: [] } }));
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      writeFileSync(trustedPath, JSON.stringify({ accountId: "trusted-owner" }), { mode: 0o600 });
      const before = readFileSync(sessionPath, "utf8");
      const client = OpenMatesClient.load({ apiUrl });
      await assert.rejects(client.listMemories({ personal: true }),
        /Personal memory owner changed during preparation/);
      assert.deepEqual(requestBodies, [{ session_id: "test-session-id", include_personal_memories: true }]);
      assert.equal(readFileSync(sessionPath, "utf8"), before);
      assert.equal(client.getSession()?.wsToken, "test-ws-token");
      assert.equal(client.getSession()?.cookies.auth_refresh_token, "test-refresh-token");
      const internal = client as unknown as {
        http: { getCookieMap(): Record<string, string> };
        personalMemoryAuthHandoff: unknown;
      };
      assert.equal(internal.http.getCookieMap().auth_refresh_token, "test-refresh-token");
      assert.equal(internal.personalMemoryAuthHandoff, null);
    } finally {
      rmSync(trustedPath, { force: true });
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
  it("keeps Team memory reads on the Team endpoint without flagged auth", async () => {
    const requestPaths: string[] = [];
    const server = createServer((request, response) => {
      requestPaths.push(`${request.method ?? "GET"} ${request.url ?? ""}`);
      response.writeHead(request.url === "/v1/teams/team-1/memories" ? 200 : 404,
        { "content-type": "application/json" });
      response.end(JSON.stringify({ memories: [] }));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      client.setActiveTeamId("team-1");
      assert.deepEqual(await client.listMemories(), []);
      assert.deepEqual(requestPaths, ["GET /v1/teams/team-1/memories"]);
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=chats.completion.lease-fenced
  it("shares only an in-flight Personal memory read for the same owner", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const internal = client as unknown as {
      fetchPersonalMemoryBatch: () => Promise<null>;
      sdkGetPersonalMemories: () => Promise<Array<Record<string, unknown>>>;
      getCustomRuleDocuments: () => Promise<[]>;
    };
    const finish: Array<(rows: Array<Record<string, unknown>>) => void> = [];
    internal.fetchPersonalMemoryBatch = async () => null;
    internal.sdkGetPersonalMemories = () => new Promise(resolve => { finish.push(resolve); });
    internal.getCustomRuleDocuments = async () => [];
    const first = client.listMemories({ personal: true });
    const shared = client.listMemories({ personal: true });
    await Promise.resolve();
    assert.equal(finish.length, 1);
    finish[0]!([]);
    const [firstRows, sharedRows] = await Promise.all([first, shared]);
    assert.equal(sharedRows, firstRows, "privacy snapshot and auth handoff must retain array identity");
    const fresh = client.listMemories({ personal: true });
    await Promise.resolve();
    assert.equal(finish.length, 2, "a settled read is never cached");
    client.getSession()!.hashedEmail = "another-owner";
    const changedOwner = client.listMemories({ personal: true });
    await Promise.resolve();
    assert.equal(finish.length, 3, "an in-flight read cannot cross owner identity");
    finish[1]!([]);
    finish[2]!([]);
    await Promise.all([fresh, changedOwner]);
  });
});

describe("saved embed on-demand lookup", () => {
  const embedId = "11111111-1111-4111-8111-111111111111";
  const chatId = "22222222-2222-4222-8222-222222222222";
  const emptyCache = () => ({ syncedAt: Date.now(), totalChatCount: 0, loadedChatCount: 0,
    chats: [], embeds: [], embedKeys: [] });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,chats.persistence.client-encrypted
  it("requests a full UUID missing from sync windows, decrypts its chat wrapper, and saves ciphertext", async () => {
    writeLegacySession();
    saveSyncCache(emptyCache());
    const client = OpenMatesClient.load();
    const chatKey = new Uint8Array(32).fill(7);
    const embedKey = new Uint8Array(32).fill(9);
    const source = { type: "diagram_html", html_source: "<html><body><svg data-om-diagram></svg></body></html>" };
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, new Uint8Array(32));
    const encryptedEmbedKey = await encryptBytesWithAesGcm(embedKey, chatKey);
    const encryptedContent = await encryptWithAesGcmCombined(JSON.stringify(source), embedKey);
    const encryptedType = await encryptWithAesGcmCombined("diagram_html", embedKey);
    const wrapper = { hashed_embed_id: createHash("sha256").update(embedId).digest("hex"),
      hashed_chat_id: createHash("sha256").update(chatId).digest("hex"),
      key_type: "chat", encrypted_embed_key: encryptedEmbedKey };
    const syncs: Array<{ force: boolean; chats: string[] }> = [];
    const requests: Record<string, unknown>[] = [];
    (client as any).ensureSynced = async (force: boolean, chats: string[]) => {
      syncs.push({ force, chats });
      if (!force) return emptyCache();
      const cache = { ...emptyCache(), totalChatCount: 1, loadedChatCount: 1,
        chats: [{ details: { id: chatId, encrypted_chat_key: encryptedChatKey }, messages: [] }] };
      saveSyncCache(cache);
      return cache;
    };
    let deliver!: (value: { payload: Record<string, unknown> }) => void;
    const ws = {
      waitForMessage: (_type: string, predicate: (payload: unknown) => boolean) => new Promise((resolve) => {
        deliver = (value) => { assert.ok(predicate(value.payload)); resolve(value); };
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        assert.equal(type, "request_embed");
        requests.push(payload);
        deliver({ payload: { payload: { embed_id: embedId, already_encrypted: true,
          status: "finished", chat_id: chatId, type: encryptedType, content: encryptedContent,
          embed_keys: [wrapper] } } });
      },
      close: () => {},
    };
    (client as any).openWsClient = async () => ({ ws });

    const embed = await client.getEmbed(embedId, { chatId });
    assert.deepEqual(syncs, [{ force: false, chats: [] }, { force: true, chats: [chatId] }]);
    assert.deepEqual(requests, [{ embed_id: embedId, chat_id: chatId }]);
    assert.equal(embed.type, "diagram_html");
    assert.deepEqual(embed.content, source);
    const saved = loadSyncCache();
    assert.equal(saved?.embeds.find((row) => row.embed_id === embedId)?.encrypted_content, encryptedContent);
    assert.equal(saved?.embedKeys.find((row) => row.hashed_embed_id === wrapper.hashed_embed_id)?.encrypted_embed_key, encryptedEmbedKey);
    assert.equal(JSON.stringify(saved).includes(source.html_source), false);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,chats.persistence.client-encrypted
  it("uses an explicit Team chat scope to decrypt an authorized on-demand embed", async () => {
    writeLegacySession();
    saveSyncCache(emptyCache());
    const client = OpenMatesClient.load();
    const teamId = "33333333-3333-4333-8333-333333333333";
    const teamKey = new Uint8Array(32).fill(3);
    const chatKey = new Uint8Array(32).fill(7);
    const embedKey = new Uint8Array(32).fill(9);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, teamKey);
    const encryptedContent = await encryptWithAesGcmCombined(JSON.stringify({ type: "diagram_html", title: "Team map" }), embedKey);
    const cache = { ...emptyCache(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: chatId, encrypted_chat_key: encryptedChatKey }, messages: [] }] };
    saveSyncCache(cache, teamId);
    (client as any).ensureSynced = async () => cache;
    (client as any).getChatWrappingKey = async (scope: string | null) => {
      assert.equal(scope, teamId);
      return teamKey;
    };
    const wrapper = { hashed_embed_id: createHash("sha256").update(embedId).digest("hex"),
      hashed_chat_id: createHash("sha256").update(chatId).digest("hex"), key_type: "chat",
      encrypted_embed_key: await encryptBytesWithAesGcm(embedKey, chatKey) };
    let deliver!: (value: { payload: Record<string, unknown> }) => void;
    const ws = {
      waitForMessage: (_type: string, predicate: (payload: unknown) => boolean) => new Promise((resolve) => {
        deliver = (value) => { assert.ok(predicate(value.payload)); resolve(value); };
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        assert.equal(type, "request_embed");
        assert.deepEqual(payload, { embed_id: embedId, chat_id: chatId, team_id: teamId });
        deliver({ payload: { payload: { embed_id: embedId, chat_id: chatId, already_encrypted: true,
          status: "finished", type: await encryptWithAesGcmCombined("diagram_html", embedKey),
          content: encryptedContent, embed_keys: [wrapper] } } });
      },
      close: () => {},
    };
    (client as any).openWsClient = async () => ({ ws });
    const embed = await client.getEmbed(embedId, { teamId, chatId });
    assert.equal(embed.type, "diagram_html");
    assert.equal(embed.content?.title, "Team map");
    assert.equal(loadSyncCache(teamId)?.embeds.find((row) => row.embed_id === embedId)?.encrypted_content, encryptedContent);
    assert.equal(loadSyncCache()?.embeds.some((row) => row.embed_id === embedId), false);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("preserves authorized lookup failures and does not cache a missing or denied embed", async () => {
    writeLegacySession();
    saveSyncCache(emptyCache());
    const client = OpenMatesClient.load();
    (client as any).ensureSynced = async () => emptyCache();
    for (const reason of ["Embed not found", "Access denied"]) {
      let rejectReply!: (error: Error) => void;
      const ws = {
        waitForMessage: () => new Promise((_resolve, reject) => { rejectReply = reject; }),
        sendAsync: async (type: string, payload: Record<string, unknown>) => {
          assert.equal(type, "request_embed");
          assert.deepEqual(payload, { embed_id: embedId, chat_id: chatId });
          queueMicrotask(() => rejectReply(new Error(reason)));
        },
        close: () => {},
      };
      (client as any).openWsClient = async () => ({ ws });
      await assert.rejects(client.getEmbed(embedId, { chatId }), new RegExp(reason));
      assert.deepEqual(loadSyncCache()?.embeds, []);
      assert.deepEqual(loadSyncCache()?.embedKeys, []);
    }
  });
});

describe("CLI streamed embed persistence", () => {
  const versionResponse = (encryptedSnapshot: string) => ({
    ok: true, status: 200,
    data: { embed_id: "embed-123", version_number: 1,
      rows: [{ version_number: 1, encrypted_snapshot: encryptedSnapshot, encrypted_patch: null }] },
  });
  const diffReceipt = (payload: Record<string, any>) => ({
    request_id: payload.request_id,
    embed_id: payload.embed_id,
    version_number: payload.version_number,
    canonical_source: "version_row",
    canonical_digest: createHash("sha256").update(JSON.stringify([
      payload.encrypted_snapshot ?? null, payload.encrypted_patch ?? null,
    ])).digest("hex"),
  });
  const streamedEmbed = (content: string, version = 1) => ({
    embed_id: "embed-123", type: "diagram_html", content, status: "finished", version_number: version,
    version_history_rows: [{ embed_id: "embed-123", version_number: version,
      snapshot: content, created_at: 1780000000 + version }],
  });
  const persistenceArgs = (ws: unknown, content: string, version = 1) => ({
    ws, embeds: [streamedEmbed(content, version)], chatId: "chat-123",
    chatKeyBytes: new Uint8Array(32).fill(7), fallbackMessageId: "message-123",
    ownerId: "user-uuid-123",
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,storage.versions.bounded-reconstruction
  it("uses the same deterministic parent embed key across version updates", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const masterKey = new Uint8Array(32);
    const chatKey = new Uint8Array(32).fill(7);
    const frames: { type: string; payload: Record<string, any> }[] = [];
    const ws = {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        await new Promise<void>((resolve) => setImmediate(resolve));
        const sent = frames.at(-1);
        assert.ok(sent && match(sent.payload));
        return { payload: type === "store_embed_keys_confirmed"
          ? { created_count: 2, failed_count: 0 }
          : type === "store_embed_diff_confirmed" ? diffReceipt(sent.payload) : sent.payload };
      },
      sendAsync: async (type: string, payload: Record<string, any>) => {
        frames.push({ type, payload });
      },
    };
    (client as any).http.get = async () => ({ ok: false, status: 404 });

    const replacementPatch = "--- v1\n+++ v2\n@@ -1,1 +1,2 @@\n-version one\n+version two\n+";
    const persist = async (content: string, version: number) => {
      await (client as any).persistStreamedEmbeds({
        ws,
        embeds: [{
          embed_id: "embed-123",
          type: "code-code",
          content,
          status: "finished",
          version_number: version,
          version_history_rows: [{
            embed_id: "embed-123",
            version_number: version,
            snapshot: content,
            ...(version > 1 ? { patch: replacementPatch } : {}),
            created_at: 1780000000 + version,
          }],
        }],
        chatId: "chat-123",
        chatKeyBytes: chatKey,
        fallbackMessageId: "message-123",
        ownerId: "user-uuid-123",
      });
    };

    await persist("version one", 1);
    await persist("version two\n", 2);

    const keyFrames = frames.filter((frame) => frame.type === "store_embed_keys");
    const diffFrames = frames.filter((frame) => frame.type === "store_embed_diff");
    const expectedUserHash = createHash("sha256").update("user-uuid-123").digest("hex");
    const storeFrames = frames.filter((frame) => frame.type === "store_embed");
    assert.equal(storeFrames[0].payload.hashed_user_id, expectedUserHash);
    assert.equal(keyFrames.length, 2);
    assert.equal(diffFrames.length, 2);
    assert.ok(
      frames.findIndex((frame) => frame.type === "store_embed_keys") <
        frames.findIndex((frame) => frame.type === "store_embed_diff"),
    );

    const firstMasterWrapper = keyFrames[0].payload.keys.find(
      (entry: Record<string, unknown>) => entry.key_type === "master",
    );
    const secondMasterWrapper = keyFrames[1].payload.keys.find(
      (entry: Record<string, unknown>) => entry.key_type === "master",
    );
    const firstKey = await decryptBytesWithAesGcm(firstMasterWrapper.encrypted_embed_key, masterKey);
    const secondKey = await decryptBytesWithAesGcm(secondMasterWrapper.encrypted_embed_key, masterKey);
    assert.ok(firstKey);
    assert.ok(secondKey);
    assert.deepEqual(secondKey, firstKey);
    assert.equal(
      await decryptWithAesGcmCombined(diffFrames[0].payload.encrypted_snapshot, firstKey),
      "version one",
    );
    assert.equal(
      await decryptWithAesGcmCombined(diffFrames[1].payload.encrypted_snapshot, secondKey),
      "version two\n",
    );
    assert.equal(
      await decryptWithAesGcmCombined(diffFrames[1].payload.encrypted_patch, secondKey),
      replacementPatch,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=chats.completion.recovery-takeover,storage.versions.bounded-reconstruction
  it("waits for the correlated durable v1 receipt before continuing to recovery", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const frames: Array<{ type: string; payload: Record<string, any> }> = [];
    let releaseDiff!: (payload: Record<string, unknown>) => void;
    const diffAck = new Promise<Record<string, unknown>>((resolve) => { releaseDiff = resolve; });
    (client as any).http.get = async () => ({ ok: false, status: 404 });
    const ws = {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        if (type === "store_embed_diff_confirmed") {
          const receipt = await diffAck;
          assert.equal(match({ ...receipt, request_id: "unrelated-request" }), false);
          assert.ok(match(receipt));
          return { payload: receipt };
        }
        await new Promise<void>((resolve) => setImmediate(resolve));
        const sent = frames.at(-1);
        assert.ok(sent && match(sent.payload));
        return { payload: type === "store_embed_keys_confirmed"
          ? { created_count: 2, failed_count: 0 } : sent.payload };
      },
      sendAsync: async (type: string, payload: Record<string, any>) => { frames.push({ type, payload }); },
    };
    let settled = false;
    const persist = (client as any).persistStreamedEmbeds(persistenceArgs(ws, "<html>first</html>"))
      .finally(() => { settled = true; });
    for (let i = 0; i < 30 && !frames.some((frame) => frame.type === "store_embed_diff"); i++) {
      await new Promise<void>((resolve) => setImmediate(resolve));
    }
    const sent = frames.find((frame) => frame.type === "store_embed_diff");
    assert.ok(sent);
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.equal(settled, false);
    releaseDiff(diffReceipt(sent.payload));
    await persist;
    assert.equal(settled, true);
  });

  // contract-test: supporting surface=sdks.npm assertions=storage.versions.bounded-reconstruction,chats.completion.recovery-takeover
  it("reuses an existing identical v1 without sending new randomized ciphertext", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const frames: Array<{ type: string; payload: Record<string, any> }> = [];
    const chatKey = new Uint8Array(32).fill(7);
    const embedKey = await (await import("../src/crypto.ts")).deriveEmbedKeyFromChatKey(chatKey, "embed-123");
    const existingCiphertext = await encryptWithAesGcmCombined("<html>same</html>", embedKey);
    let requestedPath = "";
    (client as any).http.get = async (path: string) => {
      requestedPath = path;
      return versionResponse(existingCiphertext);
    };
    const ws = {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        await new Promise<void>((resolve) => setImmediate(resolve));
        const sent = frames.at(-1);
        assert.ok(sent && match(sent.payload));
        return { payload: type === "store_embed_keys_confirmed"
          ? { created_count: 2, failed_count: 0 } : sent.payload };
      },
      sendAsync: async (type: string, payload: Record<string, any>) => { frames.push({ type, payload }); },
    };
    await (client as any).persistStreamedEmbeds(persistenceArgs(ws, "<html>same</html>"));
    assert.match(requestedPath, /versions\/1\?capability=bounded-v1&chat_id=chat-123/);
    assert.equal(frames.filter((frame) => frame.type === "store_embed_diff").length, 0);
  });

  // contract-test: supporting surface=sdks.npm assertions=storage.versions.bounded-reconstruction
  it("rejects an existing v1 with different plaintext without overwriting it", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const frames: Array<{ type: string; payload: Record<string, any> }> = [];
    const embedKey = await (await import("../src/crypto.ts")).deriveEmbedKeyFromChatKey(
      new Uint8Array(32).fill(7), "embed-123");
    const existingCiphertext = await encryptWithAesGcmCombined("<html>other</html>", embedKey);
    (client as any).http.get = async () => versionResponse(existingCiphertext);
    const ws = {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        await new Promise<void>((resolve) => setImmediate(resolve));
        const sent = frames.at(-1);
        assert.ok(sent && match(sent.payload));
        return { payload: type === "store_embed_keys_confirmed"
          ? { created_count: 2, failed_count: 0 } : sent.payload };
      },
      sendAsync: async (type: string, payload: Record<string, any>) => { frames.push({ type, payload }); },
    };
    await assert.rejects(
      (client as any).persistStreamedEmbeds(persistenceArgs(ws, "<html>changed</html>")),
      /does not match streamed source/,
    );
    assert.equal(frames.filter((frame) => frame.type === "store_embed_diff").length, 0);
  });

  // contract-test: supporting surface=sdks.npm assertions=chats.completion.recovery-takeover,storage.versions.bounded-reconstruction
  it("surfaces timeout and mismatched durable history receipts", async () => {
    for (const failure of ["timeout", "digest"] as const) {
      writeLegacySession();
      const client = OpenMatesClient.load();
      const frames: Array<{ type: string; payload: Record<string, any> }> = [];
      (client as any).http.get = async () => ({ ok: false, status: 404 });
      const ws = {
        waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
          await new Promise<void>((resolve) => setImmediate(resolve));
          const sent = frames.at(-1);
          assert.ok(sent && match(sent.payload));
          if (type === "store_embed_diff_confirmed") {
            if (failure === "timeout") throw new Error("durable receipt timed out");
            return { payload: { ...diffReceipt(sent.payload), canonical_digest: "0".repeat(64) } };
          }
          return { payload: type === "store_embed_keys_confirmed"
            ? { created_count: 2, failed_count: 0 } : sent.payload };
        },
        sendAsync: async (type: string, payload: Record<string, any>) => { frames.push({ type, payload }); },
      };
      await assert.rejects(
        (client as any).persistStreamedEmbeds(persistenceArgs(ws, "<html>source</html>")),
        failure === "timeout" ? /durable receipt timed out/ : /durable receipt did not match/,
      );
      assert.equal(frames.filter((frame) => frame.type === "store_embed_diff").length, 1);
    }
  });
});

describe("connected account payload builders", () => {
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("rejects token or plaintext identity fields in the chat-visible directory", () => {
    assert.throws(
      () => buildConnectedAccountDirectoryPayload([
        {
          connected_account_id: "acct-1",
          app_id: "calendar",
          account_ref: "work",
          label: "Work",
          capabilities: ["read"],
          provider_email: "person@example.com",
        } as never,
      ]),
      /forbidden field: provider_email/,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("builds token-broker requests without putting refresh tokens in chat payloads", () => {
    const request = buildTurnTokenRefsRequestPayload({
      chatId: "chat-1",
      messageId: "msg-1",
      refs: [
        {
          connected_account_id: "acct-1",
          app_id: "calendar",
          provider_id: "google",
          allowed_actions: ["read"],
          refresh_token_envelope: { refresh_token: "refresh-secret" },
          action_scope: { calendar_id: "primary" },
        },
      ],
    });
    const directory = buildConnectedAccountDirectoryPayload([
        {
          connected_account_id: "acct-1",
          app_id: "calendar",
          provider_id: "google",
          account_ref: "work",
          label: "Work",
          capabilities: ["read"],
      },
    ]);

    assert.equal(request.refs[0]?.refresh_token_envelope.refresh_token, "refresh-secret");
    assert.equal(request.refs[0]?.provider_id, "google");
    assert.equal(directory[0]?.provider_id, "google");
    assert.equal(JSON.stringify(directory).includes("refresh-secret"), false);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("posts connected-account cancel requests without token refs", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/connected-accounts/actions/action-1/cancel");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ action_id: "action-1", status: "cancelled", receipt: {} }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.cancelConnectedAccountAction({
        actionId: "action-1",
        chatId: "chat-1",
        messageId: "message-1",
      });

      assert.deepEqual(JSON.parse(requestBody), { chat_id: "chat-1", message_id: "message-1" });
      assert.equal(JSON.stringify(requestBody).includes("refresh"), false);
      assert.deepEqual(result, { action_id: "action-1", status: "cancelled", receipt: {} });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("posts connected-account undo requests with only the opaque turn token ref", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/connected-accounts/actions/action-1/undo");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            action_id: "action-1",
            status: "undone",
            undo_type: "delete_created_event",
            events: [],
            receipt: {},
          }),
        );
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.undoConnectedAccountAction({
        actionId: "action-1",
        chatId: "chat-1",
        messageId: "message-1",
        turnTokenRef: "turn-ref-1",
      });

      assert.deepEqual(JSON.parse(requestBody), {
        chat_id: "chat-1",
        message_id: "message-1",
        turn_token_ref: "turn-ref-1",
      });
      assert.equal(JSON.stringify(requestBody).includes("refresh"), false);
      assert.deepEqual(result, {
        action_id: "action-1",
        status: "undone",
        undo_type: "delete_created_event",
        events: [],
        receipt: {},
      });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

import { coalesceMemoryRequestMessages, parseMemoryRequest, mergeMemoryRequests } from "../../ui/src/utils/appMemoryRequests.js";

describe("memory request system messages", () => {
  // contract-test: direct surface=cli assertions=app-memories.conversation.request-convergence
  it("records actual available counts without implying consent", () => {
    const message = buildAppSettingsMemoryRequestSystemMessage({
      userMessageId: "user-message-id",
      requestId: "request-id",
      requestedKeys: ["mail-writing_styles"],
      createdAt: 1780000000,
      entryCounts: new Map([["mail-writing_styles", 1]]),
    });
    assert.equal(message.message_id, "request-id");
    const payload = JSON.parse(message.content);
    assert.equal(payload.categories[0].entryCount, 1);
    assert.equal(payload.action, undefined);
  });

  // contract-test: direct surface=cli assertions=app-memories.conversation.request-convergence
  it("represents an unavailable count as unknown rather than empty", () => {
    const message = buildAppSettingsMemoryRequestSystemMessage({
      userMessageId: "user-message-id",
      requestId: "request-id",
      requestedKeys: ["mail-writing_styles"],
      createdAt: 1780000000,
    });
    assert.equal(JSON.parse(message.content).categories[0].entryCount, null);
  });

  // contract-test: direct surface=cli assertions=app-memories.conversation.request-convergence
  it("converges legacy CLI/web duplicates in both orders without altering consent", () => {
    const base = { type: "app_settings_memories_request", request_id: "request-id", user_message_id: "user-id", requested_keys: ["mail-writing_styles"] };
    const legacyCli = { role: "system", clientMessageId: "request-id", content: JSON.stringify({ ...base, categories: [{ appId: "mail", itemType: "writing_styles", entryCount: 0 }] }) };
    const legacyWeb = { role: "system", clientMessageId: "web-random-id", content: JSON.stringify({ ...base, categories: [{ appId: "mail", itemType: "writing_styles", entryCount: 1 }] }) };
    const decision = { role: "system", clientMessageId: "decision-id", content: JSON.stringify({ type: "app_settings_memories_response", action: "rejected", user_message_id: "user-id" }) };
    for (const pair of [[legacyCli, legacyWeb], [legacyWeb, legacyCli]]) {
      const result = coalesceMemoryRequestMessages([...pair, decision]);
      assert.equal(result.length, 2);
      assert.equal(JSON.parse(result[0].content).categories[0].entryCount, 1);
      assert.equal(result[1], decision);
      assert.equal(JSON.parse(legacyCli.content).categories[0].entryCount, 0);
    }
  });

  // contract-test: direct surface=cli assertions=app-memories.conversation.request-convergence
  it("keeps measured zero and distinct request identities separate", () => {
    const first = buildAppSettingsMemoryRequestSystemMessage({ userMessageId: "user-id", requestId: "a", requestedKeys: ["mail-writing_styles"], entryCounts: new Map([["mail-writing_styles", 0]]), createdAt: 1 });
    const second = buildAppSettingsMemoryRequestSystemMessage({ userMessageId: "user-id", requestId: "b", requestedKeys: ["mail-writing_styles"], createdAt: 2 });
    assert.equal(parseMemoryRequest(first.content, "a")?.categories[0].entryCount, 0);
    assert.equal(coalesceMemoryRequestMessages([first, second]).length, 2);
    assert.throws(() => mergeMemoryRequests(JSON.parse(first.content), JSON.parse(second.content)), /distinct/);
    assert.equal(parseMemoryRequest('{"type":"app_settings_memories_request","request_id":"a","user_message_id":"u","requested_keys":[],"categories":[null]}'), null);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("builds the request artifact without approving memory content", () => {
    const message = buildAppSettingsMemoryRequestSystemMessage({
      userMessageId: "user-message-id",
      requestId: "request-id",
      requestedKeys: ["books-currently_reading"],
      createdAt: 1780000000,
    });

    assert.equal(message.message_id, "request-id");
    assert.equal(message.role, "system");
    assert.equal(message.created_at, 1780000000);
    assert.equal(message.user_message_id, "user-message-id");

    const payload = JSON.parse(message.content);
    assert.equal(payload.type, "app_settings_memories_request");
    assert.equal(payload.user_message_id, "user-message-id");
    assert.equal(payload.request_id, "request-id");
    assert.deepEqual(payload.requested_keys, ["books-currently_reading"]);
    assert.deepEqual(payload.categories, [
      { appId: "books", itemType: "currently_reading", entryCount: null },
    ]);
    assert.notEqual(payload.type, "app_settings_memories_response");
    assert.equal(payload.action, undefined);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("builds an included response artifact only for explicit approval", () => {
    const message = buildAppSettingsMemoryResponseSystemMessage({
      userMessageId: "user-message-id",
      messageId: "response-id",
      action: "included",
      categories: [{ appId: "books", itemType: "currently_reading", entryCount: 2 }],
      createdAt: 1780000001,
    });

    assert.equal(message.message_id, "response-id");
    assert.equal(message.role, "system");
    assert.equal(message.created_at, 1780000001);
    assert.equal(message.user_message_id, "user-message-id");

    const payload = JSON.parse(message.content);
    assert.equal(payload.type, "app_settings_memories_response");
    assert.equal(payload.user_message_id, "user-message-id");
    assert.equal(payload.action, "included");
    assert.deepEqual(payload.categories, [
      { appId: "books", itemType: "currently_reading", entryCount: 2 },
    ]);
  });
});

describe("task update job helpers", () => {
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("builds encrypted task event system messages without plaintext leakage", async () => {
    const chatKey = new Uint8Array(32).fill(11);
    const systemMessage = await buildTaskEventSystemMessage({
      chatKey,
      userMessageId: "user-message-1",
      event: {
        event_id: "task-event-1",
        chat_id: "chat-1",
        task_id: "TASK-123",
        short_id: "TASK-123",
        event_type: "created",
        title: "Book flights",
        status: "todo",
        created_at: 1780000000,
      },
    });

    assert.equal(systemMessage.role, "system");
    assert.equal(systemMessage.message_id, "task-event-task-event-1");
    assert.equal(systemMessage.user_message_id, "user-message-1");
    assert.equal(systemMessage.created_at, 1780000000);
    assert.equal(systemMessage.encrypted_content.includes("Book flights"), false);
    const decrypted = await decryptWithAesGcmCombined(systemMessage.encrypted_content, chatKey);
    assert.match(decrypted, /TASK-123 created/);
    assert.match(decrypted, /Book flights/);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("builds task update job persist payloads with only encrypted task content", () => {
    const payload = buildTaskUpdateJobPersistPayload({
      jobId: "task-update-job-1",
      leaseToken: "lease-token",
      leaseGeneration: 2,
      expectedTaskVersion: 4,
      encryptedTaskPayload: {
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 5,
      },
      encryptedTaskEventMessage: "cipher-system-event",
    });

    assert.deepEqual(payload, {
      protocol_version: 1,
      job_id: "task-update-job-1",
      lease_token: "lease-token",
      lease_generation: 2,
      expected_task_version: 4,
      encrypted_task_payload: {
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 5,
      },
      encrypted_task_event_message: "cipher-system-event",
    });
    assert.throws(
      () => buildTaskUpdateJobPersistPayload({
        jobId: "task-update-job-1",
        leaseToken: "lease-token",
        leaseGeneration: 2,
        expectedTaskVersion: 4,
        encryptedTaskPayload: { title: "Book flights" },
        encryptedTaskEventMessage: "cipher-system-event",
      }),
      /plaintext/,
    );

    const createPayload = buildTaskUpdateJobPersistPayload({
      jobId: "task-update-job-2",
      leaseToken: "lease-token",
      leaseGeneration: 3,
      expectedTaskVersion: 0,
      encryptedTaskPayload: {
        task_id: "task-1",
        short_id: undefined,
        plan_id: null,
        due_at: null,
        task_type: "verification",
        verification_id: "verify-1",
        parent_task_id: "parent-1",
        queue_state: "waiting_for_user",
        blocked_reason_code: "needs_input",
        ai_execution_state: "waiting_for_user",
        encrypted_task_key: "cipher-key",
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 1,
      },
    });
    assert.deepEqual(createPayload.encrypted_task_payload, {
      task_id: "task-1",
      task_type: "verification",
      verification_id: "verify-1",
      parent_task_id: "parent-1",
      queue_state: "waiting_for_user",
      blocked_reason_code: "needs_input",
      ai_execution_state: "waiting_for_user",
      encrypted_task_key: "cipher-key",
      encrypted_title: "cipher-title",
      encrypted_description: "cipher-description",
      version: 1,
    });
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("keeps task update jobs only when the current response emitted a matching event", () => {
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-active-turn",
          task_id: "TASK-1",
          chat_id: "chat-active",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [
          {
            event_id: "event-active",
            chat_id: "chat-active",
            task_id: "TASK-1",
            event_type: "updated",
            task_update_job_id: "job-active-turn",
          },
        ],
      ),
      true,
    );
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-same-chat-stale",
          task_id: "TASK-STALE",
          chat_id: "chat-active",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [],
      ),
      false,
    );
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-stale",
          task_id: "TASK-STALE",
          chat_id: "chat-old",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [],
      ),
      false,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("detects explicit Tasks app-skill messages", () => {
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@skill:tasks:create create launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@skill:tasks:search find launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@Tasks-Create create launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@Tasks-Search find launch tasks"),
      true,
    );
    assert.equal(messageExplicitlyRequestsTasksAppSkill("create launch tasks"), false);
  });
});

describe("TUI one-shot send socket warmup", () => {
  const sendOptions = { taskUpdateJobs: true, projectFileJobs: true, remoteCommandJobs: true, interactiveHuman: true };

  function fixture() {
    writeLegacySession();
    const client = OpenMatesClient.load();
    let open = true;
    let closeCount = 0;
    const closeHandlers: Array<() => void> = [];
    const ws = {
      isOpen: () => open,
      close: () => { if (open) { open = false; closeCount++; closeHandlers.forEach(handler => handler()); } },
      onClose: (handler: () => void) => { closeHandlers.push(handler); return () => {}; },
    };
    const opened = { ws, session: client.getSession(), ownerId: "11111111-1111-4111-8111-111111111111" };
    const internal = client as unknown as {
      interactiveViewerAllowed: boolean;
      openWsClient: (options: typeof sendOptions & { signal?: AbortSignal }) => Promise<typeof opened>;
      warmSendSocket: () => void;
      takePreparedSendSocket: (options: typeof sendOptions, teamId: string | null) => Promise<typeof opened | null>;
      preparedSendSocket: { pending: Promise<void>; expiresAt: number } | null;
    };
    internal.interactiveViewerAllowed = true;
    let opens = 0;
    internal.openWsClient = async options => {
      const { signal, ...flags } = options;
      assert.deepEqual(flags, sendOptions);
      assert.ok(signal);
      opens++;
      return opened;
    };
    return { client, internal, opened, getOpens: () => opens, getCloseCount: () => closeCount };
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  it("borrows an identical live socket once after a persisted-session recheck", async () => {
    const { client, internal, opened, getOpens, getCloseCount } = fixture();
    internal.warmSendSocket();
    await internal.preparedSendSocket?.pending;
    assert.equal(await internal.takePreparedSendSocket(sendOptions, null), opened);
    assert.equal(await internal.takePreparedSendSocket(sendOptions, null), null);
    assert.equal(getOpens(), 1);
    client.endInteractiveViewerSession();
    assert.equal(getCloseCount(), 0, "borrowed socket belongs to the send");
    opened.ws.close();
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  for (const tokenChange of ["same refresh authority", "different refresh authority"] as const) {
    it(`${tokenChange} when auth issues a new WebSocket token`, async () => {
      const { client, internal, opened, getCloseCount } = fixture();
      const refreshHash = createHash("sha256").update("test-refresh-token").digest("hex");
      const initialToken = `${refreshHash}:100:${"a".repeat(64)}`;
      client.getSession()!.wsToken = initialToken;
      const stored = JSON.parse(readFileSync(sessionPath, "utf8")) as Record<string, unknown>;
      stored.wsToken = initialToken;
      writeFileSync(sessionPath, JSON.stringify(stored), { mode: 0o600 });
      internal.warmSendSocket();
      await internal.preparedSendSocket?.pending;

      stored.wsToken = `${tokenChange === "same refresh authority" ? refreshHash : "f".repeat(64)}:200:${"b".repeat(64)}`;
      writeFileSync(sessionPath, JSON.stringify(stored), { mode: 0o600 });
      const borrowed = await internal.takePreparedSendSocket(sendOptions, null);
      if (tokenChange === "same refresh authority") {
        assert.equal(borrowed, opened);
        assert.equal(getCloseCount(), 0);
        opened.ws.close();
      } else {
        assert.equal(borrowed, null);
        assert.equal(getCloseCount(), 1);
      }
      client.endInteractiveViewerSession();
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  for (const change of ["account", "session", "createdAt", "masterKey", "cookie", "options", "expired", "closed", "team"] as const) {
    it(`closes an idle socket and rejects changed ${change}`, async () => {
      const { client, internal, opened, getCloseCount } = fixture();
      internal.warmSendSocket();
      await internal.preparedSendSocket?.pending;
      let options = sendOptions;
      if (change === "options") options = { ...sendOptions, taskUpdateJobs: false };
      else if (change === "expired") internal.preparedSendSocket!.expiresAt = performance.now() - 1;
      else if (change === "closed") opened.ws.close();
      else if (change === "team") client.setActiveTeamId("22222222-2222-4222-8222-222222222222");
      else {
        const stored = JSON.parse(readFileSync(sessionPath, "utf8")) as Record<string, unknown>;
        if (change === "account") stored.hashedEmail = "other-account";
        if (change === "session") stored.sessionId = "other-session";
        if (change === "createdAt") stored.createdAt = Number(stored.createdAt) + 1;
        if (change === "masterKey") stored.masterKeyExportedB64 = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=";
        if (change === "cookie") stored.cookies = { auth_refresh_token: "rotated-by-memory-auth" };
        writeFileSync(sessionPath, JSON.stringify(stored), { mode: 0o600 });
      }
      assert.equal(await internal.takePreparedSendSocket(options, null), null);
      assert.equal(getCloseCount(), 1);
      client.endInteractiveViewerSession();
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  it("rejects a rotated Team key", async () => {
    const { client, internal, getCloseCount } = fixture();
    const teamId = "22222222-2222-4222-8222-222222222222";
    client.setActiveTeamId(teamId);
    saveLocalTeamKey("test-hashed-email", teamId, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
    internal.warmSendSocket();
    await internal.preparedSendSocket?.pending;
    saveLocalTeamKey("test-hashed-email", teamId, "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=");
    assert.equal(await internal.takePreparedSendSocket(sendOptions, teamId), null);
    assert.equal(getCloseCount(), 1);
    client.endInteractiveViewerSession();
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("closes an unused socket when the TUI ends", async () => {
    const { client, internal, getCloseCount } = fixture();
    internal.warmSendSocket();
    await internal.preparedSendSocket?.pending;
    client.endInteractiveViewerSession();
    assert.equal(getCloseCount(), 1);
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("joins the identical pending warmup without opening a second socket", async () => {
    const { client, internal, opened } = fixture();
    let resolveOpen!: (value: typeof opened) => void;
    let opens = 0;
    internal.openWsClient = () => {
      opens++;
      return new Promise(resolve => { resolveOpen = resolve; });
    };
    internal.warmSendSocket();
    const borrowing = internal.takePreparedSendSocket(sendOptions, null);
    resolveOpen(opened);
    assert.equal(await borrowing, opened);
    assert.equal(opens, 1);
    client.endInteractiveViewerSession();
    opened.ws.close();
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("bounds a stalled optional warmup and cancels its late socket", async () => {
    const { client, internal, opened, getCloseCount } = fixture();
    let resolveOpen!: (value: typeof opened) => void;
    let signal: AbortSignal | undefined;
    internal.openWsClient = options => {
      signal = options.signal;
      return new Promise(resolve => { resolveOpen = resolve; });
    };
    internal.warmSendSocket();
    const startedAt = performance.now();
    assert.equal(await internal.takePreparedSendSocket(sendOptions, null), null);
    assert.ok(performance.now() - startedAt < 250, "cold send must not await the optional open timeout");
    assert.equal(signal?.aborted, true);
    resolveOpen(opened);
    await new Promise<void>(resolve => setImmediate(resolve));
    assert.equal(getCloseCount(), 1, "a cancelled late upgrade cannot retain an idle socket");
    client.endInteractiveViewerSession();
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle
  it("falls back after a failed optional warmup", async () => {
    const { client, internal } = fixture();
    internal.openWsClient = async () => { throw new Error("warm socket unavailable"); };
    internal.warmSendSocket();
    await internal.preparedSendSocket?.pending;
    assert.equal(await internal.takePreparedSendSocket(sendOptions, null), null);
    client.endInteractiveViewerSession();
  });

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle,auth.session.isolation
  it("cancels stalled warm auth before foreground memory validation and ignores its late cookie", async () => {
    let authCalls = 0;
    let resolveFirstAuth!: () => void;
    const firstAuth = new Promise<void>(resolve => { resolveFirstAuth = resolve; });
    let stalledResponse: ServerResponse | null = null;
    let upgrades = 0;
    const server = createServer((request, response) => {
      response.setHeader("content-type", "application/json");
      if (request.url === "/v1/auth/session") {
        authCalls++;
        if (authCalls === 1) { stalledResponse = response; resolveFirstAuth(); return; }
        response.setHeader("set-cookie", "auth_refresh_token=foreground-cookie; Path=/; HttpOnly");
        response.end(JSON.stringify({ success: true, ws_token: "foreground-ws-token", user: { id: "owner-id" } }));
        return;
      }
      if (request.url === "/v1/sdk/memories") {
        response.end(JSON.stringify({ memories: [] }));
        return;
      }
      response.writeHead(404);
      response.end(JSON.stringify({}));
    });
    server.on("upgrade", (_request, socket) => { upgrades++; socket.destroy(); });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const internal = client as unknown as { interactiveViewerAllowed: boolean; warmSendSocket: () => void };
      internal.interactiveViewerAllowed = true;
      internal.warmSendSocket();
      await firstAuth;
      const startedAt = performance.now();
      await assert.rejects(client.sendMessage({ message: "foreground turn", piiDetection: false,
        onPrivacyPrepared: () => { throw new Error("stop after fresh memory auth"); } }),
      /stop after fresh memory auth/);
      assert.ok(performance.now() - startedAt < 2_000, "foreground memory auth must not wait on stalled optional auth");
      assert.equal(authCalls, 2);
      stalledResponse?.setHeader("set-cookie", "auth_refresh_token=stale-warm-cookie; Path=/; HttpOnly");
      stalledResponse?.end(JSON.stringify({ success: true, ws_token: "stale-warm-token", user: { id: "wrong-owner" } }));
      await new Promise<void>(resolve => setTimeout(resolve, 20));
      assert.equal(client.getSession()?.cookies.auth_refresh_token, "foreground-cookie");
      assert.equal((JSON.parse(readFileSync(sessionPath, "utf8")) as { cookies: { auth_refresh_token: string } }).cookies.auth_refresh_token, "foreground-cookie");
      assert.equal(upgrades, 0);
      client.endInteractiveViewerSession();
    } finally {
      stalledResponse?.end();
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });
});

describe("CLI saved-chat recovery preflight", () => {
  // contract-test: supporting surface=sdks.npm assertions=auth.session.isolation
  it("requires a session before requesting the Personal routing directory", async () => {
    const client = OpenMatesClient.load({ apiUrl: "http://127.0.0.1:1", loadStoredSession: false });
    let requests = 0;
    (client as unknown as { http: { get: () => Promise<never> } }).http.get = async () => {
      requests++;
      throw new Error("unexpected HTTP request");
    };
    await assert.rejects(client.listPersonalProjectRoutingDirectory(), /Not logged in/);
    assert.equal(requests, 0);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,chats.completion.lease-fenced
  for (const scenario of ["unavailable-old-server", "unavailable-failure-signal", "unavailable-failure-rejected", "available", "routing-directory", "supplied-memory", "routing-ack-rejected", "details-ack-rejected"] as const) it(`keeps v2 admission ahead of Project resolution: ${scenario}`, async () => {
    const projectsAvailable = scenario === "available" || scenario === "routing-directory" || scenario === "supplied-memory" || scenario.endsWith("ack-rejected");
    const failureSignalAvailable = scenario === "unavailable-failure-signal" || scenario === "unavailable-failure-rejected" || scenario.endsWith("ack-rejected");
    const disabledProjectId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    const disabledProjectKey = new Uint8Array(32).fill(7);
    const disabledProject = {
      project_id: disabledProjectId, archived: false,
      encrypted_project_key: await encryptBytesWithAesGcm(disabledProjectKey, new Uint8Array(32)),
      encrypted_name: await encryptWithAesGcmCombined("Disabled Project", disabledProjectKey),
      encrypted_description: await encryptWithAesGcmCombined("Excluded from automatic routing", disabledProjectKey),
    };
    const projectList = { projects: scenario === "available" ? [disabledProject] : [] };
    const routingDirectory = { project_candidates: [{
      project_id: disabledProjectId, encrypted_project_key: disabledProject.encrypted_project_key,
      encrypted_name: disabledProject.encrypted_name, encrypted_description: disabledProject.encrypted_description,
      auto_selection: true, focus_activation_policy: "delayed",
    }] };
    const suppliedCandidates = [{ project_id: disabledProjectId, name: "Caller disabled Project",
      summary: "Preserve legacy caller routing", auto_selection: false, focus_activation_policy: "delayed" as const }];
    let legacyListRequests = 0;
    let routingDirectoryRequests = 0;
    let settingsRequests = 0;
    let admitted = false;
    let candidatesWaitingAtAdmission = false;
    let deferredProjects: ServerResponse | null = null;
    let admittedTurnId: string | null = null;
    let admittedFrame: Record<string, unknown> | null = null;
    const contextFrames: Array<Record<string, unknown>> = [];
    let failureFrame: Record<string, unknown> | null = null;
    const debugLines: string[] = [];
    const previousDebug = process.env.OPENMATES_DEBUG;
    const previousConsoleError = console.error;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      response.setHeader("content-type", "application/json");
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token",
          user: { id: "11111111-1111-4111-8111-111111111111" } }));
      } else if (request.method === "GET" && request.url === "/v1/sdk/memories") {
        response.end(JSON.stringify({ memories: [] }));
      } else if (request.method === "GET" && request.url === "/v1/projects/routing-directory") {
        routingDirectoryRequests++;
        if (!admitted) { deferredProjects = response; return; }
        response.end(JSON.stringify(routingDirectory));
      } else if (request.method === "GET" && request.url === "/v1/projects") {
        legacyListRequests++;
        if (!admitted) { deferredProjects = response; return; }
        response.writeHead(projectsAvailable ? 200 : 503);
        response.end(JSON.stringify(projectsAvailable ? projectList : { message: "temporarily unavailable" }));
      } else if (request.method === "GET" && request.url === `/v1/projects/${disabledProjectId}/settings`) {
        settingsRequests++;
        response.end(JSON.stringify({ settings: { auto_selection: false, focus_activation_policy: "delayed" } }));
      } else if (request.method === "GET" && request.url?.startsWith("/v1/user-tasks")) {
        response.end(JSON.stringify({ tasks: [] }));
      } else {
        response.writeHead(404);
        response.end(JSON.stringify({}));
      }
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, ws => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [
          "personal_send_context_snapshot_v1", "personal_memory_snapshot_v1",
          "chat_turn_admit_v1", "chat_turn_context_v1", "chat_turn_context_selection_details_v2",
          ...(failureSignalAvailable ? ["chat_turn_context_failure_v1"] : []),
          ...(scenario === "routing-directory" ? ["personal_project_routing_directory_v1"] : []),
        ] } }));
        ws.on("message", raw => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload?: Record<string, unknown> };
          if (frame.type === "personal_memory_snapshot") {
            ws.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
              request_id: frame.payload?.request_id, success: true,
              personal_memories: { encrypted_settings: null, memories: [] },
            } }));
          } else if (frame.type === "chat_turn_admit") {
            admitted = true;
            admittedFrame = frame.payload ?? {};
            admittedTurnId = String(frame.payload?.turn_id);
            candidatesWaitingAtAdmission = deferredProjects !== null;
            ws.send(JSON.stringify({ type: "chat_turn_preflight_ack", payload: {
              turn_id: frame.payload?.turn_id, preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            } }));
            deferredProjects?.writeHead(projectsAvailable ? 200 : 503, { "content-type": "application/json" });
            deferredProjects?.end(JSON.stringify(scenario === "routing-directory" ? routingDirectory
              : projectsAvailable ? projectList : { message: "temporarily unavailable" }));
          } else if (frame.type === "chat_turn_context_failed") {
            failureFrame = frame.payload ?? {};
            ws.send(JSON.stringify({ type: "chat_turn_context_failed_ack", payload: {
              chat_id: frame.payload?.chat_id, turn_id: frame.payload?.turn_id,
              message_id: frame.payload?.message_id, request_id: frame.payload?.request_id,
              status: scenario === "unavailable-failure-rejected" ? "rejected" : "accepted",
            } }));
          } else if (frame.type === "chat_turn_context_ready") {
            contextFrames.push(frame.payload ?? {});
            if (scenario === `${String(frame.payload?.phase)}-ack-rejected`) {
              ws.send(JSON.stringify({ type: "chat_turn_context_ack", payload: {
                chat_id: frame.payload?.chat_id, turn_id: frame.payload?.turn_id,
                message_id: frame.payload?.message_id, request_id: frame.payload?.request_id,
                phase: frame.payload?.phase, status: "rejected",
              } }));
            } else if (frame.payload?.phase === "details" && (scenario === "available" || scenario === "routing-directory" || scenario === "supplied-memory")) {
              ws.send(JSON.stringify({ type: "chat_turn_context_ack", payload: {
                chat_id: frame.payload?.chat_id, turn_id: frame.payload?.turn_id,
                message_id: frame.payload?.message_id, request_id: "other-request",
                phase: "details", status: "rejected",
              } }));
              ws.send(JSON.stringify({ type: "chat_message_confirmed", payload: {
                chat_id: frame.payload.chat_id, message_id: frame.payload.message_id,
              } }));
              setTimeout(() => ws.send(JSON.stringify({ type: "error", payload: {
                code: "client_update_required", turn_id: admittedTurnId,
              } })), 20);
            }
          }
        });
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      process.env.OPENMATES_DEBUG = "1";
      console.error = (...values: unknown[]) => {
        if (typeof values[0] === "string" && values[0].startsWith("[chat admission continuation]")) debugLines.push(values[0]);
        else previousConsoleError(...values);
      };
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      await assert.rejects(client.sendMessage({ message: "private diagnostic marker", personal: true, piiDetection: false,
        ...(scenario === "supplied-memory" ? { memorySnapshot: [], jevContext: { project_focus_candidates: suppliedCandidates } } : {}),
      }),
        scenario.endsWith("ack-rejected") ? /Chat context delivery was rejected/
          : projectsAvailable ? /update required/i : /Project list failed with HTTP 503/);
      assert.equal(admitted, true);
      assert.equal(admittedFrame?.inference_request &&
        (admittedFrame.inference_request as Record<string, unknown>).project_focus_candidates, undefined);
      assert.equal(candidatesWaitingAtAdmission, true, "candidate resolution must not gate durable admission");
      if (scenario === "routing-ack-rejected") {
        assert.equal(contextFrames[0]?.phase, "routing");
      } else {
        assert.deepEqual(contextFrames.map(frame => frame.phase), projectsAvailable ? ["routing", "details"] : []);
      }
      if (scenario === "available" || scenario === "routing-directory" || scenario === "supplied-memory") {
        assert.deepEqual((contextFrames[0]?.context as Record<string, unknown>)?.project_focus_candidates,
          scenario === "available" || scenario === "supplied-memory" ? [] : [{
            project_id: disabledProjectId, name: "Disabled Project", summary: "Excluded from automatic routing",
            auto_selection: true, focus_activation_policy: "delayed",
          }],
          "fresh deferred discovery excludes disabled Projects even when the caller supplies memories");
      }
      if (scenario === "routing-directory") {
        assert.equal(routingDirectoryRequests, 1);
        assert.equal(legacyListRequests, 0);
        assert.equal(settingsRequests, 0);
      } else {
        assert.equal(routingDirectoryRequests, 0, "servers without the advertised capability keep legacy discovery");
      }
      assert.equal(Boolean(failureFrame), failureSignalAvailable);
      if (failureFrame) {
        assert.equal(failureFrame.reason, projectsAvailable ? "context_preparation_failed" : "project_discovery_failed");
        assert.equal(failureFrame.turn_id, admittedTurnId);
        assert.equal(failureFrame.chat_id, admittedFrame?.chat_id);
        assert.equal(failureFrame.message_id, admittedFrame?.message_id);
        assert.equal(failureFrame.request_id,
          (admittedFrame?.inference_request as Record<string, unknown>)?.client_context_request_id);
        assert.deepEqual(Object.keys(failureFrame).sort(), ["chat_id", "message_id", "reason", "request_id", "turn_id"]);
      }
      assert.equal(debugLines.length, scenario === "available" || scenario === "routing-directory" || scenario === "supplied-memory" ? 0 : 1);
      if (debugLines.length) {
        assert.match(debugLines[0], /^\[chat admission continuation\] phase=(await_routing|await_details|await_confirmation) ack_observed=true routing_sent=(true|false) details_sent=(true|false) socket_open=(true|false) elapsed_ms=\d+$/);
        for (const secret of ["private diagnostic marker", "test-refresh-token", "test-hashed-email", "test-session-id"])
          assert.equal(debugLines[0].includes(secret), false);
      }
    } finally {
      console.error = previousConsoleError;
      if (previousDebug === undefined) delete process.env.OPENMATES_DEBUG;
      else process.env.OPENMATES_DEBUG = previousDebug;
      wss.close();
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.isolation
  it("prefetches real encrypted privacy at TUI startup and reuses it only after durable send generation equality", async () => {
    const requests: Array<Record<string, unknown>> = [];
    let generation: string | null = "epoch:1";
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request, response) => {
      if (request.method !== "POST" || request.url !== "/v1/auth/session") {
        response.writeHead(404); response.end("{}"); return;
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, ws_token: "fresh-token", user: { id: "11111111-1111-4111-8111-111111111111" } }));
    });
    const encrypted = await encryptWithAesGcmCombined(JSON.stringify({ enabled: true, textToHide: "Private Fixture Name", replaceWith: "NAME" }), new Uint8Array(32));
    server.on("upgrade", (request, connection, head) => wss.handleUpgrade(request, connection, head, peer => {
      peer.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["personal_send_context_snapshot_v2"] } }));
      peer.on("message", raw => {
        const frame = JSON.parse(raw.toString());
        if (frame.type !== "personal_send_context_snapshot") return;
        requests.push(frame.payload);
        const unchanged = !!generation && frame.payload.known_generation === generation;
        peer.send(JSON.stringify({ type: "personal_send_context_snapshot_result", payload: {
          request_id: frame.payload.request_id, success: true, privacy_generation: generation, unchanged,
          receipt_id: frame.payload.purpose === "send" ? "22222222-2222-4222-8222-222222222222" : null,
          turn_id: frame.payload.turn_id, project_candidates: [],
          ...(!unchanged ? { personal_memories: { encrypted_settings: null, memories: [{ id: "private-row", app_id: "privacy",
            item_type: "personal_data_entry", encrypted_item_json: encrypted }] } } : {}),
        } }));
      });
    }));
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address(); assert.ok(address && typeof address === "object");
    const apiUrl = `http://127.0.0.1:${address.port}`; writeLegacySession(apiUrl);
    const client = OpenMatesClient.load({ apiUrl });
    const internal = client as unknown as {
      openWsClient: () => Promise<{ ws: InstanceType<typeof OpenMatesWsClient> }>;
      chatActivitySocket: unknown; warmPersonalPrivacy: () => void; preparedPrivacyWarmPending: Promise<void>;
      listMemoriesUnshared: (...args: unknown[]) => Promise<unknown>;
    };
    const original = internal.listMemoriesUnshared.bind(client); let decrypts = 0;
    internal.listMemoriesUnshared = (...args) => { decrypts++; return original(...args); };
    let activity: InstanceType<typeof OpenMatesWsClient> | null = null;
    try {
      client.beginInteractiveViewerSession();
      (client as unknown as { interactiveViewerAllowed: boolean }).interactiveViewerAllowed = true;
      activity = (await internal.openWsClient()).ws;
      internal.chatActivitySocket = { ws: activity, ownerCurrent: () => client.hasSession(), lastWarmupScope: null };
      internal.warmPersonalPrivacy(); await internal.preparedPrivacyWarmPending;
      assert.equal(decrypts, 1); assert.equal(requests[0]?.purpose, "prepare");
      const send = async () => {
        let safe = "";
        await assert.rejects(client.sendMessage({ message: "Hello Private Fixture Name", personal: true,
          onPrivacyPrepared: message => { safe = message; throw new Error("stop after privacy"); } }), /stop after privacy/);
        assert.equal(safe.includes("Private Fixture Name"), false);
      };
      await send(); assert.equal(requests.at(-1)?.known_generation, "epoch:1"); assert.equal(decrypts, 1);
      generation = "epoch:2"; await send(); assert.equal(decrypts, 2, "lost mutation notification still refreshes changed generation");
      client.invalidatePreparedPrivacy(); await send(); assert.equal(requests.at(-1)?.known_generation, undefined); assert.equal(decrypts, 3);
      generation = null; await send(); await send(); assert.equal(decrypts, 5, "missing generation never means unchanged");
    } finally {
      client.endInteractiveViewerSession(); activity?.close();
      for (const peer of wss.clients) peer.terminate();
      wss.close(); server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=sdk.surface.semantic-parity,chats.send.immediate-admission
  it("owns the recovery fixture's deferred compatibility fault under strict unhandled-rejection policy", async () => {
    const source = readFileSync(new URL("../../../apps/web_app/tests/cli-recovery-discovery.spec.ts", import.meta.url), "utf8");
    const fixture = source.slice(source.indexOf("test('SDK reports a Project directory failure after durable epoch-one first Personal admission'"));
    const gate = /const projectGate=new Promise[\s\S]*?(?=\s*const outbound=)/.exec(fixture)?.[0];
    const capability = /const supports=opened\.ws\.supportsServerCapability[\s\S]*?(?=\s*opened\.ws\.onMessageType)/.exec(fixture)?.[0];
    assert.ok(gate); assert.ok(capability);
    const program = `
      import assert from 'node:assert/strict';
      const client={};let rejectProjects,projectReads=0;
      ${gate}
      const advertised=new Set(['personal_send_context_snapshot_v2','personal_send_context_snapshot_v1','personal_memory_snapshot_v1','personal_project_routing_directory_v1','chat_turn_admit_v1']);
      const opened={ws:{supportsServerCapability:cap=>advertised.has(cap)}};
      ${capability}
      assert.equal(opened.ws.supportsServerCapability('personal_send_context_snapshot_v2'),false);
      for(const cap of [...advertised].filter(cap=>cap!=='personal_send_context_snapshot_v2')) assert.equal(opened.ws.supportsServerCapability(cap),true);
      rejectProjects(Error('synthetic-private-directory-failure'));
      // Let a full event-loop turn pass before a consumer attaches, matching
      // the CI timing that exposed an unowned fixture gate on Node24.
      await new Promise(resolve=>setImmediate(resolve));
      const failed=await Promise.allSettled([client.listProjects(),client.listPersonalProjectRoutingDirectory()]);
      assert.equal(projectReads,2);
      assert.ok(failed.every(result=>result.status==='rejected'&&result.reason.message==='synthetic-private-directory-failure'));
      process.stdout.write('owned-deferred-directory-fixture');
    `;
    const { stdout } = await new Promise<{ stdout: string }>((resolve, reject) => {
      execFile(process.execPath, ["--unhandled-rejections=strict", "--input-type=module", "-e", program], (error, stdout) => {
        if (error) reject(error); else resolve({ stdout });
      });
    });
    assert.equal(stdout, "owned-deferred-directory-fixture");
  });

  // contract-test: supporting surface=cli assertions=app-memories.surface.semantic-parity,auth.session.isolation
  for (const socketMode of ["warm", "cold"] as const) {
    it("requests fresh Personal Memory before privacy on a " + socketMode + " socket", async () => {
      const order: string[] = [];
      let batchedAuth = 0;
      const wss = new WebSocketServer({ noServer: true });
      const server = createServer((request, response) => {
        if (request.method !== "POST" || request.url !== "/v1/auth/session") {
          response.writeHead(404); response.end(JSON.stringify({})); return;
        }
        let body = "";
        request.on("data", chunk => { body += chunk.toString(); });
        request.on("end", () => {
          if (JSON.parse(body).include_personal_memories === true) batchedAuth++;
          order.push("auth");
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ success: true, ws_token: "fresh-token",
            user: { id: "11111111-1111-4111-8111-111111111111" } }));
        });
      });
      server.on("upgrade", (request, connection, head) => {
        wss.handleUpgrade(request, connection, head, socket => {
          socket.send(JSON.stringify({ type: "server_capabilities", payload: {
            capabilities: ["personal_memory_snapshot_v1"],
          } }));
          socket.on("message", raw => {
            const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
            if (frame.type !== "personal_memory_snapshot") return;
            order.push("snapshot");
            socket.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
              request_id: frame.payload?.request_id, success: true,
              personal_memories: { encrypted_settings: null, memories: [] },
            } }));
          });
        });
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      const apiUrl = "http://127.0.0.1:" + address.port;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const internal = client as unknown as {
        openWsClient: () => Promise<{ ws: { close: () => void } }>;
        takePreparedSendSocket: () => Promise<unknown>;
        interactiveViewerAllowed: boolean;
      };
      const oldInputTty = process.stdin.isTTY;
      const oldOutputTty = process.stdout.isTTY;
      try {
        if (socketMode === "warm") {
          const opened = await internal.openWsClient();
          internal.takePreparedSendSocket = async () => opened;
          internal.interactiveViewerAllowed = true;
          Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
          Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });
        }
        await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true,
          interactiveHuman: socketMode === "warm", piiDetection: false,
          onPrivacyPrepared: () => { order.push("privacy"); throw new Error("stop after snapshot"); },
        }), /stop after snapshot/);
        assert.deepEqual(order.slice(-2), ["snapshot", "privacy"]);
        assert.equal(order.filter(value => value === "auth").length, 1);
        assert.equal(batchedAuth, 0);
      } finally {
        Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: oldInputTty });
        Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: oldOutputTty });
        wss.close();
        server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,app-memories.surface.semantic-parity,workflows.chat.metadata-warmup
  for (const mode of ["deferred-personal", "saved-chat", "legacy-context", "wrong-nonce"] as const) {
    it(`keeps a fresh one-use privacy snapshot for ${mode}`, async () => {
      const frames: string[] = [];
      let privacyPrepared = false;
      const wss = new WebSocketServer({ noServer: true });
      const server = createServer((request, response) => {
        if (request.method === "POST" && request.url === "/v1/auth/session") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ success: true, ws_token: "fresh-token",
            user: { id: "11111111-1111-4111-8111-111111111111" } }));
          return;
        }
        response.writeHead(404); response.end();
      });
      server.on("upgrade", (request, connection, head) => {
        wss.handleUpgrade(request, connection, head, socket => {
          socket.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [
            "personal_send_context_snapshot_v1", "personal_memory_snapshot_v1", "chat_turn_admit_v1",
            ...(mode === "legacy-context" ? [] : ["chat_turn_context_v1"]),
          ] } }));
          socket.on("message", raw => {
            const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
            frames.push(frame.type);
            if (frame.type !== "personal_memory_snapshot" && frame.type !== "personal_send_context_snapshot") return;
            const wrongNonce = mode === "wrong-nonce";
            socket.send(JSON.stringify({
              type: frame.type === "personal_memory_snapshot"
                ? "personal_memory_snapshot_result" : "personal_send_context_snapshot_result",
              payload: { request_id: wrongNonce ? "00000000-0000-4000-8000-000000000000" : frame.payload?.request_id,
                success: true, personal_memories: { encrypted_settings: null, memories: [] },
                ...(frame.type === "personal_send_context_snapshot" ? { project_candidates: [] } : {}),
              },
            }));
            if (wrongNonce) setTimeout(() => socket.close(), 10);
          });
        });
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      const previousTiming = process.env.OPENMATES_TRACE_SEND_TIMING;
      const previousDebug = process.env.OPENMATES_DEBUG;
      const previousConsoleError = console.error;
      const timingLines: string[] = [];
      try {
        if (mode === "deferred-personal") {
          process.env.OPENMATES_TRACE_SEND_TIMING = "1";
          delete process.env.OPENMATES_DEBUG;
          console.error = (...values: unknown[]) => {
            if (typeof values[0] === "string" && values[0].startsWith("[chat send timing]"))
              timingLines.push(values[0]);
            else previousConsoleError(...values);
          };
        }
        const apiUrl = `http://127.0.0.1:${address.port}`;
        writeLegacySession(apiUrl);
        const client = OpenMatesClient.load({ apiUrl });
        if (mode === "saved-chat") {
          (client as unknown as { getChatMessages: () => Promise<{ messages: [] }> }).getChatMessages =
            async () => ({ messages: [] });
        }
        await assert.rejects(client.sendMessage({
          message: "Private test text", personal: true, piiDetection: false,
          ...(mode === "saved-chat" ? { chatId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" } : {}),
          onPrivacyPrepared: () => { privacyPrepared = true; throw new Error("stop after fresh privacy"); },
        }), mode === "wrong-nonce" ? /WebSocket closed|snapshot|socket/i : /stop after fresh privacy/);
        const snapshots = frames.filter(type => type === "personal_memory_snapshot" || type === "personal_send_context_snapshot");
        assert.deepEqual(snapshots, [mode === "saved-chat" || mode === "legacy-context"
          ? "personal_send_context_snapshot" : "personal_memory_snapshot"]);
        assert.equal(privacyPrepared, mode !== "wrong-nonce");
        assert.equal(frames.includes("chat_turn_admit"), false);
        if (mode === "deferred-personal") {
          assert.deepEqual(timingLines.map(line => line.match(/^\[chat send timing\] phase=([a-z_]+) elapsed_ms=\d+$/)?.[1]),
            ["send_begin", "snapshot_request", "snapshot_ready", "memory_decrypt_ready", "privacy_begin"]);
        }
      } finally {
        console.error = previousConsoleError;
        if (previousTiming === undefined) delete process.env.OPENMATES_TRACE_SEND_TIMING;
        else process.env.OPENMATES_TRACE_SEND_TIMING = previousTiming;
        if (previousDebug === undefined) delete process.env.OPENMATES_DEBUG;
        else process.env.OPENMATES_DEBUG = previousDebug;
        wss.close(); server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  it("closes the snapshot socket when saved history fails before admission", async () => {
    const events: string[] = [];
    let resolveClosed!: () => void;
    const closed = new Promise<void>(resolve => { resolveClosed = resolve; });
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request, response) => {
      if (request.method !== "POST" || request.url !== "/v1/auth/session") {
        response.writeHead(404); response.end(JSON.stringify({})); return;
      }
      let body = "";
      request.on("data", chunk => { body += chunk.toString(); });
      request.on("end", () => {
        assert.equal(JSON.parse(body).include_personal_memories, undefined);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token",
          user: { id: "11111111-1111-4111-8111-111111111111" } }));
      });
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, socket => {
        socket.send(JSON.stringify({ type: "server_capabilities", payload: {
          capabilities: ["personal_memory_snapshot_v1"],
        } }));
        socket.on("close", () => { events.push("closed"); resolveClosed(); });
        socket.on("message", raw => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
          if (frame.type !== "personal_memory_snapshot") return;
          events.push("snapshot");
          socket.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
            request_id: frame.payload?.request_id, success: true,
            personal_memories: { encrypted_settings: null, memories: [] },
          } }));
        });
      });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    const apiUrl = "http://127.0.0.1:" + address.port;
    writeLegacySession(apiUrl);
    const client = OpenMatesClient.load({ apiUrl });
    const internal = client as unknown as { getChatMessages: () => Promise<never> };
    internal.getChatMessages = async () => { events.push("history"); throw new Error("history unavailable"); };
    try {
      await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true,
        chatId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", piiDetection: false,
      }), /history unavailable/);
      let closeTimer: ReturnType<typeof setTimeout> | null = null;
      try {
        await Promise.race([closed, new Promise<never>((_, reject) => {
          closeTimer = setTimeout(() => reject(new Error("Snapshot socket did not close after history failure.")), 1_000);
        })]);
      } finally {
        if (closeTimer) clearTimeout(closeTimer);
      }
      assert.deepEqual(events, ["snapshot", "history", "closed"]);
    } finally {
      for (const socket of wss.clients) socket.terminate();
      wss.close();
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,app-memories.surface.semantic-parity
  for (const resultMode of ["unauthorized", "rate_limited", "unavailable", "malformed"] as const) {
    it("does not downgrade an advertised snapshot " + resultMode + " with auto-approval off", async () => {
      let authCalls = 0;
      let batchCalls = 0;
      const wss = new WebSocketServer({ noServer: true });
      const server = createServer((request, response) => {
        if (request.method !== "POST" || request.url !== "/v1/auth/session") {
          response.writeHead(404); response.end(JSON.stringify({})); return;
        }
        let body = "";
        request.on("data", chunk => { body += chunk.toString(); });
        request.on("end", () => {
          authCalls++;
          if (JSON.parse(body).include_personal_memories === true) batchCalls++;
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ success: true, ws_token: "fresh-token",
            user: { id: "11111111-1111-4111-8111-111111111111" } }));
        });
      });
      server.on("upgrade", (request, connection, head) => {
        wss.handleUpgrade(request, connection, head, socket => {
          socket.send(JSON.stringify({ type: "server_capabilities", payload: {
            capabilities: ["personal_memory_snapshot_v1"],
          } }));
          socket.on("message", raw => {
            const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
            if (frame.type !== "personal_memory_snapshot") return;
            socket.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: resultMode === "malformed"
              ? { request_id: frame.payload?.request_id, success: true, personal_memories: { memories: [] } }
              : { request_id: frame.payload?.request_id, success: false, error: { code: resultMode } },
            }));
          });
        });
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      const apiUrl = "http://127.0.0.1:" + address.port;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      try {
        await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true,
          piiDetection: false, autoApproveMemories: false,
        }), resultMode === "malformed" ? /Invalid Personal Memory snapshot result/ : new RegExp(resultMode));
        assert.equal(authCalls, 1);
        assert.equal(batchCalls, 0);
      } finally {
        wss.close();
        server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  for (const changed of ["owner", "cookie", "options"] as const) {
    it("discards a Personal Memory receipt after " + changed + " changes", async () => {
      let admitted = false;
      const wss = new WebSocketServer({ noServer: true });
      const server = createServer((request, response) => {
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/auth/session") {
          response.end(JSON.stringify({ success: true, ws_token: "fresh-token",
            user: { id: "11111111-1111-4111-8111-111111111111" } }));
        } else if (request.method === "GET" && request.url === "/v1/projects") {
          response.end(JSON.stringify({ projects: [] }));
        } else if (request.method === "GET" && request.url?.startsWith("/v1/user-tasks")) {
          response.end(JSON.stringify({ tasks: [], complete: true, next_cursor: null }));
        } else {
          response.writeHead(404); response.end(JSON.stringify({}));
        }
      });
      server.on("upgrade", (request, connection, head) => {
        wss.handleUpgrade(request, connection, head, socket => {
          socket.send(JSON.stringify({ type: "server_capabilities", payload: {
            capabilities: ["personal_memory_snapshot_v1", "chat_turn_admit_v1", "chat_turn_context_v1"],
          } }));
          socket.on("message", raw => {
            const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
            if (frame.type === "personal_memory_snapshot") {
              socket.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
                request_id: frame.payload?.request_id, success: true,
                personal_memories: { encrypted_settings: null, memories: [] },
              } }));
            } else if (frame.type === "chat_metadata_warmup") {
              socket.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
            } else if (frame.type === "chat_turn_admit") {
              admitted = true;
              socket.send(JSON.stringify({ type: "error", payload: { code: "client_update_required" } }));
            }
          });
        });
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      const apiUrl = "http://127.0.0.1:" + address.port;
      writeLegacySession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      const sendParams: Parameters<typeof client.sendMessage>[0] = {
        message: "ordinary question", personal: true, piiDetection: false,
        learningMode: { enabled: false },
        onPrivacyPrepared: () => {
          if (changed === "owner") client.getSession()!.hashedEmail = "different-owner";
          if (changed === "cookie") {
            const stored = JSON.parse(readFileSync(sessionPath, "utf8")) as { cookies: Record<string, string> };
            stored.cookies.auth_refresh_token = "rotated-cookie";
            writeFileSync(sessionPath, JSON.stringify(stored), { mode: 0o600 });
          }
          if (changed === "options") sendParams.learningMode = { enabled: true };
        },
      };
      try {
        await assert.rejects(client.sendMessage(sendParams));
        assert.equal(admitted, false);
      } finally {
        wss.close();
        server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }

  // contract-test: supporting surface=cli assertions=auth.session.lifecycle,auth.session.isolation,chats.completion.lease-fenced
  for (const variant of ["fresh", "memory-loaded", "arbitrary snapshot", "expired", "future", "missing owner", "rotated disk cookie", "changed account", "changed Team", "revoked socket"] as const) {
    it(`uses a one-shot Personal auth receipt or falls back safely: ${variant}`, async () => {
      let authCalls = 0;
      let preflightSent = false;
      let upgraded = false;
      const wss = new WebSocketServer({ noServer: true });
      const server = createServer((request: IncomingMessage, response: ServerResponse) => {
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/auth/session") {
          authCalls++;
          let body = "";
          request.on("data", chunk => { body += chunk.toString(); });
          request.on("end", () => {
            const batched = JSON.parse(body).include_personal_memories === true;
            response.end(JSON.stringify({ success: true, ws_token: `fresh-token-${authCalls}`,
              user: variant === "missing owner" && authCalls === 1 ? {} : { id: "11111111-1111-4111-8111-111111111111" },
              ...(batched ? { personal_memories: { encrypted_settings: null, memories: [] } } : {}),
            }));
          });
        } else if (request.method === "GET" && request.url === "/v1/sdk/memories") {
          response.end(JSON.stringify({ memories: [] }));
        } else if (request.method === "GET" && request.url === "/v1/projects") {
          response.end(JSON.stringify({ projects: [] }));
        } else if (request.method === "GET" && request.url?.startsWith("/v1/user-tasks")) {
          response.end(JSON.stringify({ tasks: [], complete: true, next_cursor: null }));
        } else {
          response.writeHead(404);
          response.end(JSON.stringify({}));
        }
      });
      server.on("upgrade", (request, connection, head) => {
        if (variant === "revoked socket") { connection.destroy(); return; }
        upgraded = true;
        wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
          ws.on("message", raw => {
            const frame = JSON.parse(raw.toString()) as { type: string; payload?: { chat_id?: string } };
            if (frame.type === "chat_metadata_warmup") {
              ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
            } else if (frame.type === "encrypted_chat_metadata") {
              ws.send(JSON.stringify({ type: "encrypted_metadata_stored", payload: { chat_id: frame.payload?.chat_id } }));
            } else if (frame.type === "chat_turn_admit") {
              preflightSent = true;
              ws.send(JSON.stringify({ type: "error", payload: { code: "client_update_required" } }));
            }
          });
        });
      });
      await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
      const address = server.address();
      assert.ok(address && typeof address === "object");
      try {
        const apiUrl = `http://127.0.0.1:${address.port}`;
        writeLegacySession(apiUrl);
        const client = OpenMatesClient.load({ apiUrl });
        const snapshot = variant === "memory-loaded" ? undefined : variant === "arbitrary snapshot"
          ? (await client.whoAmI(), []) : variant === "missing owner"
            ? await client.listMemories({ personal: true }).catch(() => [])
            : await client.listMemories({ personal: true });
        const internal = client as unknown as {
          personalMemoryAuthHandoff: { auth: { validatedAt: number } } | null;
        };
        if (variant === "expired") internal.personalMemoryAuthHandoff!.auth.validatedAt -= 6_000;
        if (variant === "future") internal.personalMemoryAuthHandoff!.auth.validatedAt += 6_000;
        if (variant === "rotated disk cookie") {
          const stored = JSON.parse(readFileSync(sessionPath, "utf8")) as { cookies: Record<string, string> };
          stored.cookies.auth_refresh_token = "rotated-on-disk";
          writeFileSync(sessionPath, JSON.stringify(stored), { mode: 0o600 });
        }
        if (variant === "changed account") client.getSession()!.hashedEmail = "different-account";
        if (variant === "changed Team") client.getSession()!.activeTeamId = "different-team";
        await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true,
          ...(snapshot ? { memorySnapshot: snapshot } : {}), piiDetection: false }), variant === "revoked socket" ? undefined
            : variant === "changed account" ? /Login account changed/i
              : variant === "changed Team" ? /Chat key preparation owner changed before send/i : /update required/i);
        // A cold send probes the socket first; definitive capability absence then
        // uses the fresh HTTP batch and its one-use auth handoff.
        assert.equal(authCalls, variant === "changed account" ? 1 : variant === "memory-loaded" || variant === "revoked socket" ? 2 : 3,
          "caller snapshots never replace fresh Personal send authority");
        assert.equal(preflightSent, variant !== "revoked socket" && variant !== "changed account" && variant !== "changed Team");
        assert.equal(upgraded, variant !== "revoked socket" && variant !== "changed account");
        if (variant === "fresh") {
          await assert.rejects(client.sendMessage({ message: "second question", personal: true,
            memorySnapshot: snapshot, piiDetection: false }), /update required/i);
          assert.equal(authCalls, 5, "each unsupported send probes then reloads its full Personal batch");
        }
      } finally {
        wss.close();
        server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }
  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("prepares a new chat's scoped context during recovery discovery", async () => {
    let projectReadBeforeDiscovery = false;
    let discoverySent = false;
    let preflightSent = false;
    let admissionBeforeDiscovery = false;
    let focusReads = 0;
    let planReads = 0;
    let _socket: import("ws").WebSocket | null = null;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/projects") {
        projectReadBeforeDiscovery = !discoverySent;
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ projects: [] }));
        return;
      }
      if (request.method === "GET" && request.url?.startsWith("/v1/projects/focus/current")) focusReads++;
      if (request.method === "GET" && request.url?.startsWith("/v1/user-plans")) planReads++;
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        _socket = ws;
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string };
          if (frame.type === "chat_turn_admit") {
            preflightSent = true;
            admissionBeforeDiscovery = !discoverySent;
            ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
            discoverySent = true;
            ws.send(JSON.stringify({ type: "error", payload: { code: "client_update_required" } }));
          }
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(client.sendMessage({ message: "ordinary question", piiDetection: false }), /update required/i);
      assert.equal(projectReadBeforeDiscovery, true);
      assert.equal(preflightSent, true);
      assert.equal(admissionBeforeDiscovery, true);
      assert.equal(focusReads, 0);
      assert.equal(planReads, 0);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.active-context.vault-boundary
  for (const variant of ["caller newChatId", "explicit Project"] as const) it(`retains Focus and Plan discovery for ${variant}`, async () => {
    let focusReads = 0;
    let planReads = 0;
    let discoverySent = false;
    let admissionBeforeDiscovery = false;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      const path = request.url ?? "";
      response.setHeader("content-type", "application/json");
      if (request.method === "POST" && path === "/v1/auth/session") {
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
      } else if (request.method === "GET" && path === "/v1/projects") {
        response.end(JSON.stringify({ projects: [] }));
      } else if (request.method === "GET" && path.startsWith("/v1/projects/focus/current")) {
        focusReads++;
        response.end(JSON.stringify({ focus: null }));
      } else if (request.method === "GET" && path.startsWith("/v1/user-plans")) {
        planReads++;
        response.end(JSON.stringify({ plans: [] }));
      } else if (request.method === "GET" && path.startsWith("/v1/user-tasks")) {
        response.end(JSON.stringify({ tasks: [], complete: true, next_cursor: null }));
      } else {
        response.writeHead(404);
        response.end(JSON.stringify({}));
      }
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload?: { chat_id?: string } };
          if (frame.type === "chat_metadata_warmup") {
            setTimeout(() => {
              discoverySent = true;
              ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
            }, 30);
          } else if (frame.type === "encrypted_chat_metadata") {
            ws.send(JSON.stringify({ type: "encrypted_metadata_stored", payload: { chat_id: frame.payload?.chat_id } }));
          } else if (frame.type === "chat_turn_admit") {
            admissionBeforeDiscovery = !discoverySent;
            ws.send(JSON.stringify({ type: "error", payload: { code: "client_update_required" } }));
          }
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const options = variant === "caller newChatId"
        ? { newChatId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" }
        : { projectId: "project" };
      await assert.rejects(client.sendMessage({ message: "ordinary question", piiDetection: false, ...options }),
        variant === "explicit Project" ? /Project (get|settings) failed: HTTP_404/ : /update required/i);
      // A missing explicit Project stops before activation and its post-activation
      // revalidation. The caller-ID path completes both current-focus reads.
      assert.equal(focusReads, variant === "explicit Project" ? 1 : 2);
      assert.equal(planReads, 1);
      assert.equal(admissionBeforeDiscovery, false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("keeps a prepared chat across a same-owner reload and discards it after owner changes", () => {
    for (const change of ["apiUrl", "hashedEmail", "sessionId", "createdAt", "masterKeyExportedB64", "activeTeamId"] as const) {
      writeLegacySession();
      const client = OpenMatesClient.load();
      const preparedId = client.preparedNewChatId();
      const original = client.getSession();
      const internal = client as unknown as { session: typeof original };
      internal.session = { ...original };
      assert.equal(client.preparedNewChatId(), preparedId, "an equivalent persisted profile keeps the prepared ID");
      internal.session = { ...original, [change]: change === "createdAt" ? original.createdAt + 1
        : change === "masterKeyExportedB64" ? "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="
        : change === "activeTeamId" ? "different-team" : `different-${change}` };
      assert.notEqual(client.preparedNewChatId(), preparedId, `${change} must invalidate the prepared ID`);
    }
    writeLegacySession();
    const teamClient = OpenMatesClient.load();
    const teamId = "22222222-2222-4222-8222-222222222222";
    teamClient.setActiveTeamId(teamId);
    saveLocalTeamKey("test-hashed-email", teamId, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
    const teamPreparedId = teamClient.preparedNewChatId();
    saveLocalTeamKey("test-hashed-email", teamId, "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=");
    assert.notEqual(teamClient.preparedNewChatId(), teamPreparedId, "Team key rotation must invalidate the prepared ID");
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  for (const mutation of ["setter", "live session"] as const) it(`rejects prepared context after a ${mutation} Team change`, { timeout: 5_000 }, async () => {
    let client: OpenMatesClient | null = null;
    let sendSocket: import("ws").WebSocket | null = null;
    let userFrameSent = false;
    let resolveSendSocketClosed!: () => void;
    const sendSocketClosed = new Promise<void>(resolve => { resolveSendSocketClosed = resolve; });
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/projects") {
        // The Personal snapshot receipt keeps this exact authenticated socket
        // for the send. Mutate only when its context read starts, after auth.
        assert.ok(client && sendSocket);
        if (mutation === "setter") client.setActiveTeamId("22222222-2222-4222-8222-222222222222");
        else client.getSession().activeTeamId = "22222222-2222-4222-8222-222222222222";
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ projects: [] }));
        sendSocket.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [
          "personal_memory_snapshot_v1", "chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1",
        ] } }));
        ws.on("close", () => { if (ws === sendSocket) resolveSendSocketClosed(); });
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
          if (frame.type === "personal_memory_snapshot") {
            sendSocket = ws;
            ws.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
              request_id: frame.payload?.request_id, success: true,
              personal_memories: { encrypted_settings: null, memories: [] },
            } }));
          }
          if (["chat_turn_admit", "chat_turn_preflight", "chat_message_added"].includes(frame.type)) userFrameSent = true;
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true, piiDetection: false }), /Chat workspace changed while preparing context/);
      await sendSocketClosed;
      assert.equal(userFrameSent, false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("aborts an unfinished context read when recovery discovery fails", { timeout: 5_000 }, async () => {
    let socket: import("ws").WebSocket | null = null;
    let discoveryFailurePending = false;
    let projectAborted = false;
    let socketClosed = false;
    let projectReadStarted = false;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/projects") {
        projectReadStarted = true;
        response.on("close", () => { if (!response.writableEnded) projectAborted = true; });
        discoveryFailurePending = true;
        socket?.send(JSON.stringify({ type: "error", payload: { code: "client_update_required", message: "Recovery discovery failed." } }));
        // Leave this response open: the scoped abort must close it promptly.
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        socket = ws;
        if (discoveryFailurePending) setTimeout(() => ws.send(JSON.stringify({ type: "error", payload: { code: "client_update_required", message: "Recovery discovery failed." } })), 10);
        ws.on("close", () => { socketClosed = true; });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const startedAt = Date.now();
      await assert.rejects(client.sendMessage({ message: "ordinary question", piiDetection: false }), /OpenMates CLI update required/);
      assert.equal(projectReadStarted, true);
      assert.ok(Date.now() - startedAt < 2_000, "failed send must not wait for the HTTP timeout");
      await new Promise<void>((resolve) => setTimeout(resolve, 30));
      assert.equal(projectAborted, true);
      assert.equal(socketClosed, true);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("closes the Personal snapshot probe when the session disappears before context setup", { timeout: 5_000 }, async () => {
    let socketClosed = false;
    let resolveSocketClosed!: () => void;
    const socketClosedPromise = new Promise<void>(resolve => { resolveSocketClosed = resolve; });
    let contextRead = false;
    let userFrameSent = false;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
        return;
      }
      if (request.url === "/v1/projects") contextRead = true;
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.on("close", () => { socketClosed = true; resolveSocketClosed(); });
        ws.on("message", (raw) => {
          if (["chat_turn_admit", "chat_turn_preflight", "chat_message_added"].includes(
            (JSON.parse(raw.toString()) as { type: string }).type)) userFrameSent = true;
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const internal = client as unknown as {
        openWsClient: (...args: never[]) => Promise<{ ws: unknown; ownerId: string | null }>;
        session: unknown;
      };
      const open = internal.openWsClient.bind(client);
      internal.openWsClient = async (...args: never[]) => {
        const opened = await open(...args);
        internal.session = null; // Deterministic forced logout after successful socket open.
        return opened;
      };
      await assert.rejects(client.sendMessage({ message: "ordinary question", piiDetection: false }), /Not logged in/);
      await socketClosedPromise;
      assert.equal(socketClosed, true);
      assert.equal(contextRead, false, "logout before snapshot completion must not start a context read");
      assert.equal(userFrameSent, false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("closes the send socket when the session disappears during its context read", { timeout: 5_000 }, async () => {
    let client: OpenMatesClient | null = null;
    let sendSocket: import("ws").WebSocket | null = null;
    let socketClosed = false;
    let resolveSocketClosed!: () => void;
    const socketClosedPromise = new Promise<void>(resolve => { resolveSocketClosed = resolve; });
    let contextRead = false;
    let userFrameSent = false;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: "11111111-1111-4111-8111-111111111111" }, personal_memories: { encrypted_settings: null, memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/projects") {
        assert.ok(client && sendSocket, "context must use the authenticated snapshot socket");
        contextRead = true;
        (client as unknown as { session: unknown }).session = null;
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ projects: [] }));
        sendSocket.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, connection, head) => {
      wss.handleUpgrade(request, connection, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [
          "personal_memory_snapshot_v1", "chat_turn_admit_v1", "chat_turn_context_v1",
        ] } }));
        ws.on("close", () => { socketClosed = true; resolveSocketClosed(); });
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload?: { request_id?: string } };
          if (frame.type === "personal_memory_snapshot") {
            sendSocket = ws;
            ws.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
              request_id: frame.payload?.request_id, success: true,
              personal_memories: { encrypted_settings: null, memories: [] },
            } }));
          }
          if (["chat_turn_admit", "chat_turn_preflight", "chat_message_added"].includes(frame.type)) userFrameSent = true;
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(client.sendMessage({ message: "ordinary question", personal: true, piiDetection: false }),
        /Chat workspace changed while preparing context|Not logged in/);
      assert.equal(contextRead, true);
      assert.equal(userFrameSent, false);
      await socketClosedPromise;
      assert.equal(socketClosed, true);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
  it("orders immediate personal follow-ups after committed replies", () => {
    assert.equal(nextPersonalUserCreatedAt(100, [100, 101]), 102);
    assert.equal(nextPersonalUserCreatedAt(100, [100, 101, 102, 103]), 104);
    assert.equal(nextPersonalUserCreatedAt(200, [100, 101, 103]), 200);
    assert.equal(nextPersonalUserCreatedAt(100, [100, Number.NaN, -1]), 101);
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("stops before inference when saved-chat preflight requires a client update", async () => {
    const captured: { frameTypes: string[] } = { frameTypes: [] };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: "11111111-1111-4111-8111-111111111111" },
        }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_admit") {
            ws.send(JSON.stringify({
              type: "error",
              payload: {
                code: "client_update_required",
                message: "Please update OpenMates before sending another saved chat message.",
              },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        client.sendMessage({ message: "This must not reach inference" }),
        /OpenMates CLI update required\. Run `openmates upgrade` and retry\./,
      );
      assert.equal(captured.frameTypes.includes("chat_turn_admit"), true);
      assert.equal(captured.frameTypes.includes("chat_message_added"), false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,workflows.chat.metadata-warmup
  // contract-test: supporting surface=cli assertions=chats.completion.independent-metadata,auth.session.isolation
  it("does not dispatch encrypted initial metadata after its owner fence is superseded", async () => {
    const client = OpenMatesClient.load();
    let dispatched = 0;
    const ws = { supportsServerCapability: () => true,
      sendAsync: async () => { dispatched++; },
      waitForMessage: async () => { throw new Error("Superseded metadata must not allocate a transport waiter."); } };
    await (client as any).persistPostProcessingMetadata({ ws, chatId: "owned-chat", teamId: null,
      chatKeyBytes: new Uint8Array(32), encryptedChatKey: "fixture-wrapper", followUpSuggestions: [],
      suggestedFollowupMessage: null, newChatSuggestions: [], chatSummary: null, chatTags: [],
      updatedChatTitle: "Generated title", sourceTitleVersion: null, sourceMetadataVersion: null,
      unversionedGeneratedTitle: true, ownerCurrent: () => false });
    assert.equal(dispatched, 0);
  });

  for (const holdInitialHeaderAck of [false, true]) for (const supported of [true, false]) it(`uses ${supported ? "single admission" : "legacy preflight fallback"} with durable encrypted content${holdInitialHeaderAck ? " and independently delayed initial header ACK" : ""}`, async () => {
    const ownerId = "11111111-1111-4111-8111-111111111111";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const captured: {
      messagePayload?: Record<string, unknown>;
      preflightPayload?: Record<string, unknown>;
      persistPayload?: Record<string, unknown>;
      metadataPayload?: Record<string, unknown>;
      warmupPayload?: Record<string, unknown>;
      postProcessingPayload?: Record<string, unknown>;
      initialPostProcessingPayload?: Record<string, unknown>;
      initialHeaderBeforeTerminal?: boolean;
      frameTypes: string[];
      preflightAcknowledged: boolean;
      terminalSent: boolean;
    } = { frameTypes: [], preflightAcknowledged: false, terminalSent: false };
    let sealedPayloadForTest: string | null = null;
    let releaseInitialHeaderAck: (() => void) | undefined;
    let initialHeaderAcknowledged = false;
    let deferredProjects: ServerResponse | null = null;
    let projectListRequested = false;
    let projectListCompletedAfterAdmission = false;
    let discoverySent = false;
    let admissionBeforeDiscovery = false;
    const contextFrames: Array<Record<string, unknown>> = [];
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
        return;
      }
      if (
        request.method === "GET" &&
        request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false"
      ) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      if (request.url === "/v1/projects") {
        projectListRequested = true;
        // Deliberately stall discovery until the durable message reaches the server.
        if (supported && !captured.preflightPayload) { deferredProjects = response; return; }
        if (supported) projectListCompletedAfterAdmission = Boolean(captured.preflightPayload);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ projects: [] })); return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        if (supported) setTimeout(() => ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [
          "personal_send_context_snapshot_v1", "personal_memory_snapshot_v1",
          "chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1",
        ] } })), 50);
        else {
          // This server advertises capabilities but lacks single admission;
          // the CLI must use durable preflight rather than infer no-frame support.
          ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: [] } }));
          discoverySent = true;
          ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        }
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "personal_memory_snapshot") {
            ws.send(JSON.stringify({ type: "personal_memory_snapshot_result", payload: {
              request_id: frame.payload.request_id, success: true,
              personal_memories: { encrypted_settings: null, memories: [] },
            } }));
          }
          if (frame.type === "chat_metadata_warmup") captured.warmupPayload = frame.payload;
          if (frame.type === "chat_turn_context_ready") {
            contextFrames.push(frame.payload);
            ws.send(JSON.stringify({ type: "chat_turn_context_ack", payload: {
              chat_id: frame.payload.chat_id, turn_id: frame.payload.turn_id,
              message_id: frame.payload.message_id, request_id: frame.payload.request_id,
              phase: frame.payload.phase, status: "accepted",
            } }));
          }
          if (frame.type === "chat_turn_admit" || frame.type === "chat_turn_preflight") {
            captured.preflightPayload = frame.payload;
            if (supported) {
              admissionBeforeDiscovery = !discoverySent;
              discoverySent = true;
              ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
            }
            deferredProjects?.writeHead(200, { "content-type": "application/json" });
            deferredProjects?.end(JSON.stringify({ projects: [] }));
            if (deferredProjects) projectListCompletedAfterAdmission = true;
            const sealedPayload = await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantMessageId,
                category: "general_knowledge",
                chat_id: frame.payload.chat_id,
                content: "ok",
                job_id: recoveryJobId,
                key_version: 1,
                model_name: "test-model",
                turn_id: frame.payload.turn_id,
              })),
              {
                recoveryPublicKey: String(frame.payload.recovery_public_key),
                ownerId,
                chatId: String(frame.payload.chat_id),
                turnId: String(frame.payload.turn_id),
                jobId: recoveryJobId,
                assistantMessageId,
                keyVersion: 1,
              },
            );
            sealedPayloadForTest = JSON.stringify(sealedPayload);
            ws.send(JSON.stringify({ type: "ai_typing_started", payload: {
              chat_id: frame.payload.chat_id, user_message_id: frame.payload.message_id,
              turn_id: frame.payload.turn_id, task_id: "owned-initial-task",
              ...(!holdInitialHeaderAck ? { source_title_v: 0, source_metadata_v: 0 } : {}),
              title: "Contact a plumber", category: "general_knowledge", icon_names: ["wrench"],
            } }));
            await new Promise<void>(resolve => setTimeout(resolve, 10));
            {
              captured.preflightAcknowledged = true;
              ws.send(JSON.stringify({
                type: "chat_turn_preflight_ack",
                payload: {
                  preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                  turn_id: frame.payload.turn_id,
                },
              }));
            }
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            assert.equal(captured.preflightAcknowledged, true);
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: {
                chat_id: frame.payload.chat_id,
                message_id: message.message_id,
              },
            }));
            setTimeout(() => {
              captured.terminalSent = true;
              ws.send(JSON.stringify({ type: "ai_typing_started", payload: {
                chat_id: frame.payload.chat_id, user_message_id: message.message_id,
                turn_id: captured.preflightPayload?.turn_id, task_id: "owned-initial-task",
                title: "Contact a plumber", category: "general_knowledge", icon_names: ["wrench"],
              }}));
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: frame.payload.chat_id,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "stale streamed content",
                  is_final_chunk: true,
                  category: "general_knowledge",
                  model_name: "test-model",
                  recovery_job_id: recoveryJobId,
                  recovery_protocol_version: 1,
                  recovery_turn_id: captured.preflightPayload?.turn_id,
                  created_at: Number((captured.preflightPayload?.encrypted_user_message as Record<string, unknown>).created_at) + 2,
                },
              }));
              ws.send(JSON.stringify({
                type: "post_processing_metadata",
                payload: {
                  chat_id: frame.payload.chat_id,
                  turn_id: captured.preflightPayload?.turn_id,
                  user_message_id: message.message_id,
                  updated_chat_title: "Updated plumber title",
                  source_title_v: 1,
                  source_metadata_v: 1,
                },
              }));
            }, 10);
          }
          if (frame.type === "encrypted_chat_metadata") {
            captured.metadataPayload = frame.payload;
            ws.send(JSON.stringify({ type: "encrypted_metadata_stored", payload: { chat_id: frame.payload.chat_id } }));
          }
          if (frame.type === "update_post_processing_metadata") {
            assert.equal(captured.preflightAcknowledged, true, "initial title must wait for durable admission ACK");
            if (!captured.initialPostProcessingPayload) {
              captured.initialPostProcessingPayload = frame.payload;
              captured.initialHeaderBeforeTerminal = !captured.terminalSent;
              if (holdInitialHeaderAck) {
                releaseInitialHeaderAck = () => { initialHeaderAcknowledged = true;
                  ws.send(JSON.stringify({ type: "post_processing_metadata_stored", payload: { chat_id: frame.payload.chat_id } })); };
                return;
              }
              initialHeaderAcknowledged = true;
            }
            captured.postProcessingPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "post_processing_metadata_stored",
              payload: { chat_id: frame.payload.chat_id },
            }));
          }
          if (frame.type === "recovery_job_claim") {
            assert.equal(frame.payload.job_id, recoveryJobId);
            assert.equal(captured.terminalSent, true);
            assert.ok(sealedPayloadForTest);
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                state: "LEASED",
                lease_token: "lease-token-1",
                lease_generation: 3,
                sealed_payload: sealedPayloadForTest,
                chat_id: captured.preflightPayload?.chat_id,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "recovery_job_persist") {
            captured.persistPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "recovery_job_persisted",
              payload: { job_id: recoveryJobId, state: "TERMINAL", committed_messages_v: 2 },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const previousDebug = process.env.OPENMATES_DEBUG;
    const previousTiming = process.env.OPENMATES_TRACE_SEND_TIMING;
    const previousConsoleError = console.error;
    const admissionDebugLines: string[] = [];
    const timingLines: string[] = [];
    if (supported) {
      process.env.OPENMATES_DEBUG = "1";
      process.env.OPENMATES_TRACE_SEND_TIMING = "1";
      console.error = (...values: unknown[]) => {
        if (typeof values[0] === "string" && values[0].startsWith("[chat admission preparation]")) {
          admissionDebugLines.push(values[0]);
        } else if (typeof values[0] === "string" && values[0].startsWith("[chat send timing]")) {
          timingLines.push(values[0]);
        } else previousConsoleError(...values);
      };
    }
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const preparedChatId = client.preparedNewChatId();
      const preparedSession = client.getSession();
      await client.whoAmI();
      assert.notStrictEqual(client.getSession(), preparedSession, "auth reloads the same owner into a new session object");
      let metadataReady!: () => void;
      const metadataDone = new Promise<void>(resolve => { metadataReady = resolve; });
      const result = await client.sendMessage({
        onMetadata: metadata => { if (metadata.updatedChatTitle === "Updated plumber title") metadataReady(); },
        newChatId: preparedChatId,
        message: "Email [EMAIL_1_com] or call [PHONE_1_567].",
        ...(supported ? { jevContext: { project_focus_candidates: [{
          project_id: "stale-caller-project", name: "Stale", summary: "Must not route",
          auto_selection: true, focus_activation_policy: "delayed" as const,
        }] } } : {}),
        piiMappings: [
          { placeholder: "[EMAIL_1_com]", original: "sarah@example.com", type: "EMAIL" },
          { placeholder: "[PHONE_1_567]", original: "+1 (555) 123-4567", type: "PHONE" },
        ],
      });
      if (holdInitialHeaderAck) {
        assert.equal(initialHeaderAcknowledged, false, "required encrypted reply settles before initial header ACK");
        assert.equal(result.assistant, "ok");
        assert.ok(releaseInitialHeaderAck); releaseInitialHeaderAck();
      }
      await metadataDone;
      if (supported) {
        assert.deepEqual(captured.frameTypes.filter(type => type === "personal_memory_snapshot"
          || type === "personal_send_context_snapshot"), ["personal_memory_snapshot"]);
        assert.equal(projectListRequested, true);
        assert.equal(projectListCompletedAfterAdmission, true);
        const timingPhases = timingLines.map(line => {
          assert.match(line, /^\[chat send timing\] phase=[a-z_]+ elapsed_ms=\d+$/);
          for (const secret of ["Email [EMAIL_1_com]", "test-refresh-token", preparedChatId, ownerId])
            assert.equal(line.includes(secret), false);
          return line.match(/phase=([a-z_]+)/)?.[1];
        });
        for (const phase of ["send_begin", "snapshot_request", "snapshot_ready", "memory_decrypt_ready",
          "privacy_begin", "privacy_ready", "key_begin", "key_ready", "preflight_begin",
          "preflight_ready", "admission_frame", "admission_ack", "routing_prepared",
          "routing_frame", "routing_ack", "details_prepared", "details_frame", "details_ack"])
          assert.ok(timingPhases.includes(phase), `missing payload-free ${phase} trace`);
        assert.equal(admissionDebugLines.length, 1);
        const line = admissionDebugLines[0];
        assert.match(line, /^\[chat admission preparation\] sdk_minted=true defer_recovery=true combined_admission=true caps_wait_ms=\d+ key_wait_ms=\d+ recovery_keypair_ms=\d+ encrypt_payload_ms=\d+ socket_ready_to_frame_dispatch_ms=\d+ frame_dispatch_from_send_start_ms=\d+ wire_send_ms=\d+$/);
        for (const secret of [
          "Email [EMAIL_1_com] or call [PHONE_1_567].", "test-refresh-token",
          "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", preparedChatId,
          "sarah@example.com", ownerId,
        ]) assert.equal(line.includes(secret), false);
      }

      const userMessage = captured.messagePayload?.message as Record<string, unknown> | undefined;
      assert.equal(userMessage?.content, "Email [EMAIL_1_com] or call [PHONE_1_567].");
      assert.equal(JSON.stringify(captured.messagePayload).includes("sarah@example.com"), false);
      assert.equal(JSON.stringify(captured.messagePayload).includes("+1 (555) 123-4567"), false);

      assert.ok(captured.preflightPayload);
      assert.equal(captured.preflightPayload.chat_id, preparedChatId);
      const admitted = captured.preflightPayload.inference_request as Record<string, unknown>;
      assert.equal(admitted.client_context_pending, supported ? true : undefined);
      assert.equal(admitted.client_context_request_id === undefined, !supported);
      if (supported) assert.equal(admitted.project_focus_candidates, undefined);
      else assert.deepEqual(admitted.project_focus_candidates, []);
      assert.deepEqual(contextFrames.map(frame => frame.phase), supported ? ["routing", "details"] : []);
      if (supported) assert.deepEqual(
        (contextFrames[0]?.context as Record<string, unknown>)?.project_focus_candidates, [],
        "deferred routing must use the fresh owner-scoped Project listing, not supplied candidates",
      );
      for (const frame of contextFrames) {
        assert.equal(frame.request_id, admitted.client_context_request_id);
        assert.equal(frame.chat_id, captured.preflightPayload.chat_id);
        assert.equal(frame.turn_id, captured.preflightPayload.turn_id);
        assert.equal(frame.message_id, captured.preflightPayload.message_id);
      }
      assert.deepEqual(captured.warmupPayload, {});
      const sendType = supported ? "chat_turn_admit" : "chat_turn_preflight";
      assert.equal(captured.frameTypes.indexOf("chat_metadata_warmup") < captured.frameTypes.indexOf(sendType), true);
      assert.equal(captured.frameTypes.includes("chat_message_added"), !supported);
      assert.equal(captured.frameTypes.includes("chat_turn_admit"), supported);
      if (supported) assert.equal(admissionBeforeDiscovery, true);
      if (!supported) assert.ok(captured.frameTypes.indexOf("chat_message_added") > captured.frameTypes.indexOf("chat_turn_preflight"));
      assert.equal(captured.initialHeaderBeforeTerminal, true, "initial title persists during the main response");
      assert.equal(captured.frameTypes.indexOf("update_post_processing_metadata") < captured.frameTypes.indexOf("recovery_job_persist"), true);
      assert.equal(captured.metadataPayload?.message_id, undefined);
      const inferenceRequest = captured.preflightPayload.inference_request as Record<string, unknown>;
      const finalInferenceRequest = { ...captured.messagePayload };
      delete finalInferenceRequest.protocol_version;
      delete finalInferenceRequest.preflight_id;
      assert.deepEqual(inferenceRequest, finalInferenceRequest);

      const encryptedUserMessage = captured.preflightPayload.encrypted_user_message as Record<string, unknown>;
      assert.deepEqual(Object.keys(encryptedUserMessage).sort(), [
        "chat_id",
        "client_message_id",
        "created_at",
        "encrypted_content",
        "encrypted_pii_mappings",
        "encrypted_sender_name",
        "role",
        "updated_at",
      ]);
      assert.equal(typeof encryptedUserMessage.encrypted_pii_mappings, "string");
      assert.equal(typeof encryptedUserMessage.encrypted_sender_name, "string");
      assert.equal(JSON.stringify(encryptedUserMessage).includes("Email [EMAIL_1_com]"), false);
      assert.equal(JSON.stringify(encryptedUserMessage).includes("sarah@example.com"), false);
      const newChatMetadata = captured.preflightPayload.encrypted_chat_metadata as Record<string, unknown>;
      assert.deepEqual(Object.keys(newChatMetadata).sort(), [
        "created_at",
        "encrypted_chat_key",
        "encrypted_slug",
        "encrypted_title",
        "slug_lookup_hash",
        "updated_at",
      ]);
      assert.equal(typeof newChatMetadata.encrypted_slug, "string");
      assert.match(String(newChatMetadata.slug_lookup_hash), /^[0-9a-f]{64}$/);
      assert.equal(JSON.stringify(newChatMetadata).includes("sarah@example.com"), false);

      const masterKey = Buffer.alloc(32);
      const encryptedChatKey = String(captured.preflightPayload.encrypted_chat_key);
      const chatKey = await decryptBytesWithAesGcm(encryptedChatKey, masterKey);
      assert.ok(chatKey);
      const automaticChatSlug = await decryptWithAesGcmCombined(
        String(newChatMetadata.encrypted_slug),
        chatKey,
      );
      assert.ok(automaticChatSlug);
      assert.ok(automaticChatSlug.length <= 80);
      assert.equal(
        automaticChatSlug.endsWith(String(captured.preflightPayload.chat_id)),
        true,
      );
      const mappingsJson = await decryptWithAesGcmCombined(
        String(encryptedUserMessage.encrypted_pii_mappings),
        chatKey,
      );
      assert.deepEqual(JSON.parse(mappingsJson ?? "[]"), [
        { placeholder: "[EMAIL_1_com]", original: "sarah@example.com", type: "EMAIL" },
        { placeholder: "[PHONE_1_567]", original: "+1 (555) 123-4567", type: "PHONE" },
      ]);
      assert.ok(captured.metadataPayload);
      assert.equal(await decryptWithAesGcmCombined(String(captured.initialPostProcessingPayload?.encrypted_title), chatKey), "Contact a plumber");
      assert.equal(captured.metadataPayload.encrypted_title, undefined, "initial title never uses the unconditional title writer");
      assert.deepEqual(captured.initialPostProcessingPayload?.versions, holdInitialHeaderAck ? undefined : { title_v: 1, metadata_v: 1 },
        "missing generated-title base stays unversioned; known source versions retain the existing protocol");
      assert.equal(await decryptWithAesGcmCombined(String(captured.metadataPayload.encrypted_chat_category), chatKey), "general_knowledge");
      assert.equal(await decryptWithAesGcmCombined(String(captured.metadataPayload.encrypted_icon), chatKey), "wrench");
      assert.ok(captured.postProcessingPayload);
      assert.equal(
        await decryptWithAesGcmCombined(String(captured.postProcessingPayload.encrypted_title), chatKey),
        "Updated plumber title",
      );
      assert.deepEqual(captured.postProcessingPayload.versions, { title_v: 2, metadata_v: 2 });
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      assert.equal(captured.frameTypes.includes("recovery_job_claim"), true);
      assert.equal(captured.frameTypes.includes("recovery_job_persist"), true);
      assert.equal(result.assistant, "ok");
      assert.ok(captured.persistPayload);
      assert.equal(captured.persistPayload.job_id, recoveryJobId);
      assert.equal(captured.persistPayload.lease_token, "lease-token-1");
      assert.equal(captured.persistPayload.lease_generation, 3);
      assert.equal(captured.persistPayload.expected_messages_v, 1);
      const encryptedAssistant = captured.persistPayload.encrypted_assistant_message as Record<string, unknown>;
      assert.equal(encryptedAssistant.client_message_id, assistantMessageId);
      assert.equal(encryptedAssistant.created_at, Number(encryptedUserMessage.created_at) + 2);
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_content), chatKey),
        "ok",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_sender_name), chatKey),
        "George",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_category), chatKey),
        "general_knowledge",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_model_name), chatKey),
        "test-model",
      );
    } finally {
      console.error = previousConsoleError;
      if (previousDebug === undefined) delete process.env.OPENMATES_DEBUG;
      else process.env.OPENMATES_DEBUG = previousDebug;
      if (previousTiming === undefined) delete process.env.OPENMATES_TRACE_SEND_TIMING;
      else process.env.OPENMATES_TRACE_SEND_TIMING = previousTiming;
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  for (const missingChild of [false, true, "unavailable"]) {
  it(`persists terminal recovery embeds including missing children: ${missingChild}`, async () => {
    const ownerId = "11111111-1111-4111-8111-111111111111";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const embedId = "55555555-5555-4555-8555-555555555555";
    const childId = "66666666-6666-4666-8666-666666666666";
    const grandchildId = "77777777-7777-4777-8777-777777777777";
    const storedIds: string[] = [];
    const captured: {
      preflightPayload?: Record<string, unknown>;
      frameTypes: string[];
      storeEmbedPayload?: Record<string, unknown>;
      storeEmbedKeysPayload?: Record<string, unknown>;
    } = { frameTypes: [] };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
        return;
      }
      if (
        request.method === "GET" &&
        request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false"
      ) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_admit") {
            captured.preflightPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: {
                preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                turn_id: frame.payload.turn_id,
              },
            }));
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: {
                chat_id: frame.payload.chat_id,
                message_id: message.message_id,
              },
            }));
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "send_embed_data",
                payload: {
                  embed_id: embedId,
                  embed_ids: missingChild ? [childId] : [],
                  type: "code",
                  content: '{"type":"code","code":"<html></html>","status":"finished"}',
                  status: "finished",
                  chat_id: frame.payload.chat_id,
                  message_id: assistantMessageId,
                },
              }));
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: frame.payload.chat_id,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "ok",
                  is_final_chunk: true,
                  recovery_job_id: recoveryJobId,
                  recovery_protocol_version: 1,
                },
              }));
              ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: frame.payload.chat_id } }));
            }, 10);
          }
          if (frame.type === "recovery_job_claim") {
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                state: "TERMINAL",
                chat_id: captured.preflightPayload?.chat_id,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "request_embed" && [childId, grandchildId].includes(String(frame.payload.embed_id))) {
            ws.send(JSON.stringify({type: "send_embed_data", payload: {
              embed_id: frame.payload.embed_id, parent_embed_id: frame.payload.embed_id === childId ? embedId : childId, status: missingChild === "unavailable" ? "error" : "finished",
              embed_ids: frame.payload.embed_id === childId ? [grandchildId] : [],
              content: 'code: "original child bytes"', type: "code",
              chat_id: captured.preflightPayload?.chat_id, message_id: assistantMessageId,
            }}));
          }
          if (frame.type === "store_embed") {
            storedIds.push(String(frame.payload.embed_id));
            if (frame.payload.embed_id === embedId) captured.storeEmbedPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "store_embed_confirmed",
              payload: {
                request_id: frame.payload.request_id,
                embed_id: frame.payload.embed_id,
              },
            }));
          }
          if (frame.type === "store_embed_keys") {
            captured.storeEmbedKeysPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "store_embed_keys_confirmed",
              payload: { request_id: frame.payload.request_id, created_count: 2, failed_count: 0 },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      if (missingChild === "unavailable") {
        await assert.rejects(client.sendMessage({ message: "Make HTML from this screenshot" }), /original finished child data is unavailable/);
        assert.deepEqual(storedIds, []);
        return;
      }
      const result = await client.sendMessage({ message: "Make HTML from this screenshot" });

      assert.equal(result.assistant, "ok");
      assert.deepEqual(storedIds, missingChild ? [embedId, childId, grandchildId] : [embedId]);
      assert.equal(captured.frameTypes.includes("recovery_job_persist"), false);
      assert.equal(captured.storeEmbedPayload?.embed_id, embedId);
      assert.equal(captured.storeEmbedPayload?.status, "finished");
      assert.equal(captured.storeEmbedPayload?.hashed_user_id, createHash("sha256").update(ownerId).digest("hex"));
      const keyRows = captured.storeEmbedKeysPayload?.keys as Array<Record<string, unknown>> | undefined;
      assert.equal(keyRows?.length, 2);
      assert.deepEqual(keyRows?.map((row) => row.key_type).sort(), ["chat", "master"]);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  }

  // contract-test: supporting surface=sdks.npm assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("refreshes a terminal version conflict without replaying the same typed output twice", async () => {
    const ownerId = "11111111-1111-4111-8111-111111111111";
    const assistantId = "33333333-3333-4333-8333-333333333333";
    const jobId = "44444444-4444-4444-8444-444444444444";
    const outputId = "55555555-5555-4555-8555-555555555555";
    const recordId = "66666666-6666-4666-8666-666666666666";
    const output = (chatId: string, turnId: string) => ({
      record_id: recordId, root_chat_id: chatId, target_chat_id: chatId,
      turn_id: turnId, subject_id: outputId, output_kind: "embed",
      output_version: 1, chat_key_version: 1,
    });
    const captured: {
      preflight?: Record<string, any>; sealed?: string; nestedDiscovery: number;
      persistVersions: number[]; nestedReplay: number; originalReplay: number;
      pending: boolean;
    } = { nestedDiscovery: 0, persistVersions: [], nestedReplay: 0, originalReplay: 0, pending: true };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: ownerId } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, any> };
          if (frame.type === "chat_turn_admit") {
            captured.preflight = frame.payload;
            captured.sealed = JSON.stringify(await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantId, category: "general_knowledge",
                chat_id: frame.payload.chat_id, content: "recovered answer",
                job_id: jobId, key_version: 1, model_name: "test-model",
                turn_id: frame.payload.turn_id,
              })), {
                recoveryPublicKey: String(frame.payload.recovery_public_key), ownerId,
                chatId: String(frame.payload.chat_id), turnId: String(frame.payload.turn_id),
                jobId, assistantMessageId: assistantId, keyVersion: 1,
              },
            ));
            ws.send(JSON.stringify({ type: "chat_turn_preflight_ack", payload: {
              preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              turn_id: frame.payload.turn_id,
            } }));
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            const message = frame.payload.message as Record<string, any>;
            ws.send(JSON.stringify({ type: "chat_message_confirmed", payload: {
              chat_id: frame.payload.chat_id, message_id: message.message_id,
            } }));
            setTimeout(() => {
              ws.send(JSON.stringify({ type: "ai_message_update", payload: {
                chat_id: frame.payload.chat_id, user_message_id: message.message_id,
                message_id: assistantId, full_content_so_far: "streamed answer", is_final_chunk: true,
                recovery_job_id: jobId, recovery_protocol_version: 1,
                recovery_turn_id: captured.preflight?.turn_id,
              } }));
              ws.send(JSON.stringify({ type: "recovery_outputs_available", payload: {
                outputs: [output(String(frame.payload.chat_id), String(captured.preflight?.turn_id))],
              } }));
            }, 10);
          } else if (frame.type === "recovery_job_claim") {
            ws.send(JSON.stringify({ type: "recovery_job_claimed", payload: {
              job_id: jobId, state: "LEASED", lease_token: "lease-token-1", lease_generation: 3,
              sealed_payload: captured.sealed, chat_id: captured.preflight?.chat_id,
              turn_id: captured.preflight?.turn_id, assistant_message_id: assistantId,
              chat_key_version: 1,
            } }));
          } else if (frame.type === "recovery_job_persist") {
            captured.persistVersions.push(Number(frame.payload.expected_messages_v));
            ws.send(JSON.stringify(captured.persistVersions.length === 1
              ? { type: "error", payload: { code: "version_conflict", message: "stale chat version", job_id: jobId } }
              : { type: "recovery_job_persisted", payload: { job_id: jobId, state: "TERMINAL", committed_messages_v: 4 } }));
          } else if (frame.type === "phased_sync_request") {
            captured.nestedDiscovery += 1;
            ws.send(JSON.stringify({ type: "recovery_outputs_available", payload: {
              outputs: [output(String(captured.preflight?.chat_id), String(captured.preflight?.turn_id))],
            } }));
            ws.send(JSON.stringify({ type: "phase_2_last_20_chats_ready", payload: {
              total_chat_count: 1, chats: [{ chat_details: {
                id: captured.preflight?.chat_id,
                encrypted_chat_key: captured.preflight?.encrypted_chat_key,
                messages_v: 3, title_v: 0, draft_v: 0,
              } }],
            } }));
            ws.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          }
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      (client as any).replayRecoveryOutputPages = async (_ws: unknown, _owner: unknown, pages: any[][]) => {
        assert.equal(pages.flat()[0]?.record_id, recordId);
        captured.nestedReplay += 1;
        if (!captured.pending) throw new Error("recovery_output_not_found");
        captured.pending = false;
        return 1;
      };
      (client as any).replayCurrentTurnRecoveryOutputPages = async (_ws: unknown, _owner: unknown, pages: any[][]) => {
        assert.equal(pages.flat()[0]?.record_id, recordId);
        captured.originalReplay += 1;
        if (!captured.pending) throw new Error("recovery_output_not_found");
        captured.pending = false;
      };
      const result = await client.sendMessage({ message: "Create an editable diagram" });
      assert.equal(result.assistant, "recovered answer");
      assert.deepEqual(captured.persistVersions, [1, 3]);
      assert.equal(captured.nestedDiscovery, 1);
      assert.equal(captured.nestedReplay, 0);
      assert.equal(captured.originalReplay, 1);
      assert.equal(captured.pending, false);
      client.endInteractiveViewerSession();
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  // contract-test: supporting surface=cli assertions=focus-modes.full-instruction,focus-modes.restoration
  for (const restoredFocus of ["jobs-career_insights", null]) {
  it(`lazily registers epoch-1 recovery material for an old saved chat (${restoredFocus ?? "off"})`, async () => {
    const chatId = "11111111-1111-4111-8111-111111111111";
    const ownerId = "22222222-2222-4222-8222-222222222222";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const rawChatKey = new Uint8Array(32).fill(7);
    const encryptedChatKey = await encryptBytesWithAesGcm(rawChatKey, new Uint8Array(32));
    writeFileSync(join(stateDir, "sync_cache.json"), JSON.stringify({
      syncedAt: Date.now(),
      totalChatCount: 1,
      loadedChatCount: 1,
      chats: [{
        details: { id: chatId, encrypted_chat_key: encryptedChatKey, messages_v: 7,
          encrypted_active_focus_id: restoredFocus ? await encryptWithAesGcmCombined(restoredFocus, rawChatKey) : null },
        messages: [],
      }],
      embeds: [],
      embedKeys: [],
    }));

    const captured: {
      preflightPayload?: Record<string, unknown>;
      messagePayload?: Record<string, unknown>;
      persistPayload?: Record<string, unknown>;
      focusUpdate?: Record<string, unknown>;
      frameTypes: string[];
    } = { frameTypes: [] };
    let sealedPayloadForTest: string | null = null;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
        return;
      }
      if (
        request.method === "GET" &&
        request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false"
      ) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      if (request.method === "GET" && request.url?.startsWith(`/v1/chats/${chatId}/messages/window?`)) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ messages: [], has_more_before: false, start_cursor: null }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "phased_sync_request") {
            ws.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          }
          if (frame.type === "chat_turn_admit") {
            captured.preflightPayload = frame.payload;
            sealedPayloadForTest = JSON.stringify(await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantMessageId,
                category: null,
                chat_id: chatId,
                content: "ok",
                job_id: recoveryJobId,
                key_version: 1,
                model_name: null,
                turn_id: frame.payload.turn_id,
              })),
              {
                recoveryPublicKey: String(frame.payload.recovery_public_key),
                ownerId,
                chatId,
                turnId: String(frame.payload.turn_id),
                jobId: recoveryJobId,
                assistantMessageId,
                keyVersion: 1,
              },
            ));
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: { preflight_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", turn_id: frame.payload.turn_id },
            }));
          }
          if (frame.type === "update_encrypted_active_focus_id") captured.focusUpdate = frame.payload;
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            ws.send(JSON.stringify({ type: "focus_mode_activated", payload: { chat_id: chatId, focus_id: "jobs-career_insights" } }));
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: { chat_id: chatId, message_id: message.message_id, new_messages_v: 9 },
            }));
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: chatId,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "ok",
                  is_final_chunk: true,
                },
              }));
              ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: chatId } }));
            }, 10);
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "recovery_jobs_available",
                payload: {
                  jobs: [{
                    job_id: recoveryJobId,
                    chat_id: chatId,
                    turn_id: captured.preflightPayload?.turn_id,
                    assistant_message_id: assistantMessageId,
                    chat_key_version: 1,
                  }],
                },
              }));
            }, 30);
          }
          if (frame.type === "recovery_job_claim") {
            assert.ok(sealedPayloadForTest);
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                state: "LEASED",
                lease_token: "lease-token-old-chat",
                lease_generation: 2,
                sealed_payload: sealedPayloadForTest,
                chat_id: chatId,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "recovery_job_persist") {
            captured.persistPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "recovery_job_persisted",
              payload: { job_id: recoveryJobId, state: "TERMINAL", committed_messages_v: 9 },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      // This fixture tests request/recovery metadata with an empty phased-sync response.
      await client.sendMessage({ message: "Continue this old chat", chatId, messageHistory: [] });

      assert.equal(captured.messagePayload?.active_focus_id, restoredFocus);
      assert.equal(captured.focusUpdate?.chat_id, chatId);
      assert.equal(await decryptWithAesGcmCombined(String(captured.focusUpdate?.encrypted_active_focus_id), rawChatKey), "jobs-career_insights");
      assert.ok(captured.preflightPayload);
      assert.equal(captured.preflightPayload.expected_messages_v, 7);
      const existingContext = captured.preflightPayload.inference_request as Record<string, unknown>;
      assert.equal(existingContext.client_context_pending, undefined, "queued existing turns must not depend on a short-lived continuation");
      assert.equal(existingContext.client_context_request_id, undefined);
      assert.deepEqual(existingContext.project_focus_candidates, []);
      assert.deepEqual(existingContext.project_focus_documents, []);
      assert.equal(captured.frameTypes.includes("chat_turn_context_ready"), false);
      assert.equal(captured.preflightPayload.encrypted_chat_key, encryptedChatKey);
      assert.equal(captured.preflightPayload.chat_key_version, 1);
      assert.equal(typeof captured.preflightPayload.recovery_public_key, "string");
      assert.equal(captured.preflightPayload.encrypted_chat_metadata, undefined);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), false);
      assert.equal(captured.preflightPayload.protocol_version, 1);
      assert.equal(captured.messagePayload?.preflight_id, undefined);
      assert.equal(captured.frameTypes.filter(type => type === "chat_turn_admit").length, 1);
      assert.equal(captured.frameTypes.includes("chat_message_added"), false);
      assert.equal(captured.messagePayload?.turn_id, captured.preflightPayload.turn_id);
      assert.equal(captured.messagePayload?.recovery_public_key, captured.preflightPayload.recovery_public_key);
      assert.equal(captured.messagePayload?.chat_key_version, 1);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      assert.equal(captured.persistPayload?.expected_messages_v, 9);
      assert.equal(captured.persistPayload?.lease_token, "lease-token-old-chat");
      assert.equal(captured.persistPayload?.lease_generation, 2);
    } finally {
      rmSync(join(stateDir, "sync_cache.json"), { force: true });
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
  }

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("returns after confirmation for saved team messages that do not mention OpenMates", async () => {
    const teamId = "55555555-5555-4555-8555-555555555555";
    const ownerId = "66666666-6666-4666-8666-666666666666";
    const captured: {
      messagePayload?: Record<string, unknown>;
      preflightPayload?: Record<string, unknown>;
      frameTypes: string[];
    } = { frameTypes: [] };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        if (request.method === "POST" && request.url === "/v1/auth/session") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: ownerId } }));
          return;
        }
        if (request.method === "GET" && request.url === `/v1/sdk/memories?team_id=${teamId}`) {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ memories: [] }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/teams/name-approval") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ approval_token: "approved-team-no-ai" }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/teams") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ team: { team_id: teamId, ...(raw ? JSON.parse(raw) as Record<string, unknown> : {}) } }));
          return;
        }
        response.writeHead(404);
        response.end();
      });
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_admit") {
            captured.preflightPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: { preflight_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", turn_id: frame.payload.turn_id },
            }));
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: { chat_id: frame.payload.chat_id, message_id: message.message_id, new_messages_v: 1 },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const originalWaitForMessage = OpenMatesWsClient.prototype.waitForMessage;
    const confirmationTimeouts: number[] = [];
    OpenMatesWsClient.prototype.waitForMessage = function (
      expectedType: string,
      predicate?: (payload: unknown) => boolean,
      timeoutMs?: number,
    ) {
      if (expectedType === "chat_message_confirmed") {
        confirmationTimeouts.push(timeoutMs ?? 20_000);
      }
      return originalWaitForMessage.call(this, expectedType, predicate, timeoutMs);
    };

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.createTeam({ teamId, name: "Team No AI" });
      const result = await client.sendMessage({
        message: "Team note without a mate mention",
        teamId,
        precollectResponse: true,
        responseTimeoutMs: 50,
      });

      assert.equal(result.status, "completed");
      assert.equal(result.assistant, "");
      assert.equal(result.messageId, null);
      assert.equal(captured.messagePayload?.team_id, teamId);
      assert.equal(captured.preflightPayload?.team_id, teamId);
      assert.equal(typeof captured.preflightPayload?.encrypted_chat_key, "string");
      assert.equal(captured.frameTypes.includes("recovery_job_claim"), false);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      assert.deepEqual(confirmationTimeouts, [50]);
    } finally {
      OpenMatesWsClient.prototype.waitForMessage = originalWaitForMessage;
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
  it("returns a queued receipt after ciphertext confirmation without waiting for the prior AI turn", async () => {
    const ownerId = "77777777-7777-4777-8777-777777777777";
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "queued-test-ws-token", user: { id: ownerId } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type === "chat_turn_admit") {
            ws.send(JSON.stringify({ type: "chat_turn_preflight_ack", payload: {
              preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", turn_id: frame.payload.turn_id,
            } }));
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            const user = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({ type: "chat_message_confirmed", payload: {
              chat_id: frame.payload.chat_id, message_id: user.message_id, new_messages_v: 1,
            } }));
            ws.send(JSON.stringify({ type: "message_queued", payload: {
              chat_id: frame.payload.chat_id, user_message_id: user.message_id,
              active_task_id: "active-task", queue_mode: "follow_up", queue_revision: 1,
            } }));
          }
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.sendMessage({ message: "Please follow up", responseTimeoutMs: 1_000 });
      assert.equal(result.status, "queued");
      assert.equal(result.userMessageId !== undefined, true);
      assert.equal(result.messageId, null);
      assert.equal(result.queueRevision, 1);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
  it("reports a saved turn whose queue handoff is paused instead of waiting for AI", async () => {
    const ownerId = "77777777-7777-4777-8777-777777777777";
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "paused-test-ws-token", user: { id: ownerId } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type === "chat_turn_admit") {
            ws.send(JSON.stringify({ type: "chat_turn_preflight_ack", payload: {
              preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", turn_id: frame.payload.turn_id,
            } }));
          }
          if (frame.type === "chat_turn_admit") frame.payload = frame.payload.inference_request as Record<string, unknown>;
          if (frame.type === "chat_turn_admit" || frame.type === "chat_message_added") {
            const user = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({ type: "chat_message_confirmed", payload: {
              chat_id: frame.payload.chat_id, message_id: user.message_id, new_messages_v: 1,
            } }));
            ws.send(JSON.stringify({ type: "queued_handoff_paused", payload: {
              chat_id: frame.payload.chat_id, message_id: user.message_id,
              reason_code: "durable_queue_marker_unavailable", retryable: false,
            } }));
          }
        });
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        client.sendMessage({ message: "Please follow up", responseTimeoutMs: 1_000 }),
        /Message saved, but AI handoff is paused/,
      );
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("CLI saved chat history identities", () => {
  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
  it("replays canonical client IDs while retaining storage IDs for saved-message lookup", () => {
    const messages = [
      { id: "stored-user", clientMessageId: "client-user", chatId: "chat-1", role: "user",
        content: "Earlier private request", senderName: "User", category: "news", modelName: null,
        createdAt: 100, embedIds: [], piiMappings: [{ placeholder: "[EMAIL_1]", original: "private@example.test" }] },
      { id: "stored-assistant", clientMessageId: "client-assistant", chatId: "chat-1", role: "assistant",
        content: "Earlier answer", senderName: "Assistant", category: "news", modelName: "model",
        createdAt: 101, embedIds: [] },
      { id: "legacy-stored", chatId: "chat-1", role: "system", content: "Earlier context",
        senderName: null, category: null, modelName: null, createdAt: 102, embedIds: [] },
    ];
    const history = buildSavedChatMessageHistory(messages, "chat-1");
    assert.deepEqual(history.map((message) => message.message_id), [
      "client-user", "client-assistant", "legacy-stored",
    ]);
    assert.deepEqual(messages.map(canonicalSavedChatMessageId), [
      "client-user", "client-assistant", "legacy-stored",
    ]);
    assert.deepEqual(history.map((message) => buildInferenceHistoryMessage(message, "chat-1")), [
      { message_id: "client-user", chat_id: "chat-1", role: "user", sender_name: "User",
        content: "Earlier private request", created_at: 100, category: undefined },
      { message_id: "client-assistant", chat_id: "chat-1", role: "assistant", sender_name: "Assistant",
        content: "Earlier answer", created_at: 101, category: "news" },
      { message_id: "legacy-stored", chat_id: "chat-1", role: "system", sender_name: "system",
        content: "Earlier context", created_at: 102, category: undefined },
    ]);
    assert.equal(JSON.stringify(history).includes("private@example.test"), false);
    assert.equal(messages[0].id, "stored-user");
  });
});

describe("CLI incognito chat payloads", () => {
	// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
	it("preserves only assistant categories in inference history", () => {
		assert.deepEqual(
			buildInferenceHistoryMessage({
				message_id: "assistant-history",
				role: "assistant",
				sender_name: "Assistant",
				content: "Earlier answer",
				created_at: 101,
				category: "news",
			}, "chat-1"),
			{
				message_id: "assistant-history",
				chat_id: "chat-1",
				role: "assistant",
				sender_name: "Assistant",
				content: "Earlier answer",
				created_at: 101,
				category: "news",
			},
		);

		assert.equal(buildInferenceHistoryMessage({
			message_id: "user-history",
			role: "user",
			sender_name: "User",
			content: "Earlier question",
			created_at: 100,
			category: "news",
		}, "chat-1").category, undefined);
	});

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("can include known Learning Mode context without changing incognito state", async () => {
    const captured: { messagePayload?: Record<string, unknown>; frameTypes: string[] } = {
      frameTypes: [],
    };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type !== "chat_message_added") return;

          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: {
              chat_id: frame.payload.chat_id,
              message_id: message.message_id,
            },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
              category: "general_knowledge",
              model_name: "test-model",
            },
          }));
          ws.send(JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: frame.payload.chat_id },
          }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Explain slowly",
        incognito: true,
        learningMode: { enabled: true, ageGroup: "16_18" },
        precollectResponse: true,
      });

      assert.equal(captured.messagePayload?.is_incognito, true);
      assert.deepEqual(captured.messagePayload?.learning_mode, {
        enabled: true,
        age_group: "16_18",
      });
      assert.equal(captured.frameTypes.includes("chat_turn_preflight"), false);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), false);
      assert.equal(captured.messagePayload?.protocol_version, undefined);
      assert.equal(captured.messagePayload?.preflight_id, undefined);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("sends current message history with incognito messages", async () => {
    const captured: { messagePayload?: Record<string, unknown> } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type !== "chat_message_added") return;

          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: {
              chat_id: frame.payload.chat_id,
              message_id: message.message_id,
            },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
              category: "general_knowledge",
              model_name: "test-model",
            },
          }));
          ws.send(JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: frame.payload.chat_id },
          }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Benchmark prompt",
        incognito: true,
        precollectResponse: true,
      });

      assert.equal(captured.messagePayload?.is_incognito, true);
      const message = captured.messagePayload?.message as Record<string, unknown> | undefined;
      const history = captured.messagePayload?.message_history as Record<string, unknown>[] | undefined;
      assert.equal(Array.isArray(history), true);
      assert.equal(history?.length, 1);
      assert.equal(history?.[0]?.message_id, message?.message_id);
      assert.equal(history?.[0]?.chat_id, captured.messagePayload?.chat_id);
      assert.equal(history?.[0]?.role, "user");
      assert.equal(history?.[0]?.sender_name, "User");
      assert.equal(history?.[0]?.content, "Benchmark prompt");
      assert.equal(typeof history?.[0]?.created_at, "number");
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("prepends provided benchmark history before the current incognito message", async () => {
    const captured: { messagePayload?: Record<string, unknown> } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.send(JSON.stringify({ type: "server_capabilities", payload: { capabilities: ["chat_turn_admit_v1", "chat_turn_context_v1", "suggested_followup_message_v1"] } }));
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type !== "chat_message_added") return;
          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: { chat_id: frame.payload.chat_id, message_id: message.message_id },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
            },
          }));
          ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: frame.payload.chat_id } }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Follow-up prompt",
        incognito: true,
        messageHistory: [
          { message_id: "history-1", role: "user", sender_name: "User", content: "Earlier user", created_at: 100 },
          { message_id: "history-2", role: "assistant", sender_name: "Assistant", content: "Earlier assistant", created_at: 101, category: "news" },
        ],
        precollectResponse: true,
      });

      const history = captured.messagePayload?.message_history as Record<string, unknown>[] | undefined;
      assert.equal(history?.length, 3);
      assert.equal(history?.[0]?.message_id, "history-1");
      assert.equal(history?.[1]?.message_id, "history-2");
			assert.equal(history?.[1]?.category, "news");
      assert.equal(history?.[2]?.content, "Follow-up prompt");
      assert.equal(history?.[0]?.chat_id, captured.messagePayload?.chat_id);
      assert.equal(history?.[1]?.chat_id, captured.messagePayload?.chat_id);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("sub-chat encryption helpers", () => {
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
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

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
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
  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("forces a message refresh when cached metadata has no local messages", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: [],
      }),
      0,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("caps the cached messages version to the local message count", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id"}'],
      }),
      1,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
  it("keeps the cached messages version when it matches the local message count", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id-1"}', '{"id":"message-id-2"}'],
      }),
      2,
    );
  });
});
