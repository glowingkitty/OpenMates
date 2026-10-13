import { beforeEach, describe, expect, it, vi } from "vitest";
import { websocketStatus } from "../../stores/websocketStatusStore";

const mocks = vi.hoisted(() => {
  const rows = new Map<string, Record<string, unknown>>();
  const handlers = new Map<string, Set<(value: Record<string, unknown>) => void>>();
  const sent: Array<{ type: string; payload: Record<string, unknown> }> = [];
  let rejectSends = 0;
  let dropReceipts = 0;
  let rejectCode: string | null = null;
  const chat = {
    chat_id: "chat-uuid-1234", team_id: null, encrypted_title: null,
    encrypted_chat_key: "wrapped-key", messages_v: 0, title_v: 0,
    created_at: 1_700_000_000, updated_at: 1_700_000_000,
    last_edited_overall_timestamp: 1_700_000_000, unread_count: 0,
  };
  const emit = (type: string, payload: Record<string, unknown>) => {
    for (const handler of handlers.get(type) ?? []) handler(payload);
  };
  const transaction = () => {
    const tx: Record<string, unknown> = {
      objectStore: () => ({
        get: (id: string) => {
          const request: Record<string, unknown> = {};
          queueMicrotask(() => {
            request.result = rows.get(id);
            (request.onsuccess as () => void)?.();
            queueMicrotask(() => (tx.oncomplete as () => void)?.());
          });
          return request;
        },
        put: (row: Record<string, unknown>) => {
          rows.set(String(row.message_id), row);
          queueMicrotask(() => (tx.oncomplete as () => void)?.());
        },
        delete: (id: string) => {
          rows.delete(id);
          queueMicrotask(() => (tx.oncomplete as () => void)?.());
        },
      }),
      abort: () => (tx.onabort as () => void)?.(),
    };
    return tx;
  };
  const db = {
    getChat: vi.fn(async () => chat),
    getMessage: vi.fn(async (id: string) => {
      const raw = rows.get(id);
      return raw ? { ...raw, content: String(raw.encrypted_content).slice(7) } : null;
    }),
    getMessageWindowForChat: vi.fn(async () => ({ messages: [] })),
    getPendingMessageRetryPage: vi.fn(async () => ({ rows: [...rows.values()].filter((row) => row.status === "sending"), nextCursor: null })),
    getTransaction: vi.fn(async () => transaction()),
    getEncryptedFields: vi.fn(async (message: { content?: string }) => ({ encrypted_content: `cipher:${message.content}` })),
    updateMessageStatus: vi.fn(async (id: string, status: string) => {
      const row = rows.get(id);
      if (row) row.status = status;
    }),
    addChat: vi.fn(async () => {}),
  };
  const socket = {
    on: vi.fn((type: string, handler: (value: Record<string, unknown>) => void) => {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type)!.add(handler);
    }),
    off: vi.fn((type: string, handler: (value: Record<string, unknown>) => void) => handlers.get(type)?.delete(handler)),
    sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>) => {
      if (type === "call_message_completed" && rejectSends-- > 0) throw new Error("socket disconnected");
      sent.push({ type, payload });
      queueMicrotask(() => {
        if (type === "call_message_completed") {
          if (dropReceipts-- > 0) return;
          if (rejectCode) emit("call_message_rejected", { request_id: payload.request_id, code: rejectCode });
          else emit("call_message_confirmed", {
            request_id: payload.request_id, revision: payload.revision, outcome: "created",
          });
        }
        if (type === "encrypted_chat_metadata") emit("encrypted_metadata_stored", { chat_id: payload.chat_id });
      });
    }),
  };
  return { rows, handlers, sent, chat, db, socket, emit, dispatchEvent: vi.fn(),
    rejectNextSends: (count: number) => { rejectSends = count; },
    dropNextReceipts: (count: number) => { dropReceipts = count; },
    rejectCallWith: (code: string | null) => { rejectCode = code; } };
});

