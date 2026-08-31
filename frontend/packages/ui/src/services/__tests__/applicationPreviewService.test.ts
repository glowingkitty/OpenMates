// frontend/packages/ui/src/services/__tests__/applicationPreviewService.test.ts
//
// Regression coverage for application preview request context construction.
// Shared recipients depend on decrypted child embeds arriving before preview
// start so the backend can preserve strict owner authorization as a fallback.

import { beforeEach, describe, expect, it, vi } from "vitest";

const embedResolverMocks = vi.hoisted(() => ({
  decodeToonContent: vi.fn(),
  extractEmbedReferences: vi.fn(),
  loadEmbedsWithRetry: vi.fn(),
  resolveEmbed: vi.fn(),
}));

vi.mock("../embedResolver", () => ({
  decodeToonContent: embedResolverMocks.decodeToonContent,
  extractEmbedReferences: embedResolverMocks.extractEmbedReferences,
  loadEmbedsWithRetry: embedResolverMocks.loadEmbedsWithRetry,
  resolveEmbed: embedResolverMocks.resolveEmbed,
}));

import { autoStartCreatedApplicationPreview, buildApplicationPreviewSharedContext } from "../applicationPreviewService";

describe("buildApplicationPreviewSharedContext", () => {
  beforeEach(() => {
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.extractEmbedReferences.mockReset();
    embedResolverMocks.loadEmbedsWithRetry.mockReset();
    embedResolverMocks.resolveEmbed.mockReset();
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("waits for shared application child embeds before building context", async () => {
    embedResolverMocks.loadEmbedsWithRetry.mockResolvedValue([
      { embed_id: "file-1", content: "toon-1" },
      { embed_id: "file-2", content: "toon-2" },
    ]);
    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => ({ code: content }));

    const context = await buildApplicationPreviewSharedContext("application-1", {
      type: "application",
      file_refs: [
        { embed_id: "file-1", path: "src/App.svelte" },
        { embed_id: "file-2", path: "src/main.ts" },
      ],
    });

    expect(embedResolverMocks.loadEmbedsWithRetry).toHaveBeenCalledWith(["file-1", "file-2"]);
    expect(JSON.parse(context!)).toMatchObject({
      application_embed_id: "application-1",
      child_contents: {
        "file-1": { code: "toon-1" },
        "file-2": { code: "toon-2" },
      },
    });
  });
});

describe("autoStartCreatedApplicationPreview", () => {
  beforeEach(() => {
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.extractEmbedReferences.mockReset();
    embedResolverMocks.loadEmbedsWithRetry.mockReset();
    embedResolverMocks.resolveEmbed.mockReset();
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
});
