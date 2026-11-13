import { beforeEach, describe, expect, it, vi } from "vitest";

const { getChat, addChat } = vi.hoisted(() => ({
  getChat: vi.fn(),
  addChat: vi.fn(),
}));
vi.mock("../chatCrudOperations", () => ({ getChat, addChat }));

import {
  updateChatComponentVersion,
  updateChatLastEditedTimestamp,
} from "../offlineChangesAndUpdates";

/**
 * A caller-created transaction can expire before addChat uses it; addChat then
 * commits on a replacement transaction and the original never fires oncomplete.
 * The version update must therefore settle from addChat itself (F74G7: a voice
 * call receipt handler hung behind this and every call event failed to save).
 */
function makeDatabase() {
  return {
    init: vi.fn(async () => {}),
    getTransaction: vi.fn(async () => {
      throw new Error("the version update must not open its own transaction");
    }),
    CHATS_STORE_NAME: "chats",
  };
}

describe("chat version updates settle from addChat", () => {
  beforeEach(() => {
    getChat.mockReset();
    addChat.mockReset();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.call-events
  it("updateChatComponentVersion resolves once addChat resolves, without a caller transaction", async () => {
    getChat.mockResolvedValue({ chat_id: "chat-1", messages_v: 1 });
    addChat.mockResolvedValue(undefined);
    const db = makeDatabase();

    await expect(
      updateChatComponentVersion(db as never, "chat-1", "messages_v", 4),
    ).resolves.toBeUndefined();

    expect(db.getTransaction).not.toHaveBeenCalled();
    expect(addChat).toHaveBeenCalledTimes(1);
    const [, saved, transaction] = addChat.mock.calls[0];
    expect(saved).toMatchObject({ chat_id: "chat-1", messages_v: 4 });
    expect(transaction).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.call-events
  it("updateChatComponentVersion rejects when addChat fails", async () => {
    getChat.mockResolvedValue({ chat_id: "chat-1" });
    addChat.mockRejectedValue(new Error("quota"));

    await expect(
      updateChatComponentVersion(makeDatabase() as never, "chat-1", "title_v", 2),
    ).rejects.toThrow("quota");
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.call-events
  it("updateChatLastEditedTimestamp resolves once addChat resolves, without a caller transaction", async () => {
    getChat.mockResolvedValue({ chat_id: "chat-1" });
    addChat.mockResolvedValue(undefined);
    const db = makeDatabase();

    await updateChatLastEditedTimestamp(db as never, "chat-1", 1234);

    expect(db.getTransaction).not.toHaveBeenCalled();
    expect(addChat.mock.calls[0][1]).toMatchObject({
      chat_id: "chat-1",
      last_edited_overall_timestamp: 1234,
    });
    expect(addChat.mock.calls[0][2]).toBeUndefined();
  });
});