vi.mock("../db", () => ({ chatDB: mocks.db }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {
  getKey: vi.fn(async () => new Uint8Array(32)),
  createAndPersistKeyLocked: vi.fn(async () => ({ chatKey: new Uint8Array(32), encryptedChatKey: "wrapped-key" })),
} }));
vi.mock("../chatKeyWriteGuard", () => ({ ensureChatKeySafeForWrite: vi.fn(async () => true) }));
vi.mock("../websocketService", () => ({ webSocketService: mocks.socket }));
vi.mock("../chatSyncService", () => ({ chatSyncService: { dispatchEvent: mocks.dispatchEvent } }));
vi.mock("../userDB", () => ({ userDB: { getUserProfile: vi.fn(async () => ({ user_id: "owner-uuid" })) } }));
vi.mock("../workspaceQueryCache", () => ({ getWorkspaceCacheIdentity: () => "owner-scope" }));
vi.mock("../../i18n/translations", () => ({ text: { subscribe: (run: (value: (key: string) => string) => void) => {
  run((key: string) => key === "voicecall.interrupted" ? "Interrupted" : key);
  return () => {};
} } }));

import { applyCallMessageChanged, loadCallContext, markTypedCallMessageFailed,
  persistTypedCallMessage, retryPendingCallMessages, upsertCallTranscript } from "../voiceCallMessages";

beforeEach(() => {
  mocks.rows.clear();
  mocks.sent.length = 0;
  mocks.dispatchEvent.mockClear();
  mocks.rejectNextSends(0);
  mocks.dropNextReceipts(0);
  mocks.rejectCallWith(null);
  websocketStatus.setStatus("connected");
  mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [] });
});

