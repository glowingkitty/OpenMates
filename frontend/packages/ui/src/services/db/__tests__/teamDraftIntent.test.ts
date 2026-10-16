import { describe, expect, it, vi } from "vitest";
import type { Chat } from "../../../types/chat";
import { setTeamDraftPendingSync } from "../chatCrudOperations";

function makeDatabase(initial: Chat) {
  let stored = initial;
  const request = { result: initial, onsuccess: null as (() => void) | null,
    onerror: null as (() => void) | null, error: null as DOMException | null };
  const put = vi.fn((chat: Chat) => { stored = chat; });
  const transaction = {
    objectStore: () => ({ get: () => request, put }),
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    error: null as DOMException | null,
  };
  const db = { init: async () => {}, CHATS_STORE_NAME: "chats",
    getTransaction: async () => transaction };
  return { db, request, transaction, put, getStored: () => stored,
    replaceStored: (chat: Chat) => { stored = chat; request.result = chat; } };
}

describe("atomic Team draft intent", () => {
  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it("preserves a first-message ACK committed before the intent transaction reads", async () => {
    const local = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: true, encrypted_draft_md: "member-cipher", draft_v: 2 } as Chat;
    const fixture = makeDatabase(local);
    const writing = setTeamDraftPendingSync(fixture.db as never, "chat-1", "team-1", "update", () => true);
    await vi.waitFor(() => expect(fixture.request.onsuccess).not.toBeNull());
    fixture.replaceStored({ ...local, team_chat_pending_commit: false, messages_v: 2 });
    fixture.request.onsuccess?.();
    fixture.transaction.oncomplete?.();
    const result = await writing;
    expect(result).toEqual(expect.objectContaining({
      messages_v: 2, team_chat_pending_commit: false,
      team_draft_pending_sync: "update", encrypted_draft_md: "member-cipher",
    }));
    expect(fixture.getStored()).toEqual(result);
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("rejects a stale workspace or newer draft when clearing intent", async () => {
    const local = { chat_id: "chat-1", team_id: "team-1", messages_v: 2,
      team_draft_pending_sync: "update", encrypted_draft_md: "newer-cipher", draft_v: 3 } as Chat;
    const fixture = makeDatabase(local);
    let current = true;
    const writing = setTeamDraftPendingSync(fixture.db as never, "chat-1", "team-1", undefined,
      () => current, { kind: "update", cipher: "older-cipher", version: 2 });
    await vi.waitFor(() => expect(fixture.request.onsuccess).not.toBeNull());
    fixture.request.onsuccess?.();
    fixture.transaction.oncomplete?.();
    expect(await writing).toBeNull();
    expect(fixture.put).not.toHaveBeenCalled();

    const switched = makeDatabase(local);
    const oldContextWrite = setTeamDraftPendingSync(switched.db as never, "chat-1", "team-1", "delete",
      () => current);
    await vi.waitFor(() => expect(switched.request.onsuccess).not.toBeNull());
    current = false;
    switched.request.onsuccess?.();
    switched.transaction.oncomplete?.();
    expect(await oldContextWrite).toBeNull();
    expect(switched.put).not.toHaveBeenCalled();
  });
});
