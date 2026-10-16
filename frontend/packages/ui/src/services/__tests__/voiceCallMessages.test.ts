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
    getChatCompressionCheckpoints: vi.fn(async () => [] as Array<Record<string, unknown>>),
    getAppSettingsMemoriesMetadataKeys: vi.fn(async () => [] as string[]),
    getMessage: vi.fn(async (id: string) => {
      const raw = rows.get(id);
      if (!raw) return null;
      const decrypted = { ...raw, content: String(raw.encrypted_content).slice(7) };
      delete (decrypted as Record<string, unknown>).encrypted_content;
      return decrypted;
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
        if (type === "chat_system_message_added") emit("system_message_confirmed", {
          chat_id: payload.chat_id, message_id: (payload.message as Record<string, unknown>).message_id,
        });
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
vi.mock("../embedStore", () => ({ embedStore: { get: vi.fn(async (ref: string) => ({
  embed_id: ref.slice(6), type: "app_skill_use", content: "app_id: web\nskill_id: search",
})) } }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {
  getKey: vi.fn(async () => new Uint8Array(32)),
  createAndPersistKeyLocked: vi.fn(async () => ({ chatKey: new Uint8Array(32), encryptedChatKey: "wrapped-key" })),
} }));
vi.mock("../encryption/MessageEncryptor", () => ({ decryptWithChatKey: vi.fn(async (value: string) => {
  if (value === "invalid") throw new Error("Invalid ciphertext");
  return value.slice(7);
}) }));
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
  persistTypedCallMessage, retryPendingCallMessages, upsertCallTranscript, upsertCallArtifact, recordCallLifecycle } from "../voiceCallMessages";

const artifactReferenceText = (id: string) => '```json\n' + JSON.stringify({ embed_id: id,
  type: "app_skill_use", app_id: "web", skill_id: "search" }) + '\n```';

beforeEach(() => {
  mocks.rows.clear();
  mocks.sent.length = 0;
  mocks.dispatchEvent.mockClear();
  mocks.rejectNextSends(0);
  mocks.dropNextReceipts(0);
  mocks.rejectCallWith(null);
  websocketStatus.setStatus("connected");
  mocks.db.getMessageWindowForChat.mockReset().mockResolvedValue({ messages: [] });
  mocks.db.getChatCompressionCheckpoints.mockResolvedValue([]);
  mocks.db.getAppSettingsMemoriesMetadataKeys.mockResolvedValue([]);
  delete (mocks.chat as Record<string, unknown>).encrypted_active_focus_id;
  delete (mocks.chat as Record<string, unknown>).encrypted_focus_phase_state;
});

