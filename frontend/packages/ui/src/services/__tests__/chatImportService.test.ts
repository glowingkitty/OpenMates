/**
 * Account Import V1 browser service tests.
 *
 * These tests guard the Settings -> Account -> Import web path. They verify the
 * browser uses the V1 preview/scan/encrypted-persist/complete contract and does
 * not regress to the disabled plaintext settings import endpoint.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  addChat: vi.fn(),
  batchSaveMessages: vi.fn(),
  createAndPersistKey: vi.fn(),
  encryptWithChatKey: vi.fn(),
  parseImportFile: vi.fn(),
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

// The Rust `transfer` unit (shared Worker) owns parsing and batching; its parsing is
// proven by web_transfer_tests.rs in the crate. This suite covers the page-side
// import flow, so the adapter is replaced by a deterministic stand-in.
vi.mock("../rustCore/transfer/rustChatImport", () => ({
  rustParseImportFile: mocks.parseImportFile,
  rustEstimateImportCost: (chats: Array<{ messages: Array<{ content: string }> }>) => ({
    totalInputTokens: chats.reduce((sum, chat) => sum + chat.messages.length, 0),
    estimatedCredits: chats.length,
    chatCount: chats.length,
    messageCount: chats.reduce((sum, chat) => sum + chat.messages.length, 0),
  }),
  rustBuildMessageBatches: async (
    chats: Array<{ source_fingerprint: string; messages: unknown[] }>,
    maxMessages: number,
  ) => chats.flatMap((chat, chatIndex) => {
    const chunkCount = Math.max(1, Math.ceil(chat.messages.length / maxMessages));
    return Array.from({ length: chunkCount }, (_, chunkIndex) => ({
      chatIndex,
      chunkIndex,
      sourceFingerprint: chat.source_fingerprint,
      batchId: `scan-${chat.source_fingerprint.slice(0, 16)}-${chunkIndex}`,
      chat: { ...chat, messages: chat.messages.slice(chunkIndex * maxMessages, (chunkIndex + 1) * maxMessages) },
    }));
  }),
}));

function parsedChat(title: string, messages: Array<Record<string, unknown>>, source: "claude" | "gemini") {
  const identity = source === "claude"
    ? { category: "claude", sender_name: "Claude", model_name: "Claude" }
    : { category: "gemini", sender_name: "Gemini", model_name: "synthetic-model" };
  return {
    source,
    parserFormat: source === "claude" ? "claude" : "generic",
    fileType: source === "claude" ? "claude-json" : "generic-json",
    skippedDomains: [],
    chats: [{
      provider: source,
      source_chat_id: `${source}-chat-1`,
      source_fingerprint: `fingerprint-${source}-1`,
      title,
      created_at: "2026-07-18T12:00:00Z",
      updated_at: "2026-07-18T12:05:00Z",
      messages: messages.map((message) => ({
        provider_metadata: {},
        source_message_id: null,
        created_at: null,
        ...message,
        imported_assistant_identity: message.role === "assistant" ? identity : null,
      })),
      embeds: [],
      uploads: [],
      provider_labels: [source],
      source_metadata: {},
    }],
  };
}

function pathFromUrl(input: RequestInfo | URL): string {
  return new URL(String(input)).pathname;
}

function resumableControlResponse(
  path: string,
  body: Record<string, unknown>,
  requests: Array<{ path: string; body: Record<string, unknown> }>,
): Response | null {
  if (path.endsWith("/confirm")) return new Response(JSON.stringify({ status: "confirmed" }));
  if (path.endsWith("/status")) {
    return new Response(JSON.stringify({
      last_scan_sequence: requests.filter((request) => request.path.endsWith("/scan")).length - 1,
      last_compression_sequence: requests.filter((request) => request.path.endsWith("/compress")).length - 1,
    }));
  }
  if (path.endsWith("/compress")) {
    return new Response(JSON.stringify({
      batch_id: body.batch_id,
      sequence: body.sequence,
      status: "acknowledged",
      failures: [],
    }));
  }
  return null;
}

function acknowledgedScan(body: Record<string, unknown>, values: Record<string, unknown>): Record<string, unknown> {
  return { batch_id: body.batch_id, sequence: body.sequence, status: "acknowledged", ...values };
}

describe("chatImportService Account Import V1", () => {
  beforeEach(() => {
    vi.resetModules();
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

  // contract-test: supporting surface=gui.web assertions=account-import.persistence.client-encrypted,account-import.review.confirmed-results
  it("parses, previews, scans, encrypts, persists, and completes without plaintext persistence", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      const control = resumableControlResponse(path, body, requests);
      if (control) return control;
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
        const chats = body.chats as Array<{ messages: Array<Record<string, unknown>> }>;
        return new Response(JSON.stringify(acknowledgedScan(body, {
          chats: chats.map((chat) => ({
            ...chat,
            messages: chat.messages.map((message) => message.content === "Synthetic prompt injection payload"
              ? { ...message, content: "[Prompt injection removed]" }
              : message),
          })),
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        })));
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
    mocks.parseImportFile.mockResolvedValue(parsedChat("Sensitive web import", [
      { role: "user", content: "Synthetic prompt injection payload", created_at: "2026-07-18T12:01:00Z" },
      { role: "system", content: "Synthetic system import instruction", created_at: "2026-07-18T12:02:00Z" },
    ], "claude"));
    const file = { name: "claude-export.json" } as File;

    const parsed = await service.parseImportFile(file);
    const preview = await service.previewImport(parsed);
    const result = await service.importChats(parsed, parsed.chats, preview);

    expect(result.complete.status).toBe("complete");
    expect(requests.map((request) => request.path)).toEqual([
      "/v1/account-imports/preview",
      "/v1/account-imports/import-1/confirm",
      "/v1/account-imports/import-1/status",
      "/v1/account-imports/import-1/scan",
      "/v1/account-imports/import-1/status",
      "/v1/account-imports/import-1/compress",
      "/v1/account-imports/import-1/status",
      "/v1/account-imports/import-1/persist-encrypted",
      "/v1/account-imports/import-1/complete",
    ]);
    expect(requests.some((request) => request.path === "/v1/settings/import-chat")).toBe(false);

    const persistBody = requests.find((request) => request.path.endsWith("/persist-encrypted"))!.body as { chats: Array<Record<string, unknown>> };
    const persistedChat = persistBody.chats[0];
    expect(String(persistedChat.encrypted_title)).not.toContain("Sensitive web import");
    const persistedMessages = persistedChat.messages as Array<Record<string, unknown>>;
    const scanBody = requests.find((request) => request.path.endsWith("/scan"))!.body as {
      chats: Array<{ messages: Array<{ role: string; content: string }> }>;
    };
    expect(scanBody.chats[0].messages).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: "system", content: "Synthetic system import instruction" }),
      expect.objectContaining({ role: "user", content: "Synthetic prompt injection payload" }),
    ]));
    expect(persistedMessages[0].encrypted_content).toBe(
      `encrypted:${Buffer.from("[Prompt injection removed]").toString("base64")}`,
    );
    expect(JSON.stringify(persistBody)).not.toContain("Synthetic prompt injection payload");
    expect(JSON.stringify(persistBody)).not.toContain("Synthetic system import instruction");
    expect(persistedChat).not.toHaveProperty("title");
    expect(persistedMessages[0]).not.toHaveProperty("content");
    expect(mocks.addChat).toHaveBeenCalledWith(expect.objectContaining({
      title: "Sensitive web import",
      encrypted_title: `encrypted:${Buffer.from("Sensitive web import").toString("base64")}`,
    }));
    expect(mocks.batchSaveMessages).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=account-import.review.confirmed-results
  it("fails closed when safety scan blocks every selected chat", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      const control = resumableControlResponse(path, body, requests);
      if (control) return control;
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify(acknowledgedScan(body, {
          chats: [],
          credits_reserved: 0,
          messages_blocked: [{ source_chat_id: "source-chat-1", source_message_id: "message-1" }],
          failures: [],
        })));
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
      "/v1/account-imports/import-1/confirm",
      "/v1/account-imports/import-1/status",
      "/v1/account-imports/import-1/scan",
      "/v1/account-imports/import-1/status",
    ]);
    expect(mocks.createAndPersistKey).not.toHaveBeenCalled();
    expect(mocks.encryptWithChatKey).not.toHaveBeenCalled();
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=account-import.review.confirmed-results
  it("fails closed when safety scan returns failures with sanitized chats", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      const control = resumableControlResponse(path, body, requests);
      if (control) return control;
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify(acknowledgedScan(body, {
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [{ source_chat_id: "source-chat-1", reason: "scanner_timeout" }],
        })));
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
      "/v1/account-imports/import-1/confirm",
      "/v1/account-imports/import-1/status",
      "/v1/account-imports/import-1/scan",
      "/v1/account-imports/import-1/complete",
    ]);
    expect(requests.find((request) => request.path.endsWith("/complete"))!.body).toMatchObject({
      imported_chat_ids: [],
      source_fingerprints: [],
      client_failures: [{ source_chat_id: "source-chat-1", reason: "scanner_timeout" }],
    });
    expect(requests.some((request) => request.path.endsWith("/persist-encrypted"))).toBe(false);
    expect(requests.filter((request) => request.path.endsWith("/complete"))).toHaveLength(1);
    expect(mocks.createAndPersistKey).not.toHaveBeenCalled();
    expect(mocks.encryptWithChatKey).not.toHaveBeenCalled();
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=account-import.persistence.client-encrypted
  it("does not cache messages that failed encrypted persistence", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    let failedMessageId = "";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      const control = resumableControlResponse(path, body, requests);
      if (control) return control;
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify(acknowledgedScan(body, {
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        })));
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
    expect(requests.find((request) => request.path.endsWith("/complete"))!.body).toMatchObject({
      imported_chat_ids: ["uuid-1"],
      source_fingerprints: [],
      encrypted_record_counts: { chats: 1, messages: 1 },
      client_failures: [{ chat_id: "uuid-1", message_id: failedMessageId, reason: "message_create_failed" }],
    });
    expect(mocks.batchSaveMessages).toHaveBeenCalledWith([
      expect.objectContaining({ message_id: "uuid-1-uuid-2", content: "persisted message" }),
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=account-import.persistence.client-encrypted
  it("does not report or cache chats with chat-level encrypted persistence failures", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, body });
      const control = resumableControlResponse(path, body, requests);
      if (control) return control;
      if (path === "/v1/account-imports/import-1/scan") {
        return new Response(JSON.stringify(acknowledgedScan(body, {
          chats: body.chats,
          credits_reserved: 1,
          messages_blocked: [],
          failures: [],
        })));
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
    expect(requests.find((request) => request.path.endsWith("/complete"))!.body).toMatchObject({
      imported_chat_ids: ["uuid-1"],
      source_fingerprints: [],
      encrypted_record_counts: { chats: 0, messages: 0 },
      client_failures: [{ chat_id: "uuid-1", reason: "chat_create_failed" }],
    });
    expect(mocks.addChat).not.toHaveBeenCalled();
    expect(mocks.batchSaveMessages).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=account-import.persistence.client-encrypted
  it("resumes acknowledged scan and compression batches in the same tab without duplicate work", async () => {
    const requests: Array<{ path: string; method: string; body: Record<string, unknown> }> = [];
    let scanCursor = -1;
    let compressionCursor = -1;
    let statusCalls = 0;
    let compressionSequenceOneAttempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathFromUrl(input);
      const method = init?.method ?? "GET";
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ path, method, body });
      if (path.endsWith("/confirm")) return new Response(JSON.stringify({ status: "confirmed" }));
      if (path.endsWith("/status")) {
        statusCalls++;
        if (statusCalls === 2) {
          return new Response(JSON.stringify({ detail: "Synthetic status interruption", retryable: true }), { status: 503 });
        }
        return new Response(JSON.stringify({
          last_scan_sequence: scanCursor,
          last_compression_sequence: compressionCursor,
        }));
      }
      if (path.endsWith("/scan")) {
        scanCursor = Number(body.sequence);
        return new Response(JSON.stringify({
          batch_id: body.batch_id,
          sequence: body.sequence,
          status: "acknowledged",
          chats: body.chats,
          messages_blocked: [],
          failures: [],
        }));
      }
      if (path.endsWith("/compress")) {
        if (Number(body.sequence) === 1 && compressionSequenceOneAttempts++ === 0) {
          return new Response(JSON.stringify({ detail: "Synthetic compression interruption", retryable: true }), { status: 503 });
        }
        compressionCursor = Number(body.sequence);
        return new Response(JSON.stringify({
          batch_id: body.batch_id,
          sequence: body.sequence,
          status: "acknowledged",
          summary: `sanitized summary ${Number(body.sequence) + 1}`,
          failures: [],
        }));
      }
      if (path.endsWith("/persist-encrypted")) {
        const chats = body.chats as Array<{ chat_id: string }>;
        return new Response(JSON.stringify({ status: "complete", imported_chat_ids: chats.map((chat) => chat.chat_id), encrypted_record_counts: { chats: 1, messages: 5 }, failures: [] }));
      }
      if (path.endsWith("/complete")) return new Response(JSON.stringify({ status: "complete", imported_count: 1, credits_charged: 1, credits_released: 1, failures: [] }));
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    }));

    const service = await import("../chatImportService");
    mocks.parseImportFile.mockResolvedValue(parsedChat("Long synthetic transcript", [
      { role: "user", content: "Question one" },
      { role: "assistant", content: "Answer one" },
      { role: "user", content: "Question two" },
      { role: "assistant", content: "Answer two" },
    ], "gemini"));
    const parsed = await service.parseImportFile({ name: "generic-transcript.json" } as File, "gemini");

    const preview = {
      import_id: "import-resume",
      default_selection_count: 1,
      max_batch_count: 1,
      duplicate_fingerprints: [],
      estimated_credits: 2,
      can_import: true,
      reason: "paid_import_available",
    };

    await expect(service.importChats(parsed, parsed.chats, preview, undefined, { maxMessagesPerBatch: 2 }))
      .rejects.toThrow("Synthetic status interruption");
    await expect(service.importChats(parsed, parsed.chats, preview, undefined, { maxMessagesPerBatch: 2 }))
      .rejects.toThrow("Synthetic compression interruption");
    const result = await service.importChats(parsed, parsed.chats, preview, undefined, { maxMessagesPerBatch: 2 });

    expect(result.complete.status).toBe("complete");

    expect(requests.filter((request) => request.path.endsWith("/confirm"))).toHaveLength(1);
    expect(requests.filter((request) => request.path.endsWith("/scan")).map((request) => request.body.sequence)).toEqual([0, 1]);
    const compressionBodies = requests.filter((request) => request.path.endsWith("/compress")).map((request) => request.body);
    expect(compressionBodies[0]).not.toHaveProperty("prior_summary");
    expect(compressionBodies[1].prior_summary).toBe("sanitized summary 1");
    expect(compressionBodies[2].prior_summary).toBe("sanitized summary 1");
    expect(compressionBodies.map((body) => body.sequence)).toEqual([0, 1, 1]);
    expect(requests.filter((request) => request.path.endsWith("/persist-encrypted"))).toHaveLength(1);
    expect(requests.filter((request) => request.path.endsWith("/complete"))).toHaveLength(1);
    const persistBody = requests.find((request) => request.path.endsWith("/persist-encrypted"))!.body;
    expect(JSON.stringify(persistBody)).not.toContain("sanitized summary");
    const messages = (persistBody.chats as Array<{ messages: Array<Record<string, unknown>> }>)[0].messages;
    expect(messages[1]).toMatchObject({
      encrypted_sender_name: expect.stringContaining("encrypted:"),
      encrypted_category: expect.stringContaining("encrypted:"),
      encrypted_model_name: expect.stringContaining("encrypted:"),
    });
    expect(messages.at(-1)).toMatchObject({
      role: "system",
      encrypted_content: `encrypted:${Buffer.from("sanitized summary 2").toString("base64")}`,
      encrypted_category: `encrypted:${Buffer.from("compression_summary").toString("base64")}`,
    });
    expect(messages.at(-1)).not.toHaveProperty("content");
    expect(messages.at(-1)).not.toHaveProperty("category");
    expect(messages[1]).not.toHaveProperty("avatar_key");
  });
});
