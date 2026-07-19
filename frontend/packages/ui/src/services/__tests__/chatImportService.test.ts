/**
 * Account Import V1 browser service tests.
 *
 * These tests guard the Settings -> Account -> Import web path. They verify the
 * browser uses the V1 preview/scan/encrypted-persist/complete contract and does
 * not regress to the disabled plaintext settings import endpoint.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import JSZip from "jszip";

const mocks = vi.hoisted(() => ({
  addChat: vi.fn(),
  batchSaveMessages: vi.fn(),
  createAndPersistKey: vi.fn(),
  encryptWithChatKey: vi.fn(),
}));

vi.mock("../db", () => ({
  chatDB: {
    addChat: mocks.addChat,
    batchSaveMessages: mocks.batchSaveMessages,
  },
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    createAndPersistKey: mocks.createAndPersistKey,
  },
}));

vi.mock("../encryption/MessageEncryptor", () => ({
  encryptWithChatKey: mocks.encryptWithChatKey,
}));

function pathFromUrl(input: RequestInfo | URL): string {
  return new URL(String(input)).pathname;
}

describe("chatImportService Account Import V1", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    let randomCounter = 0;
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => `uuid-${++randomCounter}`),
      getRandomValues: (value: Uint8Array) => {
        value.fill(7);
        return value;
      },
      subtle: {
        digest: vi.fn(async (_algorithm: string, data: ArrayBuffer) => {
          const bytes = new Uint8Array(data);
          const digest = new Uint8Array(32);
          for (let index = 0; index < bytes.length; index++) {
            digest[index % digest.length] ^= bytes[index];
          }
          return digest.buffer;
        }),
      },
    });
    mocks.createAndPersistKey.mockResolvedValue({
      chatKey: new Uint8Array(32).fill(1),
      encryptedChatKey: "encrypted-chat-key",
    });
    mocks.encryptWithChatKey.mockImplementation(async (value: string) =>
      `encrypted:${Buffer.from(value).toString("base64")}`,
    );
    Object.defineProperty(window, "location", {
      value: { hostname: "localhost" },
      configurable: true,
    });
  });

  it("parses, previews, scans, encrypts, persists, and completes without plaintext persistence", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/v1/account-imports/preview") {
        return new Response(JSON.stringify({
          import_id: "import-1",
          default_selection_count: 1,
          max_batch_count: 1,
          duplicate_fingerprints: [],
          estimated_credits: 1,
          can_import: true,
          reason: "paid_import_available",
        }));
      }
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify({
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        }));
      }
      if (path === "/v1/account-imports/import-1/persist-encrypted") {
        return new Response(JSON.stringify({
          status: "complete",
          imported_chat_ids: ["uuid-1"],
          encrypted_record_counts: { chats: 1, messages: 1 },
          failures: [],
        }));
      }
      if (path === "/v1/account-imports/import-1/complete") {
        return new Response(JSON.stringify({
          status: "complete",
          imported_count: 1,
          credits_charged: 0,
          credits_released: 0,
          failures: [],
        }));
      }
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    }));

    const service = await import("../chatImportService");
    const claudeJson = JSON.stringify([
        {
          uuid: "claude-chat-1",
          name: "Sensitive web import",
          created_at: "2026-07-18T12:00:00Z",
          updated_at: "2026-07-18T12:05:00Z",
          chat_messages: [
            {
              uuid: "message-1",
              sender: "human",
              text: "browser plaintext must not persist",
              created_at: "2026-07-18T12:01:00Z",
            },
          ],
        },
      ]);
    const file = {
      name: "claude-export.json",
      text: async () => claudeJson,
    } as File;

    const parsed = await service.parseImportFile(file);
    const preview = await service.previewImport(parsed);
    const result = await service.importChats(parsed, parsed.chats, preview);

    expect(result.complete.status).toBe("complete");
    expect(requests.map((request) => request.path)).toEqual([
      "/v1/account-imports/preview",
      "/v1/account-imports/import-1/scan",
      "/v1/account-imports/import-1/persist-encrypted",
      "/v1/account-imports/import-1/complete",
    ]);
    expect(requests.some((request) => request.path === "/v1/settings/import-chat")).toBe(false);

    const persistBody = requests[2].body as { chats: Array<Record<string, unknown>> };
    const persistedChat = persistBody.chats[0];
    expect(String(persistedChat.encrypted_title)).not.toContain("Sensitive web import");
    const persistedMessages = persistedChat.messages as Array<Record<string, unknown>>;
    expect(String(persistedMessages[0].encrypted_content)).not.toContain("browser plaintext");
    expect(persistedChat).not.toHaveProperty("title");
    expect(persistedMessages[0]).not.toHaveProperty("content");
    expect(mocks.addChat).toHaveBeenCalledOnce();
    expect(mocks.batchSaveMessages).toHaveBeenCalledOnce();
  });

  it("fails closed when safety scan blocks every selected chat", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify({
          chats: [],
          credits_reserved: 0,
          messages_blocked: [{ source_chat_id: "source-chat-1", source_message_id: "message-1" }],
          failures: [],
        }));
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    }));

    const service = await import("../chatImportService");
    const parsed = {
      source: "claude" as const,
      fileType: "claude-json" as const,
      skippedDomains: [],
      chats: [{
        provider: "claude" as const,
        source_chat_id: "source-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Blocked chat",
        created_at: null,
        updated_at: null,
        messages: [{
          role: "user" as const,
          content: "unsafe plaintext must never reach persistence",
          created_at: null,
          source_message_id: "message-1",
          provider_metadata: {},
        }],
        embeds: [],
        uploads: [],
        provider_labels: ["claude"],
        source_metadata: {},
      }],
    };

    await expect(service.importChats(parsed, parsed.chats, {
      import_id: "import-1",
      default_selection_count: 1,
      max_batch_count: 1,
      duplicate_fingerprints: [],
      estimated_credits: 1,
      can_import: true,
      reason: "paid_import_available",
    })).rejects.toThrow("Import scan blocked all selected chats");

    expect(requests.map((request) => request.path)).toEqual([
      "/v1/account-imports/import-1/scan",
    ]);
    expect(mocks.createAndPersistKey).not.toHaveBeenCalled();
    expect(mocks.encryptWithChatKey).not.toHaveBeenCalled();
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  it("fails closed when safety scan returns failures with sanitized chats", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify({
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [{ source_chat_id: "source-chat-1", reason: "scanner_timeout" }],
        }));
      }
      if (path === "/v1/account-imports/import-1/complete") {
        return new Response(JSON.stringify({
          status: "partial",
          imported_count: 0,
          credits_charged: 0,
          credits_released: 1,
          failures: body.client_failures,
        }));
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    }));

    const service = await import("../chatImportService");
    const parsed = {
      source: "claude" as const,
      fileType: "claude-json" as const,
      skippedDomains: [],
      chats: [{
        provider: "claude" as const,
        source_chat_id: "source-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Failed scan chat",
        created_at: null,
        updated_at: null,
        messages: [{
          role: "user" as const,
          content: "sanitized but scan reported a failure",
          created_at: null,
          source_message_id: "message-1",
          provider_metadata: {},
        }],
        embeds: [],
        uploads: [],
        provider_labels: ["claude"],
        source_metadata: {},
      }],
    };

    await expect(service.importChats(parsed, parsed.chats, {
      import_id: "import-1",
      default_selection_count: 1,
      max_batch_count: 1,
      duplicate_fingerprints: [],
      estimated_credits: 1,
      can_import: true,
      reason: "paid_import_available",
    })).rejects.toThrow("Import scan failed for one or more selected chats");

    expect(requests.map((request) => request.path)).toEqual([
      "/v1/account-imports/import-1/scan",
      "/v1/account-imports/import-1/complete",
    ]);
    expect(requests[1].body).toMatchObject({
      imported_chat_ids: [],
      source_fingerprints: [],
      client_failures: [{ source_chat_id: "source-chat-1", reason: "scanner_timeout" }],
    });
    expect(mocks.createAndPersistKey).not.toHaveBeenCalled();
    expect(mocks.encryptWithChatKey).not.toHaveBeenCalled();
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  it("does not cache messages that failed encrypted persistence", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    let failedMessageId = "";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify({
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        }));
      }
      if (path === "/v1/account-imports/import-1/persist-encrypted") {
        const chats = body.chats as Array<{ messages: Array<{ message_id: string }> }>;
        failedMessageId = chats[0].messages[1].message_id;
        return new Response(JSON.stringify({
          status: "partial",
          imported_chat_ids: ["uuid-1"],
          encrypted_record_counts: { chats: 1, messages: 1 },
          failures: [{ chat_id: "uuid-1", message_id: failedMessageId, reason: "message_create_failed" }],
        }));
      }
      if (path === "/v1/account-imports/import-1/complete") {
        return new Response(JSON.stringify({
          status: "partial",
          imported_count: 1,
          credits_charged: 0,
          credits_released: 0,
          failures: body.client_failures,
        }));
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    }));

    const service = await import("../chatImportService");
    const parsed = {
      source: "claude" as const,
      fileType: "claude-json" as const,
      skippedDomains: [],
      chats: [{
        provider: "claude" as const,
        source_chat_id: "source-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Partially persisted chat",
        created_at: null,
        updated_at: null,
        messages: [
          {
            role: "user" as const,
            content: "persisted message",
            created_at: null,
            source_message_id: "message-1",
            provider_metadata: {},
          },
          {
            role: "assistant" as const,
            content: "failed message",
            created_at: null,
            source_message_id: "message-2",
            provider_metadata: {},
          },
        ],
        embeds: [],
        uploads: [],
        provider_labels: ["claude"],
        source_metadata: {},
      }],
    };

    const result = await service.importChats(parsed, parsed.chats, {
      import_id: "import-1",
      default_selection_count: 1,
      max_batch_count: 1,
      duplicate_fingerprints: [],
      estimated_credits: 1,
      can_import: true,
      reason: "paid_import_available",
    });

    expect(result.imported[0].messages_imported).toBe(1);
    expect(result.imported[0].messages?.map((message) => message.content)).toEqual([
      "persisted message",
    ]);
    expect(mocks.addChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_id: "uuid-1",
      messages_v: 1,
    }));
    expect(requests[2].body).toMatchObject({
      imported_chat_ids: ["uuid-1"],
      source_fingerprints: [],
      encrypted_record_counts: { chats: 1, messages: 1 },
      client_failures: [{ chat_id: "uuid-1", message_id: failedMessageId, reason: "message_create_failed" }],
    });
    expect(mocks.batchSaveMessages).toHaveBeenCalledWith([
      expect.objectContaining({ message_id: "uuid-1-uuid-2", content: "persisted message" }),
    ]);
  });

  it("does not report or cache chats with chat-level encrypted persistence failures", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify({
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        }));
      }
      if (path === "/v1/account-imports/import-1/persist-encrypted") {
        return new Response(JSON.stringify({
          status: "partial",
          imported_chat_ids: ["uuid-1"],
          encrypted_record_counts: { chats: 0, messages: 0 },
          failures: [{ chat_id: "uuid-1", reason: "chat_create_failed" }],
        }));
      }
      if (path === "/v1/account-imports/import-1/complete") {
        return new Response(JSON.stringify({
          status: "partial",
          imported_count: 0,
          credits_charged: 0,
          credits_released: 1,
          failures: body.client_failures,
        }));
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    }));

    const service = await import("../chatImportService");
    const parsed = {
      source: "claude" as const,
      fileType: "claude-json" as const,
      skippedDomains: [],
      chats: [{
        provider: "claude" as const,
        source_chat_id: "source-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Chat-level failure",
        created_at: null,
        updated_at: null,
        messages: [{
          role: "user" as const,
          content: "should not be cached",
          created_at: null,
          source_message_id: "message-1",
          provider_metadata: {},
        }],
        embeds: [],
        uploads: [],
        provider_labels: ["claude"],
        source_metadata: {},
      }],
    };

    const result = await service.importChats(parsed, parsed.chats, {
      import_id: "import-1",
      default_selection_count: 1,
      max_batch_count: 1,
      duplicate_fingerprints: [],
      estimated_credits: 1,
      can_import: true,
      reason: "paid_import_available",
    });

    expect(result.imported).toEqual([]);
    expect(requests[2].body).toMatchObject({
      imported_chat_ids: ["uuid-1"],
      source_fingerprints: [],
      encrypted_record_counts: { chats: 0, messages: 0 },
      client_failures: [{ chat_id: "uuid-1", reason: "chat_create_failed" }],
    });
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  it("parses OpenMates Export V1 archives and reports skipped non-chat domains", async () => {
    const service = await import("../chatImportService");
    const zip = new JSZip();
    zip.file("manifest.yml", [
      "format: openmates-account-export",
      "version: 1",
      "domains:",
      "  chats: {}",
      "  embeds: {}",
      "  uploads: {}",
      "  projects: {}",
    ].join("\n"));
    zip.file("chats/chat-1.yml", [
      "id: chat-1",
      "title: Exported OpenMates chat",
      "created_at: '2026-07-18T12:00:00Z'",
      "updated_at: '2026-07-18T12:05:00Z'",
      "messages:",
      "  - id: msg-1",
      "    role: user",
      "    content: hello from export",
    ].join("\n"));
    const bytes = await zip.generateAsync({ type: "uint8array" });
    const file = {
      name: "openmates-export.zip",
      arrayBuffer: async () => bytes.buffer.slice(
        bytes.byteOffset,
        bytes.byteOffset + bytes.byteLength,
      ),
    } as File;

    const parsed = await service.parseImportFile(file);

    expect(parsed.source).toBe("openmates");
    expect(parsed.skippedDomains).toEqual(["projects"]);
    expect(parsed.chats[0].title).toBe("Exported OpenMates chat");
    expect(parsed.chats[0].messages[0].content).toBe("hello from export");
  });
});
