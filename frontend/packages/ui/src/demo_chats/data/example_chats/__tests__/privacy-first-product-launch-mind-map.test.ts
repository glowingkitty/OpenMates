// frontend/packages/ui/src/demo_chats/data/example_chats/__tests__/privacy-first-product-launch-mind-map.test.ts
//
// Regression coverage for the Mind Maps example chat.
// The settings content detail page discovers public example chats through
// metadata.content_embed_examples, so this guards the catalog link and embed payload.

import { describe, expect, it } from "vitest";

import { CONTENT_EMBED_CATALOG } from "../../../../data/embedRegistry.generated";
import { getExampleChatsForContentEmbed } from "../../../exampleChatStore";
import { privacyFirstProductLaunchMindMapChat } from "../privacy-first-product-launch-mind-map";

describe("Privacy-first product launch mind map example chat", () => {
  it("links the Mind Maps content catalog entry to a direct mindmap embed", () => {
    const catalogEntry = CONTENT_EMBED_CATALOG.find(
      (entry) => entry.id === "mindmaps.mindmap",
    );

    expect(catalogEntry).toMatchObject({
      appId: "mindmaps",
      contentTypeId: "mindmap",
      frontendType: "mindmaps-mindmap",
      exampleKey: "mindmaps.mindmap",
    });
    expect(
      privacyFirstProductLaunchMindMapChat.metadata.content_embed_examples,
    ).toContain("mindmaps.mindmap");
    expect(privacyFirstProductLaunchMindMapChat.embeds).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "mindmap",
          content: expect.stringContaining("app_id: mindmaps\nskill_id: mindmap"),
        }),
      ]),
    );
  });

  it("is returned by the settings content embed example lookup", () => {
    const examples = getExampleChatsForContentEmbed("mindmaps", "mindmap");

    expect(examples.map((chat) => chat.chat_id)).toContain(
      privacyFirstProductLaunchMindMapChat.chat_id,
    );
  });
});
