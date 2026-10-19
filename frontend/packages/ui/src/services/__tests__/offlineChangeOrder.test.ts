import { describe, expect, it } from "vitest";
import type { OfflineChange } from "../../types/chat";
import { orderOfflineChanges } from "../offlineChangeOrder";

const row = (id: string, order?: number, type: OfflineChange["type"] = "draft", version = 0): OfflineChange => ({
  change_id: id, chat_id: "chat-1", type, value: type === "delete_draft" ? null : `cipher-${id}`,
  version_before_edit: version, ...(order === undefined ? {} : { queue_order: order }),
});

describe("offline edit chronology", () => {
  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("replays reverse UUID order causally and preserves a delete followed by a reset draft", () => {
    const changes = [row("a-new", 3, "draft", 0), row("b-delete", 2, "delete_draft", 6), row("c-old", 1, "draft", 5)];
    const result = orderOfflineChanges(changes);
    expect(result.ready.map((change) => change.change_id)).toEqual(["c-old", "b-delete", "a-new"]);
    expect(result.retainedCount).toBe(0);
    expect(changes[0].change_id).toBe("a-new");
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("retains ambiguous historical edits while allowing unrelated components and chats", () => {
    const changes = [row("old-a", undefined, "delete_draft", 7), row("old-b", undefined, "draft", 0),
      row("newer", 3), row("title", 4, "title"), { ...row("other", 5), chat_id: "chat-2" }];
    expect(orderOfflineChanges(changes)).toEqual({ ready: [changes[3], changes[4]], retainedCount: 3 });
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("retains mixed-version tab edits because a legacy row may be the newest post-delete draft", () => {
    const changes = [row("reset", 2, "draft", 0), row("legacy", undefined, "delete_draft", 9)];
    expect(orderOfflineChanges(changes)).toEqual({ ready: [], retainedCount: 2 });
    expect(orderOfflineChanges([changes[1]])).toEqual({ ready: [changes[1]], retainedCount: 0 });
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it.each([0, -1, NaN, 1.5, Number.MAX_SAFE_INTEGER + 1])("retains invalid order %s", (order) => {
    expect(orderOfflineChanges([row("bad", order)])).toEqual({ ready: [], retainedCount: 1 });
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("retains duplicate order within a component while isolating Team groups", () => {
    const other = { ...row("other-team", 1), team_id: "team-2" };
    expect(orderOfflineChanges([row("a", 1), row("b", 1), other])).toEqual({ ready: [other], retainedCount: 2 });
  });
});
