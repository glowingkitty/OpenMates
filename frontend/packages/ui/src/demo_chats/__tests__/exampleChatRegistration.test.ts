import { afterEach, describe, expect, it, vi } from "vitest";
import { embedStore } from "../../services/embedStore";
import { ALL_EXAMPLE_CHATS } from "../exampleChatData";
import { getExampleChatMessages } from "../exampleChatStore";

afterEach(() => vi.restoreAllMocks());

describe("example embed registration", () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("loads only the opened chat group, avoids repeat cache writes, and repairs a cleared ref index", () => {
    const selected = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-us-egg-prices-deep")!;
    const other = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const selectedEmbeds = [...selected.embeds, ...(selected.sub_chats ?? []).flatMap((subChat) => subChat.embeds)]
      .filter((embed) => embed.content && embed.embed_id);
    const first = selectedEmbeds[0];
    const otherId = other.embeds.find((embed) => embed.content && embed.embed_id)!.embed_id;
    const staticWrite = vi.spyOn(embedStore, "registerStaticEmbed");
    embedStore.clearEmbedRefIndex();

    expect(getExampleChatMessages(selected.chat_id).length).toBeGreaterThan(0);
    expect(staticWrite).toHaveBeenCalledTimes(selectedEmbeds.length);
    expect(embedStore.resolveByRef(first.embed_id)).toBe(first.embed_id);
    expect(embedStore.resolveByRef(otherId)).toBeNull();

    const child = selected.sub_chats?.[0];
    expect(child).toBeDefined();
    expect(getExampleChatMessages(child!.chat_id).length).toBeGreaterThan(0);
    expect(staticWrite).toHaveBeenCalledTimes(selectedEmbeds.length);

    embedStore.clearEmbedRefIndex();
    getExampleChatMessages(selected.chat_id);
    expect(staticWrite).toHaveBeenCalledTimes(selectedEmbeds.length * 2);
    expect(embedStore.resolveByRef(first.embed_id)).toBe(first.embed_id);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("resolves an authored generated-media alias when public source content is JSON", () => {
    const selected = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const embed = selected.embeds[0];
    const original = embed.content;
    const alias = "generated-images-public-alias";
    const refWrite = vi.spyOn(embedStore, "registerEmbedRef");
    try {
      embed.content = JSON.stringify({ app_id: "images", skill_id: "generated_image", embed_ref: alias });
      embedStore.clearEmbedRefIndex();
      getExampleChatMessages(selected.chat_id);
      expect(embedStore.resolveByRef(alias)).toBe(embed.embed_id);
      expect(refWrite).toHaveBeenCalledWith(alias, embed.embed_id, "images");
    } finally {
      embed.content = original;
      embedStore.clearEmbedRefIndex();
    }
  });
});
