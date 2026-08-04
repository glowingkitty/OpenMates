// frontend/packages/ui/src/stores/__tests__/chatNavigationStore.test.ts
// Regression tests for header navigation chat filtering.
// Draft-only chats must remain navigable while the sidebar is closed.
// Otherwise draft save events rebuild navigation from IndexedDB on every save.
// This guards Safari from account-size proportional chat reload storms.

import { describe, expect, it } from "vitest";

import { isHeaderNavigableChat } from "../chatNavigationStore";
import type { Chat } from "../../types/chat";

describe("isHeaderNavigableChat", () => {
  it("treats encrypted draft-only chats as navigable", () => {
    expect(
      isHeaderNavigableChat({
        chat_id: "draft-only-chat",
        messages_v: 0,
        encrypted_draft_md: "encrypted-draft-body",
      } as Chat),
    ).toBe(true);
  });
});