describe("voice call transcript persistence", () => {
  const base = {
    callId: "call-uuid-1234", chatId: "chat-uuid-1234", messageId: "message-uuid-1234",
    role: "assistant" as const, createdAt: 1_700_000_001,
  };

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("updates one encrypted local row progressively and sends ciphertext only on completion", async () => {
    await upsertCallTranscript({ ...base, text: "Hello", final: false });
    await upsertCallTranscript({ ...base, text: "Hello there", final: false });
    expect(mocks.rows.size).toBe(1);
    expect(mocks.rows.get(base.messageId)).toMatchObject({ encrypted_content: "cipher:Hello there", status: "streaming" });
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
    expect(mocks.sent).toHaveLength(0);

    await upsertCallTranscript({ ...base, text: "Hello there", final: true });
    expect(mocks.sent).toHaveLength(1);
    expect(mocks.sent[0]).toMatchObject({ type: "call_message_completed", payload: {
      message_id: base.messageId, role: "assistant", encrypted_content: "cipher:Hello there", revision: 1,
    } });
    expect(mocks.sent[0].payload).not.toHaveProperty("content");
    expect(mocks.rows.get(base.messageId)?.status).toBe("synced");
    expect(mocks.dispatchEvent).toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
  it("keeps a late correction under the same ID with a higher revision", async () => {
    await upsertCallTranscript({ ...base, text: "First", final: true });
    await upsertCallTranscript({ ...base, text: "First corrected", final: true });
    await upsertCallTranscript({ ...base, text: "First corrected", final: true });
    expect(mocks.rows.size).toBe(1);
    expect(mocks.sent.map((entry) => entry.payload.revision)).toEqual([1, 2]);
    expect(mocks.rows.get(base.messageId)?.encrypted_content).toBe("cipher:First corrected");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("retains ciphertext after a failed final send and replays only the call event on reconnect", async () => {
    mocks.rejectNextSends(3);
    await expect(upsertCallTranscript({ ...base, text: "Retained secret", final: true })).rejects.toThrow();
    const raw = mocks.rows.get(base.messageId);
    expect(raw).toMatchObject({ status: "sending", encrypted_content: "cipher:Retained secret",
      call_persistence_v1: { call_id: base.callId, entries: [{ revision: 1, ciphertext: "cipher:Retained secret" }] } });
    expect(raw).not.toHaveProperty("content");
    mocks.rejectNextSends(0);
    await retryPendingCallMessages();
    expect(mocks.rows.get(base.messageId)?.status).toBe("synced");
    expect((mocks.rows.get(base.messageId)?.call_persistence_v1 as { entries: unknown[] }).entries).toEqual([]);
    expect(mocks.sent.every((entry) => entry.type === "call_message_completed")).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("replays the same encrypted revision promptly when its receipt is lost on socket close", async () => {
    mocks.dropNextReceipts(1);
    const pending = upsertCallTranscript({ ...base, text: "Accepted but unconfirmed", final: true });
    await vi.waitFor(() => expect(mocks.sent).toHaveLength(1));
    expect(mocks.rows.get(base.messageId)?.status).toBe("sending");
    websocketStatus.setStatus("reconnecting");
    websocketStatus.setStatus("connected");
    const reconnectRetry = retryPendingCallMessages();
    await vi.waitFor(() => expect(mocks.rows.get(base.messageId)?.status).toBe("synced"), { timeout: 1_000 });
    await pending;
    await reconnectRetry;
    expect(mocks.sent).toHaveLength(2);
    expect(mocks.sent[1].payload).toMatchObject({
      message_id: base.messageId, revision: 1, encrypted_content: "cipher:Accepted but unconfirmed",
    });
    expect(mocks.sent[1].payload.request_id).toBe(mocks.sent[0].payload.request_id);
    expect((mocks.rows.get(base.messageId)?.call_persistence_v1 as { entries: unknown[] }).entries).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("leaves ciphertext visibly failed when call authorization grace expires", async () => {
    mocks.rejectCallWith("call_message_not_authorized");
    await expect(upsertCallTranscript({ ...base, text: "Late final text", final: true })).rejects.toThrow();
    expect(mocks.rows.get(base.messageId)).toMatchObject({ status: "failed",
      encrypted_content: "cipher:Late final text",
      call_persistence_v1: { entries: [{ revision: 1, ciphertext: "cipher:Late final text" }] } });
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
    expect(mocks.sent).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("does not let a passive-device snapshot erase a pending corrected ciphertext", async () => {
    mocks.rejectNextSends(3);
    await expect(upsertCallTranscript({ ...base, text: "Corrected", final: true })).rejects.toThrow();
    await applyCallMessageChanged({ chat_id: base.chatId, message_id: base.messageId,
      role: "assistant", encrypted_content: "cipher:Old", created_at: base.createdAt,
      revision: 1 });
    expect(mocks.rows.get(base.messageId)).toMatchObject({ status: "sending",
      encrypted_content: "cipher:Corrected", call_persistence_v1: {
        entries: [{ revision: 1, ciphertext: "cipher:Corrected" }],
      } });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
  it("keeps a missed-ACK ciphertext revision before a late correction", async () => {
    mocks.rejectNextSends(3);
    await expect(upsertCallTranscript({ ...base, text: "First", final: true })).rejects.toThrow();
    mocks.rejectNextSends(0);
    await upsertCallTranscript({ ...base, text: "First corrected", final: true });
    expect(mocks.sent.map((entry) => entry.payload.revision)).toEqual([1, 2]);
    expect(mocks.sent.map((entry) => entry.payload.encrypted_content)).toEqual(["cipher:First", "cipher:First corrected"]);
    expect(mocks.rows.get(base.messageId)?.status).toBe("synced");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("rolls back unaccepted typed text so a restored composer draft has no duplicate bubble", async () => {
    await persistTypedCallMessage(base.callId, base.chatId, base.messageId, "Typed secret", 1_700_000_099);
    expect(mocks.rows.get(base.messageId)).toMatchObject({ created_at: 1_700_000_099,
      encrypted_content: "cipher:Typed secret", call_persistence_v1: { call_id: base.callId, typed_pending: true, entries: [] } });
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
    await markTypedCallMessageFailed(base.callId, base.chatId, base.messageId);
    expect(mocks.rows.has(base.messageId)).toBe(false);
    expect(mocks.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "messageDeleted" }));
    expect(mocks.sent).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("cleans an orphan typed-only row after reload without starting ordinary inference", async () => {
    await persistTypedCallMessage(base.callId, base.chatId, base.messageId, "Unaccepted", 1_700_000_099);
    const raw = mocks.rows.get(base.messageId)!;
    (raw.call_persistence_v1 as { typed_pending_at: number }).typed_pending_at = Date.now() - 31_000;
    await retryPendingCallMessages();
    expect(mocks.rows.has(base.messageId)).toBe(false);
    expect(mocks.sent).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.transcripts
  it("loads bounded context and places a linked assistant after its user", async () => {
    mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [
      { message_id: "assistant-a", role: "assistant", user_message_id: "user-z", created_at: 1,
        content: "Reply" },
      { message_id: "user-z", role: "user", created_at: 1, content: "Question" },
    ] });
    expect((await loadCallContext(base.chatId)).history).toEqual([
      { role: "user", text: "Question" }, { role: "assistant", text: "Reply" },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.privacy
  it("hydrates newer ciphertext from another device without plaintext storage", async () => {
    await applyCallMessageChanged({ chat_id: base.chatId, message_id: base.messageId,
      role: "assistant", encrypted_content: "cipher:Latest", created_at: 1_700_000_001,
      revision: 2 });
    expect(mocks.rows.get(base.messageId)).toMatchObject({ encrypted_content: "cipher:Latest", queue_revision: 2 });
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
  });
});
