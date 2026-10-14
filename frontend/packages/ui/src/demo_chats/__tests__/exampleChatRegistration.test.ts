import { afterEach, describe, expect, it, vi } from "vitest";
import { embedStore } from "../../services/embedStore";
import { ALL_EXAMPLE_CHATS } from "../exampleChatData";
import { getExampleChatMessages, getExampleChatEmbed, getExampleChatEmbedPiiMappings, resolveExampleChatEmbedRef, resolveExampleFullscreenTarget } from "../exampleChatStore";
import { clearEmbedError, markEmbedAsError, resolveEmbed } from "../../services/embedResolver";

afterEach(() => vi.restoreAllMocks());

describe("example embed registration", () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("resolves refs only within the opened example group without writing the private index", () => {
    const selected = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-us-egg-prices-deep")!;
    const other = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const selectedEmbeds = [...selected.embeds, ...(selected.sub_chats ?? []).flatMap((subChat) => subChat.embeds)]
      .filter((embed) => embed.content && embed.embed_id);
    const first = selectedEmbeds[0];
    const otherId = other.embeds.find((embed) => embed.content && embed.embed_id)!.embed_id;
    const staticWrite = vi.spyOn(embedStore, "registerStaticEmbed");
    const refWrite = vi.spyOn(embedStore, "registerEmbedRef");
    const piiWrite = vi.spyOn(embedStore, "setInMemoryOnly");
    embedStore.clearEmbedRefIndex();

    expect(getExampleChatMessages(selected.chat_id).length).toBeGreaterThan(0);
    expect(staticWrite).not.toHaveBeenCalled();
    expect(refWrite).not.toHaveBeenCalled();
    expect(piiWrite).not.toHaveBeenCalled();
    expect(resolveExampleChatEmbedRef(first.embed_id, selected.chat_id)?.embedId).toBe(first.embed_id);
    expect(embedStore.resolveByRef(otherId)).toBeNull();
    expect(resolveExampleChatEmbedRef(otherId, selected.chat_id)).toBeNull();

    const child = selected.sub_chats?.[0];
    expect(child).toBeDefined();
    expect(getExampleChatMessages(child!.chat_id).length).toBeGreaterThan(0);
    expect(staticWrite).not.toHaveBeenCalled();

    embedStore.clearEmbedRefIndex();
    getExampleChatMessages(selected.chat_id);
    expect(staticWrite).not.toHaveBeenCalled();
    expect(refWrite).not.toHaveBeenCalled();
    expect(resolveExampleChatEmbedRef(first.embed_id, selected.chat_id)?.embedId).toBe(first.embed_id);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("keeps a source embed UUID private outside its reviewed example group", async () => {
    const example = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const publicEmbed = example.embeds.find((embed) => embed.content && embed.embed_id)!;
    const privateContent = "private owner ciphertext decoded content";
    const privateRead = vi.spyOn(embedStore, "get").mockResolvedValue({
      embed_id: publicEmbed.embed_id, type: publicEmbed.type, status: "finished", content: privateContent,
    });
    try {
      getExampleChatMessages(example.chat_id);
      expect(getExampleChatEmbed(publicEmbed.embed_id, example.chat_id)?.content).toBe(publicEmbed.content);
      expect(getExampleChatEmbed(publicEmbed.embed_id, "private-source-chat")).toBeNull();
      expect(resolveExampleFullscreenTarget(publicEmbed.embed_id, "private-source-chat")).toBeNull();
      expect((await resolveEmbed(publicEmbed.embed_id))?.content).toBe(privateContent);
      expect((await resolveEmbed(publicEmbed.embed_id, { chatId: "private-source-chat" }))?.content).toBe(privateContent);
      markEmbedAsError(publicEmbed.embed_id, "error");
      expect((await resolveEmbed(publicEmbed.embed_id, { chatId: example.chat_id }))?.content).toBe(publicEmbed.content);
      expect(privateRead).toHaveBeenCalledTimes(2);
    } finally {
      clearEmbedError(publicEmbed.embed_id);
      privateRead.mockRestore();
    }
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("resolves an authored generated-media alias when public source content is JSON", () => {
    const selected = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const embed = selected.embeds[0];
    const original = embed.content;
    const alias = "generated-images-public-alias";
    embedStore.registerEmbedRef(alias, "private-source-id", "private");
    const refWrite = vi.spyOn(embedStore, "registerEmbedRef");
    try {
      embed.content = JSON.stringify({ app_id: "images", skill_id: "generated_image", embed_ref: alias });
      getExampleChatMessages(selected.chat_id);
      expect(resolveExampleChatEmbedRef(alias, selected.chat_id)?.embedId).toBe(embed.embed_id);
      expect(resolveExampleChatEmbedRef(alias, "private-source-chat")).toBeNull();
      expect(embedStore.resolveByRef(alias)).toBe("private-source-id");
      expect(refWrite).not.toHaveBeenCalled();
    } finally {
      embed.content = original;
      embedStore.clearEmbedRefIndex();
    }
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("keeps public PII sidecars scoped and preserves the private sidecar key", async () => {
    const selected = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === "example-community-garden-sunflower-illustration")!;
    const embed = selected.embeds[0];
    const original = embed.pii_mappings;
    const privateSidecar = { embed_id: embed.embed_id, pii_mappings: [{ placeholder: "private" }] };
    const privateRead = vi.spyOn(embedStore, "get").mockResolvedValue(privateSidecar);
    const write = vi.spyOn(embedStore, "setInMemoryOnly");
    try {
      embed.pii_mappings = [{ placeholder: "public" }] as typeof embed.pii_mappings;
      getExampleChatMessages(selected.chat_id);
      expect(getExampleChatEmbedPiiMappings(embed.embed_id, selected.chat_id)).toEqual(embed.pii_mappings);
      expect(getExampleChatEmbedPiiMappings(embed.embed_id, "private-source-chat")).toBeNull();
      expect(await embedStore.get(`embed_pii:${embed.embed_id}`)).toBe(privateSidecar);
      expect(write).not.toHaveBeenCalled();
    } finally {
      embed.pii_mappings = original;
      privateRead.mockRestore();
    }
  });
});
