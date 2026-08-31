// frontend/packages/ui/src/services/__tests__/applicationPreviewService.test.ts
//
// Regression coverage for application preview request context construction.
// Shared recipients depend on decrypted child embeds arriving before preview
// start so the backend can preserve strict owner authorization as a fallback.

import { beforeEach, describe, expect, it, vi } from "vitest";

const embedResolverMocks = vi.hoisted(() => ({
  decodeToonContent: vi.fn(),
  loadEmbedsWithRetry: vi.fn(),
}));

vi.mock("../embedResolver", () => ({
  decodeToonContent: embedResolverMocks.decodeToonContent,
  extractEmbedReferences: vi.fn(() => []),
  loadEmbedsWithRetry: embedResolverMocks.loadEmbedsWithRetry,
  resolveEmbed: vi.fn(),
}));

import { buildApplicationPreviewSharedContext } from "../applicationPreviewService";

describe("buildApplicationPreviewSharedContext", () => {
  beforeEach(() => {
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.loadEmbedsWithRetry.mockReset();
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
