import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmbedStore } from "../embedStore";
import * as cryptoService from "../cryptoService";

describe("derived embed preview projections", () => {
  beforeEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); });

  async function fixture() {
    const store = new EmbedStore();
    const id = crypto.randomUUID();
    const ref = `embed:${id}`;
    const content = "type: app_skill_use\napp_id: web\nskill_id: search\nquery: architecture";
    const canonical = Object.freeze({
      embed_id: id, encrypted_content: "canonical-body", encrypted_type: "canonical-type",
      status: "finished", version_number: 1, hashed_chat_id: "chat", hashed_user_id: "owner",
      hashed_message_id: "message", content,
    });
    vi.spyOn(store as unknown as {
      readCanonicalEmbed(ref: string): Promise<Record<string, unknown>>;
    }, "readCanonicalEmbed").mockResolvedValue(canonical);
    return { store, ref, id, content };
  }

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("keeps previews readable while preserving canonical encrypted persistence bytes", async () => {
    const { store, ref } = await fixture();
    const before = await store.get(ref);
    const persist = vi.spyOn(store, "putEncrypted");
    const encrypt = vi.spyOn(cryptoService, "encryptWithEmbedKey");
    const fields = { result_count: 1, preview_results: [{ title: "Result", url: "https://example.com" }] };
    expect(await store.mergeDecodedContentForPreviewBackfill(ref, fields)).toEqual({ updated: true });
    expect(await store.mergeDecodedContentForPreviewBackfill(ref, fields)).toEqual({ updated: false });
    const view = await store.get(ref) as Record<string, unknown>;
    expect(JSON.parse(view.content as string)).toMatchObject(fields);
    expect(await (store as unknown as { readCanonicalEmbed(ref: string): Promise<unknown> }).readCanonicalEmbed(ref)).toEqual(before);
    expect(persist).not.toHaveBeenCalled();
    expect(encrypt).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("invalidates derived fields when the canonical revision changes or keys are cleared", async () => {
    const { store, ref, content } = await fixture();
    await store.mergeDecodedContentForPreviewBackfill(ref, { result_count: 1 });
    store.clearEmbedKeyCache();
    expect((await store.get(ref) as Record<string, unknown>).content).toBe(content);
    await store.mergeDecodedContentForPreviewBackfill(ref, { result_count: 2 });
    const read = vi.spyOn(store as unknown as {
      readCanonicalEmbed(ref: string): Promise<Record<string, unknown>>;
    }, "readCanonicalEmbed").mockResolvedValue({ content, version_number: 2 });
    expect(await store.get(ref)).toEqual({ content, version_number: 2 });
    read.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("does not let a preview projection replace content or routing identity", async () => {
    const { store, ref } = await fixture();
    const before = await store.get(ref);
    await expect(store.mergeDecodedContentForPreviewBackfill(ref, {
      encrypted_content: "replacement", version_number: 2,
    })).rejects.toThrow("Derived preview fields cannot change canonical");
    expect(await (store as unknown as { readCanonicalEmbed(ref: string): Promise<unknown> }).readCanonicalEmbed(ref)).toEqual(before);
  });
});
