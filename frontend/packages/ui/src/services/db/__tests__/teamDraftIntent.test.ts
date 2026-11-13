import { describe, expect, it, vi } from "vitest";
import type { Chat } from "../../../types/chat";
import { setTeamDraftPendingSync } from "../chatCrudOperations";

/** In-memory `chats` store: every transaction answers its get asynchronously and completes after the put. */
function makeDatabase(initial: Chat) {
  let stored = initial;
  const put = vi.fn((chat: Chat) => { stored = chat; });
  const getTransaction = vi.fn(async () => {
    const transaction = {
      objectStore: () => ({
        get: () => {
          const request = { result: stored as Chat | undefined, onsuccess: null as (() => void) | null,
            onerror: null as (() => void) | null, error: null };
          queueMicrotask(() => {
            request.onsuccess?.();
            queueMicrotask(() => (transaction as { oncomplete?: () => void }).oncomplete?.());
          });
          return request;
        },
        put,
      }),
      oncomplete: null as (() => void) | null,
      onerror: null as (() => void) | null,
      onabort: null as (() => void) | null,
      error: null,
    };
    return transaction;
  });
  const db = { init: async () => {}, CHATS_STORE_NAME: "chats", getTransaction };
  return { db, put, getStored: () => stored };
}

describe("atomic Team draft intent", () => {
  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it("applies the Rust intent decision over the latest stored row", async () => {
    const local = { chat_id: "chat-1", team_id: "team-1", messages_v: 2,
      team_chat_pending_commit: false, encrypted_draft_md: "member-cipher", draft_v: 2 } as Chat;
    const fixture = makeDatabase(local);
    const result = await setTeamDraftPendingSync(fixture.db as never, "chat-1", "team-1", "update", () => true);
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
    const stale = await setTeamDraftPendingSync(fixture.db as never, "chat-1", "team-1", undefined,
      () => true, { kind: "update", cipher: "older-cipher", version: 2 });
    expect(stale).toBeNull();
    expect(fixture.put).not.toHaveBeenCalled();

    const switched = makeDatabase(local);
    const oldContextWrite = await setTeamDraftPendingSync(switched.db as never, "chat-1", "team-1", "delete",
      () => false);
    expect(oldContextWrite).toBeNull();
    expect(switched.put).not.toHaveBeenCalled();
  });
});
