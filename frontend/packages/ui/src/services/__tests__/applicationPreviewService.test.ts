// frontend/packages/ui/src/services/__tests__/applicationPreviewService.test.ts
//
// Regression coverage for application preview request context construction.
// Shared recipients depend on decrypted child embeds arriving before preview
// start so the backend can preserve strict owner authorization as a fallback.

import { beforeEach, describe, expect, it, vi } from "vitest";

const embedResolverMocks = vi.hoisted(() => ({
  decodeToonContent: vi.fn(),
  extractEmbedReferences: vi.fn(),
  resolveEmbed: vi.fn(),
}));
const ownerChatMocks = vi.hoisted(() => ({
  getChat: vi.fn(),
  isPublicChat: vi.fn(),
}));

vi.mock("../embedResolver", () => ({
  decodeToonContent: embedResolverMocks.decodeToonContent,
  extractEmbedReferences: embedResolverMocks.extractEmbedReferences,
  resolveEmbed: embedResolverMocks.resolveEmbed,
}));
vi.mock("../db", () => ({ chatDB: { getChat: ownerChatMocks.getChat } }));
vi.mock("../../demo_chats", () => ({ isPublicChat: ownerChatMocks.isPublicChat }));

import {
  autoStartApplicationPreviewForEmbed,
  autoStartCreatedApplicationPreview,
  autoStartVisibleOwnerApplicationPreviewForEmbed,
  buildApplicationPreviewSharedContext,
  startApplicationPreview,
} from "../applicationPreviewService";

describe("buildApplicationPreviewSharedContext", () => {
  beforeEach(() => {
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.extractEmbedReferences.mockReset();
    embedResolverMocks.resolveEmbed.mockReset();
    ownerChatMocks.getChat.mockReset();
    ownerChatMocks.isPublicChat.mockReset();
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("waits for shared application child embeds before building context", async () => {
    let firstFileAttempts = 0;
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => {
      if (embedId === "file-1" && firstFileAttempts++ === 0) return null;
      return { embed_id: embedId, content: embedId === "file-1" ? "toon-1" : "toon-2" };
    });
    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => ({ code: content }));

    const context = await buildApplicationPreviewSharedContext("application-1", {
      type: "application",
      file_refs: [
        { embed_id: "file-1", path: "src/App.svelte" },
        { embed_id: "file-2", path: "src/main.ts" },
      ],
    }, "shared-chat-1");

    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("file-1", { chatId: "shared-chat-1" });
    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("file-2", { chatId: "shared-chat-1" });
    expect(firstFileAttempts).toBe(2);
    expect(JSON.parse(context!)).toMatchObject({
      application_embed_id: "application-1",
      child_contents: {
        "file-1": { code: "toon-1" },
        "file-2": { code: "toon-2" },
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("uses only the captured public example's child source despite a private same-ID embed", async () => {
    vi.stubGlobal("fetch", vi.fn());
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string, options?: { chatId?: string }) => ({
      embed_id: embedId,
      content: options?.chatId === "public-example" ? "public-source" : "private-source",
    }));
    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => ({ code: content }));

    const context = await buildApplicationPreviewSharedContext("application-public", {
      type: "application",
      file_refs: [{ embed_id: "file-collision", path: "src/App.svelte" }],
    }, "public-example");

    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("file-collision", { chatId: "public-example" });
    expect(JSON.parse(context!).child_contents["file-collision"]).toEqual({ code: "public-source" });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

describe("autoStartCreatedApplicationPreview", () => {
  beforeEach(() => {
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.extractEmbedReferences.mockReset();
    embedResolverMocks.resolveEmbed.mockReset();
    ownerChatMocks.getChat.mockReset();
    ownerChatMocks.isPublicChat.mockReset();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        session_id: "session-1",
        preview_url: "https://preview-test.dev.openmatesusercontent.org",
        status: "running",
        credits_per_minute: 0,
      }),
    })));
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
  it("starts a missing owner screenshot without client shared context", async () => {
    ownerChatMocks.getChat.mockResolvedValue({ chat_id: "owner-chat", is_shared_by_others: false });
    embedResolverMocks.resolveEmbed.mockResolvedValue({ embed_id: "owner-application", content: "application-toon" });
    embedResolverMocks.decodeToonContent.mockResolvedValue({ type: "application" });

    const session = await autoStartVisibleOwnerApplicationPreviewForEmbed("owner-chat", "assistant-1", "owner-application");

    expect(session?.session_id).toBe("session-1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/applications/owner-application/preview/start"),
      expect.objectContaining({
        body: JSON.stringify({
          chat_id: "owner-chat",
          shared_context: undefined,
          auto_started: true,
          source_message_id: "assistant-1",
        }),
      }),
    );
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
  it("reuses the creator session instead of starting a second paid preview", async () => {
    ownerChatMocks.getChat.mockResolvedValue({ chat_id: "creator-chat", is_shared_by_others: false });
    await startApplicationPreview("creator-chat", "creator-application", {
      autoStarted: true,
      sourceMessageId: "assistant-creator",
    });

    const session = await autoStartVisibleOwnerApplicationPreviewForEmbed(
      "creator-chat", undefined, "creator-application",
    );

    expect(session?.session_id).toBe("session-1");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
  it.each([
    ["public example", "public-chat", true, { chat_id: "public-chat" }],
    ["shared recipient", "shared-chat", false, { chat_id: "shared-chat", is_shared_by_others: true }],
    ["unknown local chat", "unknown-chat", false, null],
  ])("does not auto-start for %s", async (_label, chatId, isPublic, chat) => {
    ownerChatMocks.isPublicChat.mockReturnValue(isPublic);
    ownerChatMocks.getChat.mockResolvedValue(chat);

    const session = await autoStartVisibleOwnerApplicationPreviewForEmbed(chatId, undefined, "application-1");

    expect(session).toBeUndefined();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("auto-starts application previews whose markdown reference is typed as code", async () => {
    embedResolverMocks.extractEmbedReferences.mockReturnValue([
      { type: "code", embed_id: "file-embed-1" },
      { type: "code", embed_id: "application-embed-1" },
    ]);
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => ({
      embed_id: embedId,
      content: embedId === "application-embed-1" ? "application-toon" : "code-toon",
    }));
    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => ({
      type: content === "application-toon" ? "application" : "code",
    }));

    const session = await autoStartCreatedApplicationPreview("chat-1", "message-1", "markdown");

    expect(session?.session_id).toBe("session-1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/applications/application-embed-1/preview/start"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          chat_id: "chat-1",
          shared_context: undefined,
          auto_started: true,
          source_message_id: "message-1",
        }),
      }),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("auto-starts application previews from finalized application embed events", async () => {
    embedResolverMocks.resolveEmbed.mockResolvedValue({
      embed_id: "application-embed-from-event",
      content: "application-toon",
    });
    embedResolverMocks.decodeToonContent.mockResolvedValue({ type: "application" });

    const session = await autoStartApplicationPreviewForEmbed(
      "chat-1",
      "message-from-event",
      "application-embed-from-event",
    );

    expect(session?.session_id).toBe("session-1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/applications/application-embed-from-event/preview/start"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          chat_id: "chat-1",
          shared_context: undefined,
          auto_started: true,
          source_message_id: "message-from-event",
        }),
      }),
    );
  });
});
