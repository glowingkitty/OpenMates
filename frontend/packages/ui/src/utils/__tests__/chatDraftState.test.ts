// frontend/packages/ui/src/utils/__tests__/chatDraftState.test.ts
//
// Regression coverage for persisted draft-only chat classification. Draft
// payload fields can be transiently absent during save/restore, while draft_v
// remains the durable signal that the chat shell still contains a draft.

import { describe, expect, it } from "vitest";

import type { Chat } from "../../types/chat";
import { isPersistedDraftOnlyChat } from "../chatDraftState";

describe("persisted draft-only chat classification", () => {
  it("uses a positive draft version when encrypted draft fields are absent", () => {
    const chat = {
      chat_id: "draft-chat",
      draft_v: 1,
      messages_v: 0,
    } as Chat;

    expect(isPersistedDraftOnlyChat(chat)).toBe(true);
  });

  it("does not classify established chats with messages as draft-only", () => {
    const chat = {
      chat_id: "established-chat",
      draft_v: 1,
      messages_v: 1,
    } as Chat;

    expect(isPersistedDraftOnlyChat(chat)).toBe(false);
  });
});