describe("voice call transcript persistence", () => {
  const base = {
    callId: "call-uuid-1234", chatId: "chat-uuid-1234", messageId: "message-uuid-1234",
    role: "assistant" as const, createdAt: 1_700_000_001,
  };

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
  it("encrypts canonical parent metadata once and retains it when only corrected speech arrives", async () => {
    const reference = { type: "app_skill_use", embed_id: "search-parent", app_id: "web", skill_id: "search",
      query: "Fictional recipe", provider: "Fixture", status: "finished" };
    await upsertCallArtifact({ ...base, embedRefs: [reference.embed_id], embedReferences: [reference] });
    await upsertCallTranscript({ ...base, text: "The search is ready", final: true });
    await upsertCallTranscript({ ...base, text: "Corrected search result", final: true });
    const row = mocks.rows.get(base.messageId)!;
    expect(row).not.toHaveProperty("content");
    const content = String(row.encrypted_content).slice(7);
    expect(content).toBe('Corrected search result\n\n```json\n' + JSON.stringify(reference) + '\n```');
    expect(content.match(/search-parent/g)).toHaveLength(1);
    expect(row.queue_revision).toBe(3);
  });

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

  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.chat.typed-input
  it("emits the persisted call origin for spoken rows and typed input awaiting acceptance", async () => {
    const emitted = (messageId: string) => mocks.dispatchEvent.mock.calls
      .map(([event]) => (event as CustomEvent<{ newMessage?: Record<string, unknown> }>).detail.newMessage)
      .findLast((message) => message?.message_id === messageId);
    await upsertCallTranscript({ ...base, messageId: "spoken-user", role: "user", text: "Spoken words", final: false });
    expect(emitted("spoken-user")).toMatchObject({ status: "streaming",
      call_persistence_v1: { call_id: base.callId, typed_pending: false } });
    await persistTypedCallMessage(base.callId, base.chatId, "typed-user", "Typed words", base.createdAt);
    expect(emitted("typed-user")).toMatchObject({ status: "sending",
      call_persistence_v1: { call_id: base.callId, typed_pending: true } });
    expect(mocks.rows.get("typed-user")).not.toHaveProperty("content");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
  it("persists an artifact-only response and increments final revision after provisional speech", async () => {
    await upsertCallArtifact({ ...base, userMessageId: "user-turn", embedRefs: ["artifact-one"] });
    expect(mocks.rows.get(base.messageId)).toMatchObject({ encrypted_content: `cipher:${artifactReferenceText("artifact-one")}`,
      status: "synced", call_last_final_revision: 1 });
    await upsertCallTranscript({ ...base, userMessageId: "user-turn", text: "Here is", embedRefs: ["artifact-one"], final: false });
    expect(mocks.rows.get(base.messageId)).toMatchObject({ status: "streaming", call_last_final_revision: 1 });
    await upsertCallTranscript({ ...base, userMessageId: "user-turn", text: "Here is your result", embedRefs: ["artifact-one"], final: true });
    expect(mocks.sent.map((item) => item.payload.revision)).toEqual([1, 2]);
    expect(mocks.rows.get(base.messageId)).toMatchObject({ status: "synced", call_last_final_revision: 2,
      encrypted_content: `cipher:Here is your result\n\n${artifactReferenceText("artifact-one")}` });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
  it("returns the confirmed raw ciphertext proof for an identical artifact receipt after hangup or replay", async () => {
    const event = { ...base, userMessageId: "user-turn", embedRefs: ["artifact-one"] };
    const original = await upsertCallArtifact(event);
    expect(await mocks.db.getMessage(base.messageId)).not.toHaveProperty("encrypted_content");
    const replay = await upsertCallArtifact(event);
    expect(replay).toEqual(original);
    expect(replay).toEqual({ revision: 1, ciphertext: `cipher:${artifactReferenceText("artifact-one")}` });
    expect(mocks.sent.filter((entry) => entry.type === "call_message_completed")).toHaveLength(1);
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.privacy
  it("never returns a replay proof for another call, chat or role", async () => {
    const event = { ...base, embedRefs: ["artifact-one"] };
    await upsertCallArtifact(event);
    const confirmed = { ...mocks.rows.get(base.messageId)! };
    for (const mismatch of [{ chat_id: "other-chat" }, { role: "user" },
      { call_persistence_v1: { call_id: "other-call", entries: [] } }]) {
      mocks.rows.set(base.messageId, { ...confirmed, ...mismatch });
      await expect(upsertCallArtifact(event)).rejects.toThrow("Call message identity conflict");
    }
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
  it("waits for server confirmation before returning an identical pending artifact proof", async () => {
    const event = { ...base, embedRefs: ["artifact-one"] };
    mocks.rejectNextSends(3);
    await expect(upsertCallArtifact(event)).rejects.toThrow("socket disconnected");
    expect(mocks.rows.get(base.messageId)?.status).toBe("sending");
    mocks.rejectNextSends(3);
    await expect(upsertCallArtifact(event)).rejects.toThrow("socket disconnected");
    expect(mocks.rows.get(base.messageId)).toMatchObject({ status: "sending", queue_revision: 1 });
    const proof = await upsertCallArtifact(event);
    expect(proof).toEqual({ revision: 1, ciphertext: `cipher:${artifactReferenceText("artifact-one")}` });
    expect(mocks.rows.get(base.messageId)?.status).toBe("synced");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts
  it("keeps a pending artifact ciphertext revision before the spoken final and preserves aggregated references", async () => {
    mocks.rejectNextSends(3);
    await expect(upsertCallArtifact({ ...base, embedRefs: ["artifact-one"] })).rejects.toThrow();
    await upsertCallTranscript({ ...base, text: "Spoken interim", final: false });
    mocks.rejectNextSends(0);
    await upsertCallTranscript({ ...base, text: "Spoken final", final: true });
    expect(mocks.sent.map((entry) => entry.payload.revision)).toEqual([1, 2]);
    const proof = await upsertCallArtifact({ ...base, embedRefs: ["artifact-two"] });
    expect(proof).toEqual({ revision: 3, ciphertext: `cipher:Spoken final\n\n${artifactReferenceText("artifact-one")}\n\n${artifactReferenceText("artifact-two")}` });
    await upsertCallTranscript({ ...base, text: "Corrected final", final: true });
    expect(mocks.rows.get(base.messageId)?.encrypted_content).toBe(`cipher:Corrected final\n\n${artifactReferenceText("artifact-one")}\n\n${artifactReferenceText("artifact-two")}`);
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
      { role: "user", text: "Question", message_id: "user-z", created_at: 1 }, { role: "assistant", text: "Reply", message_id: "assistant-a", created_at: 1 },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context
  it("pages a 25-turn uncheckpointed conversation instead of dropping its oldest fact", async () => {
    const turns = Array.from({ length: 25 }, (_, index) => ({ message_id: `turn-${String(index).padStart(2, "0")}`,
      created_at: index + 1, role: "user", content: index === 0 ? "Oldest uncovered fact" : `Turn ${index}` }));
    mocks.db.getMessageWindowForChat.mockResolvedValueOnce({ messages: turns.slice(1), hasMoreBefore: true,
      startCursor: 2, startCursorMessageId: "turn-01" }).mockResolvedValueOnce({ messages: turns.slice(0, 1), hasMoreBefore: false });
    const context = await loadCallContext(base.chatId);
    expect(context.history).toHaveLength(25);
    expect(context.history[0].text).toBe("Oldest uncovered fact");
    expect(mocks.db.getMessageWindowForChat).toHaveBeenNthCalledWith(2, base.chatId, {
      direction: "before", limit: 24, beforeTimestamp: 2, beforeMessageId: "turn-01",
    });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.chat.transcripts
  it("pages all uncovered checkpoint tail and stops before its archive while retaining a final correction", async () => {
    mocks.db.getChatCompressionCheckpoints.mockResolvedValue([{ id: "checkpoint", chat_id: base.chatId,
      encrypted_summary: "cipher:Complete checkpoint", compressed_up_to_timestamp: 10,
      compressed_up_to_message_id: "covered-z", compressed_message_count: 3, created_at: 11 }]);
    const tail = Array.from({ length: 25 }, (_, index) => ({ message_id: `tail-${index}`,
      created_at: 11 + index, role: "user", content: index === 0 ? "Earliest uncovered detail" : `Tail ${index}` }));
    mocks.db.getMessageWindowForChat.mockResolvedValueOnce({ messages: tail.slice(1), hasMoreBefore: true,
      startCursor: 12, startCursorMessageId: "tail-1" }).mockResolvedValueOnce({ messages: [
        { message_id: "archived", created_at: 9, role: "user", content: "Already summarized" },
        { message_id: "corrected-a", created_at: 10, role: "assistant", content: "Final corrected fact",
          status: "synced", queue_revision: 2, call_persistence_v1: { call_id: "old-call", entries: [] } },
        tail[0],
      ], hasMoreBefore: true, startCursor: 9, startCursorMessageId: "archived" });
    const context = await loadCallContext(base.chatId);
    expect(context.summary).toBe("Complete checkpoint");
    expect(context.history).toHaveLength(26);
    expect(context.history.slice(0, 2).map((turn) => turn.text)).toEqual(["Final corrected fact", "Earliest uncovered detail"]);
    expect(mocks.db.getMessageWindowForChat).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context
  it("visibly rejects more than 30 uncovered turns instead of accepting a truncated tail", async () => {
    const turns = Array.from({ length: 31 }, (_, index) => ({ message_id: `turn-${index}`,
      created_at: index + 1, role: "user", content: `Important turn ${index}` }));
    mocks.db.getMessageWindowForChat.mockResolvedValueOnce({ messages: turns.slice(7), hasMoreBefore: true,
      startCursor: 8, startCursorMessageId: "turn-7" }).mockResolvedValueOnce({ messages: turns.slice(0, 7), hasMoreBefore: false });
    await expect(loadCallContext(base.chatId)).rejects.toMatchObject({ code: "context_too_large" });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context
  it("refuses an incomplete window with a cursor that cannot advance", async () => {
    mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [{ message_id: "turn-1", created_at: 1,
      role: "user", content: "Known detail" }], hasMoreBefore: true, startCursor: 1, startCursorMessageId: "turn-1" });
    await expect(loadCallContext(base.chatId)).rejects.toMatchObject({ code: "context_unavailable" });
    expect(mocks.db.getMessageWindowForChat).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it("keeps the complete latest valid encrypted checkpoint and only uncovered turns", async () => {
    const checkpoint = { id: "checkpoint-1", chat_id: base.chatId, encrypted_summary: "cipher:" + "complete context ".repeat(400),
      compressed_up_to_timestamp: 10, compressed_up_to_message_id: "message-b", compressed_message_count: 2,
      covered_message_ids: ["covered-late"], created_at: 11 };
    mocks.db.getChatCompressionCheckpoints.mockResolvedValue([
      checkpoint, { ...checkpoint, id: "broken-newer", encrypted_summary: "invalid", created_at: 12 },
      { ...checkpoint, id: "other-chat", chat_id: "unrelated", created_at: 13 },
    ]);
    mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [
      { message_id: "message-a", created_at: 10, role: "user", content: "covered" },
      { message_id: "message-c", created_at: 10, role: "user", content: "uncovered" },
      { message_id: "covered-late", created_at: 12, role: "assistant", content: "covered late" },
      { message_id: "message-z", created_at: 12, role: "assistant", content: "recent reply" },
    ] });
    const context = await loadCallContext(base.chatId);
    expect(context.summary).toBe(checkpoint.encrypted_summary.slice(7).trim());
    expect(context.history).toEqual([{ role: "user", text: "uncovered", message_id: "message-c", created_at: 10 }, { role: "assistant", text: "recent reply", message_id: "message-z", created_at: 12 }]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.chat.transcripts
  it("retains a final correction after checkpoint ACK while excluding provisional covered speech", async () => {
    mocks.db.getChatCompressionCheckpoints.mockResolvedValue([{ id: "checkpoint", chat_id: base.chatId,
      encrypted_summary: "cipher:Prior compressed conversation", compressed_up_to_timestamp: 10,
      compressed_up_to_message_id: "message-z", compressed_message_count: 2, created_at: 11 }]);
    mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [
      { message_id: "message-a", created_at: 10, role: "user", content: "Final corrected detail", status: "synced",
        queue_revision: 2, call_persistence_v1: { call_id: "finished-call", entries: [] } },
      { message_id: "message-b", created_at: 10, role: "assistant", content: "Provisional", status: "streaming",
        queue_revision: 3, call_persistence_v1: { call_id: "active-call", entries: [] } },
    ] });
    expect((await loadCallContext(base.chatId)).history).toEqual([
      { role: "user", text: "Final corrected detail", message_id: "message-a", created_at: 10 },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it("rejects oversized checkpoint meaning instead of clipping it", async () => {
    mocks.db.getChatCompressionCheckpoints.mockResolvedValue([{ id: "large", chat_id: base.chatId,
      encrypted_summary: "cipher:" + "x".repeat(48_001), compressed_up_to_timestamp: 10,
      compressed_up_to_message_id: "message-b", compressed_message_count: 2, created_at: 11 }]);
    await expect(loadCallContext(base.chatId)).rejects.toMatchObject({ code: "context_too_large" });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it("loads canonical encrypted active focus and advertises memory keys without contents", async () => {
    Object.assign(mocks.chat, { encrypted_active_focus_id: "cipher:jobs-career_insights",
      encrypted_focus_phase_state: 'cipher:{"jobs-career_insights":{"version":2}}' });
    mocks.db.getAppSettingsMemoriesMetadataKeys.mockResolvedValue(["health-medical_history"]);
    expect(await loadCallContext(base.chatId)).toEqual({ history: [],
      activeFocus: { app_id: "jobs", focus_id: "jobs-career_insights", state: { version: 2 } },
      memoryMetadata: ["health-medical_history"] });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
  it("keeps artifact references on the same encrypted call response across text corrections", async () => {
    await upsertCallTranscript({ ...base, userMessageId: "user-turn", text: "Result", embedRefs: ["artifact-1"], final: true });
    await upsertCallTranscript({ ...base, userMessageId: "user-turn", text: "Corrected", embedRefs: ["artifact-1", "artifact-1"], final: true });
    expect(mocks.rows.size).toBe(1);
    expect(mocks.rows.get(base.messageId)).toMatchObject({ encrypted_content: `cipher:Corrected\n\n${artifactReferenceText("artifact-1")}`,
      user_message_id: "user-turn", queue_revision: 2 });
    expect(mocks.sent.map((entry) => entry.payload.message_id)).toEqual([base.messageId, base.messageId]);
    expect(mocks.rows.get(base.messageId)).not.toHaveProperty("content");
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


describe("encrypted call lifecycle history", () => {
  const event = { type: "started" as const, callId: "call-lifecycle-1234", chatId: "chat-uuid-1234",
    occurredAt: 1_700_000_000, activeElapsedSeconds: 0 };
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.privacy
  it("persists ciphertext only, deduplicates callbacks and reload replay without AI inference", async () => {
    await Promise.all([recordCallLifecycle(event), recordCallLifecycle(event)]);
    await recordCallLifecycle({ ...event, occurredAt: event.occurredAt + 20 });
    const row = mocks.rows.get(`00000000-voice-call-${event.callId}-started`)!;
    expect(row.role).toBe("system");
    expect(row.content).toBeUndefined();
    expect(row.status).toBe("synced");
    expect(JSON.parse(String(row.encrypted_content).slice(7))).toMatchObject({
      type: "voice_call", action: "started", created_at: event.occurredAt });
    expect(mocks.sent.map((entry) => entry.type)).toEqual(["chat_system_message_added"]);
    expect(mocks.sent[0].payload.message).not.toHaveProperty("content");
    await retryPendingCallMessages();
    expect(mocks.sent).toHaveLength(1);
    // A normal server history reload restores ciphertext, without local outbox fields.
    delete row.call_persistence_v1;
    await recordCallLifecycle(event);
    expect(mocks.sent).toHaveLength(1);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.chat.fixed-binding
  it("keeps the original chat and event timestamp when delayed teardown arrives", async () => {
    await recordCallLifecycle({ ...event, type: "ended", occurredAt: event.occurredAt + 95, activeElapsedSeconds: 37 });
    const message = mocks.sent[0].payload.message as Record<string, unknown>;
    expect(mocks.sent[0].payload.chat_id).toBe(event.chatId);
    expect(message.created_at).toBe(event.occurredAt + 95);
    expect(JSON.parse(String(message.encrypted_content).slice(7))).toMatchObject({
      action: "ended", active_elapsed_seconds: 37 });
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.lifecycle.recovery-and-billing,video-call.privacy
  it("retries a durable ciphertext row after a failed send without re-encrypting", async () => {
    mocks.socket.sendMessage.mockRejectedValueOnce(new Error("disconnected"));
    await expect(recordCallLifecycle(event)).rejects.toThrow("disconnected");
    const row = mocks.rows.get(`00000000-voice-call-${event.callId}-started`)!;
    expect(row.status).toBe("sending");
    const ciphertext = row.encrypted_content;
    const encryptions = mocks.db.getEncryptedFields.mock.calls.length;
    await retryPendingCallMessages();
    expect(mocks.db.getEncryptedFields.mock.calls).toHaveLength(encryptions);
    expect(row.encrypted_content).toBe(ciphertext);
    expect(mocks.rows.get(String(row.message_id))?.status).toBe("synced");
    expect(mocks.sent.map((entry) => entry.type)).toEqual(["chat_system_message_added"]);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.privacy
  it("rejects shared chat writes and malformed lifecycle data before persistence", async () => {
    mocks.db.getChat.mockResolvedValueOnce({ ...mocks.chat, team_id: "team" } as never);
    await expect(recordCallLifecycle(event)).rejects.toThrow("personal chat");
    await expect(recordCallLifecycle({ ...event, activeElapsedSeconds: -1 })).rejects.toThrow("Invalid");
    expect(mocks.rows.size).toBe(0);
    expect(mocks.sent).toHaveLength(0);
  });
});


import { parseVoiceCallHistoryEvent, voiceCallLifecycleMessageId } from "../voiceCallLifecycleEvent";
// contract-test: supporting surface=gui.web assertions=video-call.chat.call-events
it("parses only valid lifecycle history schemas", () => {
  const event = { schema_version: 1, type: "voice_call", action: "ended", call_id: "call-12345678",
    created_at: 1700000000, active_elapsed_seconds: 42 };
  expect(parseVoiceCallHistoryEvent(JSON.stringify(event))).toEqual(event);
  for (const invalid of ["null", "[]", "not JSON", JSON.stringify({ ...event, action: "grant_privilege" }),
    JSON.stringify({ ...event, active_elapsed_seconds: -1 }), JSON.stringify({ ...event, created_at: "12:31" })]) {
    expect(parseVoiceCallHistoryEvent(invalid)).toBeNull();
  }
});


// contract-test: supporting surface=gui.web assertions=video-call.chat.call-events
it("orders same-second lifecycle events around UUIDv7 transcripts while preserving timestamps", async () => {
  const callId = "call-same-second-1234";
  const occurredAt = 1_700_000_000;
  const event = { callId, chatId: "chat-uuid-1234", occurredAt, activeElapsedSeconds: 0 };
  await recordCallLifecycle({ ...event, type: "started" });
  await recordCallLifecycle({ ...event, type: "ended" });
  const start = voiceCallLifecycleMessageId(callId, "started");
  const end = voiceCallLifecycleMessageId(callId, "ended");
  const user = "018bcfe5-6800-7000-8000-000000000001";
  const assistant = "018bcfe5-6800-7000-8000-000000000002";
  expect([end, assistant, start, user].sort((a, b) => a.localeCompare(b))).toEqual([start, user, assistant, end]);
  for (const id of [start, end]) {
    const row = mocks.rows.get(id)!;
    expect(row.created_at).toBe(occurredAt);
    expect(JSON.parse(String(row.encrypted_content).slice(7)).created_at).toBe(occurredAt);
  }
  expect(voiceCallLifecycleMessageId(callId, "started")).toBe(start);
  expect(voiceCallLifecycleMessageId("call-other-1234", "started")).not.toBe(start);
});
