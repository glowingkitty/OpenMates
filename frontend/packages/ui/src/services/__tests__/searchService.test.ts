// frontend/packages/ui/src/services/__tests__/searchService.test.ts
// Regression coverage for the chat search service.
// Draft-only chats can arrive from CLI/SDK sync before they have a title or
// messages. Their only searchable plaintext in the browser is the decrypted
// draft preview, so search must include that metadata surface.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../types/chat";

const mocks = vi.hoisted(() => ({
  getMessagesForChat: vi.fn(),
  getDecryptedMetadata: vi.fn(),
}));

vi.mock("../db", () => ({
  chatDB: {
    getMessagesForChat: mocks.getMessagesForChat,
  },
}));

vi.mock("../chatMetadataCache", () => ({
  chatMetadataCache: {
    getDecryptedMetadata: mocks.getDecryptedMetadata,
  },
}));

vi.mock("../searchSettingsCatalog", () => ({
  getSettingsSearchCatalog: () => [],
  getAppSearchCatalog: () => [],
}));

vi.mock("../../data/appsMetadata", () => ({
  appsMetadata: {},
}));

vi.mock("../../demo_chats", () => ({
  getDemoMessages: () => [],
  isPublicChat: () => false,
  isExampleChat: () => false,
  INTRO_CHATS: [],
  LEGAL_CHATS: [],
}));

vi.mock("../embedResolver", () => ({
  extractEmbedReferences: () => [],
}));

describe("search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getMessagesForChat.mockResolvedValue([]);
  });

  it("finds draft-only chats by decrypted draft preview", async () => {
    const { search } = await import("../searchService");
    const chat = {
      chat_id: "chat-draft-only",
      encrypted_title: null,
      encrypted_draft_preview: "encrypted-preview",
      messages_v: 0,
      title_v: 0,
      draft_v: 1,
      unread_count: 0,
      created_at: 100,
      updated_at: 100,
      last_edited_overall_timestamp: 100,
    } as Chat;
    mocks.getDecryptedMetadata.mockResolvedValue({
      chat_id: chat.chat_id,
      title: null,
      draftPreview: "CLI encrypted draft searchable text",
      icon: null,
      category: null,
      summary: null,
      tags: null,
      activeFocusId: null,
      lastDecrypted: Date.now(),
    });

    const results = await search(
      "searchable text",
      [chat],
      (key: string) => key,
      [],
      true,
    );

    expect(results.chats).toHaveLength(1);
    expect(results.chats[0]?.chat.chat_id).toBe(chat.chat_id);
    expect(results.chats[0]?.metadataSnippets[0]).toMatchObject({
      matchSource: "draft",
      snippet: "CLI encrypted draft searchable text",
    });
  });
});
