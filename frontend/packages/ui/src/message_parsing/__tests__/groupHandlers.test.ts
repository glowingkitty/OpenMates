// Unit tests for embed grouping behavior.
// Reference-only embeds represent existing synced uploads selected from search.
// They must stay as standalone references so deleting or splitting groups cannot
// cascade into deleting the underlying uploaded file.
// These tests exercise the public group-handler registry behavior.

import { describe, expect, it } from "vitest";
import { groupHandlerRegistry } from "../groupHandlers";
import type { EmbedNodeAttributes } from "../types";

describe("groupHandlerRegistry", () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("does not group reference-only embeds", () => {
    const first: EmbedNodeAttributes = {
      id: "file-a",
      type: "code-code",
      status: "finished",
      contentRef: "embed:file-a",
      referenceOnly: true,
    };
    const second: EmbedNodeAttributes = {
      id: "file-b",
      type: "code-code",
      status: "finished",
      contentRef: "embed:file-b",
    };

    expect(groupHandlerRegistry.canGroup(first, second)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("groups consecutive image search result embeds", () => {
    const first: EmbedNodeAttributes = {
      id: "image-a",
      type: "images-image-result",
      status: "finished",
      contentRef: "embed:image-a",
      title: "First image",
      thumbnail_url: "https://example.com/first.jpg",
      source_domain: "example.com",
    } as EmbedNodeAttributes;
    const second: EmbedNodeAttributes = {
      id: "image-b",
      type: "images-image-result",
      status: "finished",
      contentRef: "embed:image-b",
      title: "Second image",
      thumbnail_url: "https://example.com/second.jpg",
      source_domain: "example.com",
    } as EmbedNodeAttributes;

    expect(groupHandlerRegistry.canGroup(first, second)).toBe(true);

    const group = groupHandlerRegistry.createGroup([first, second]);

    expect(group?.type).toBe("images-image-result-group");
    expect(group?.groupCount).toBe(2);
    expect(group?.groupedItems).toEqual([
      expect.objectContaining({
        id: "image-a",
        type: "images-image-result",
        thumbnail_url: "https://example.com/first.jpg",
      }),
      expect.objectContaining({
        id: "image-b",
        type: "images-image-result",
        thumbnail_url: "https://example.com/second.jpg",
      }),
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("preserves inline interactive question code when code embeds are grouped", () => {
    const questionJson = JSON.stringify({
      id: "iphone_interest_2026",
      type: "choice",
      question: "Which iPhone topic should we explore next?",
      options: [{ id: "camera", text: "Camera rumors" }],
    });
    const first: EmbedNodeAttributes = {
      id: "question-embed",
      type: "code-code",
      status: "finished",
      contentRef: null,
      language: "interactive_question",
      filename: "Code snippet",
      code: questionJson,
    };
    const second: EmbedNodeAttributes = {
      id: "code-embed",
      type: "code-code",
      status: "finished",
      contentRef: null,
      language: "typescript",
      filename: "example.ts",
    };

    const group = groupHandlerRegistry.createGroup([first, second]);

    expect(group?.type).toBe("code-code-group");
    expect(group?.groupedItems?.[0]).toMatchObject({
      id: "question-embed",
      language: "interactive_question",
      code: questionJson,
    });
  });
});
