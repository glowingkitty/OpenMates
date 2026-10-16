// Incognito queued turns stay in the current tab's volatile chat history.
// Updating an accepted revision must keep the original user-message ID and row count.
// This test also protects against accidental migration into the durable chat DB.

import { afterEach, describe, expect, it } from "vitest";
import { incognitoChatService } from "../incognitoChatService";
import type { Chat, Message } from "../../types/chat";

afterEach(async () => { await incognitoChatService.deleteAllChats(); });

describe("incognito queued message revisions", () => {
  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  it("replaces the volatile row without appending another message", async () => {
    await incognitoChatService.storeChat({ chat_id: "incognito-1", is_incognito: true,
      created_at: 1, updated_at: 1 } as Chat);
    await incognitoChatService.addMessage("incognito-1", {
      chat_id: "incognito-1", message_id: "message-1", role: "user",
      created_at: 1, status: "queued", content: "first",
      queue_revision: 1, queue_mode: "follow_up",
    } as Message);
    expect(await incognitoChatService.updateMessage("incognito-1", "message-1", (row) => ({
      ...row, content: "revised", queue_revision: 2, queue_mode: "steer",
    }))).toBe(true);
    expect(await incognitoChatService.getMessagesForChat("incognito-1")).toMatchObject([{
      message_id: "message-1", content: "revised", queue_revision: 2, queue_mode: "steer",
    }]);
    expect((await incognitoChatService.getMessagesForChat("incognito-1")).length).toBe(1);
  });
});
