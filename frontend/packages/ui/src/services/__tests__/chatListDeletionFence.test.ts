import { beforeEach, expect, it } from "vitest";
import type { Chat } from "../../types/chat";
import { chatListCache } from "../chatListCache";

const chat = (chat_id: string) => ({ chat_id }) as Chat;
const ids = () => chatListCache.getCache()?.map((item) => item.chat_id);

beforeEach(() => chatListCache.clear());

// contract-test: supporting surface=gui.web assertions=sync.deletion.partial-window-not-authoritative
it("keeps a confirmed deletion absent across old and fresh stale reads, then resets with context", async () => {
  chatListCache.setCache([chat("keep"), chat("deleted")]);

  let finishOldRead!: (chats: Chat[]) => void;
  const oldRead = new Promise<Chat[]>((resolve) => { finishOldRead = resolve; });
  const oldVersion = chatListCache.getContextVersion();
  const oldCommit = oldRead.then((chats) => chatListCache.setCacheIfUnchanged(chats, oldVersion));

  chatListCache.markChatDeleted("deleted");
  expect(ids()).toEqual(["keep"]);

  finishOldRead([chat("keep"), chat("deleted"), chat("older")]);
  expect(await oldCommit).toBe(true);
  expect(ids()).toEqual(["keep", "older"]);

  // A read begun after deletion may still return that row. Retain other chats.
  const newVersion = chatListCache.getContextVersion();
  expect(chatListCache.setCacheIfUnchanged([
    chat("keep"), chat("deleted"), chat("older"), chat("new"),
  ], newVersion)).toBe(true);
  expect(ids()).toEqual(["keep", "older", "new"]);

  chatListCache.upsertChat(chat("deleted"));
  expect(ids()).toEqual(["keep", "older", "new"]);

  chatListCache.clear(); // Logout or team context change.
  expect(chatListCache.setCacheIfUnchanged([chat("keep")], oldVersion)).toBe(false);
  chatListCache.setCache([chat("deleted")]);
  expect(ids()).toEqual(["deleted"]);
});

// contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
it("allows a removed draft-only shell to return as a real chat with the same ID", () => {
  chatListCache.setCache([chat("draft-promoted")]);
  chatListCache.removeChat("draft-promoted");
  expect(ids()).toEqual([]);

  chatListCache.upsertChat(chat("draft-promoted"));
  expect(ids()).toEqual(["draft-promoted"]);
});
