import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../../types/chat";

const mocks = vi.hoisted(() => {
  const rows = new Map<string, { message_id: string; chat_id: string; status: string; encrypted_content: string }>();
  return {
    rows,
    connected: true,
    getMessage: vi.fn(async (id: string) => rows.get(id) ?? null),
    updateMessageStatus: vi.fn(async (id: string, status: string) => {
      const row = rows.get(id);
      if (row) row.status = status;
    }),
    isConnected: vi.fn(() => mocks.connected),
    forceReconnect: vi.fn(),
  };
});

vi.mock("../db", () => ({ chatDB: {
  getMessage: mocks.getMessage,
  updateMessageStatus: mocks.updateMessageStatus,
} }));
vi.mock("../websocketService", () => ({ webSocketService: {
  isConnected: mocks.isConnected,
  forceReconnect: mocks.forceReconnect,
} }));

import { recordMessageDispatchFailure } from "../sendersChatMessagesDispatchFailure";

const sentMessage = {
  message_id: "chat-one-user-one",
  chat_id: "chat-one",
  role: "user",
  content: "submitted text",
  status: "sending",
  created_at: 123,
} as Message;

describe("message dispatch failure after preflight", () => {
  beforeEach(() => {
    mocks.rows.clear();
    mocks.rows.set(sentMessage.message_id, {
      message_id: sentMessage.message_id,
      chat_id: sentMessage.chat_id,
      status: "sending",
      encrypted_content: "sealed-original-user-row",
    });
    mocks.connected = true;
    vi.clearAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it("retains the same encrypted user row for reconnect when the socket drops during dispatch", async () => {
    mocks.connected = false;
    const target = new EventTarget();
    const statuses: Array<{ chatId: string; messageId: string; status: string }> = [];
    target.addEventListener("messageStatusChanged", (event) => {
      statuses.push((event as CustomEvent).detail);
    });

    expect(await recordMessageDispatchFailure(target, sentMessage, true)).toBe("waiting_for_internet");
    expect(mocks.rows.size).toBe(1);
    expect(mocks.rows.get(sentMessage.message_id)).toEqual({
      message_id: sentMessage.message_id,
      chat_id: sentMessage.chat_id,
      status: "waiting_for_internet",
      encrypted_content: "sealed-original-user-row",
    });
    expect(mocks.updateMessageStatus).toHaveBeenCalledWith(sentMessage.message_id, "waiting_for_internet");
    expect(statuses).toEqual([{ chatId: sentMessage.chat_id, messageId: sentMessage.message_id, status: "waiting_for_internet" }]);
    expect(mocks.forceReconnect).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it("leaves a connected validation or serialization failure out of automatic retry", async () => {
    const target = new EventTarget();

    expect(await recordMessageDispatchFailure(target, sentMessage, true)).toBe("failed");
    expect(mocks.rows.get(sentMessage.message_id)?.status).toBe("failed");
    expect(mocks.forceReconnect).not.toHaveBeenCalled();

    mocks.connected = false;
    expect(await recordMessageDispatchFailure(target, sentMessage, false)).toBe("failed");
    expect(mocks.forceReconnect).not.toHaveBeenCalled();
  });
});
