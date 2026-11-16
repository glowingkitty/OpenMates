// Frozen vectors written by the web TS embed-key and short-URL writers (generate_share_links.cjs),
// including legacy six-character short links. The TS readers must keep opening them; the Rust
// replay of the same file is packages/openmates-rust/tests/web_share_links_corpus.rs.
import { beforeAll, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import vectors from "../../../../../../../packages/openmates-rust/tests/crypto_fixtures/ts_share_links.json";

let embedKey: Uint8Array | null = null;
vi.mock("../../embedStore", () => ({ embedStore: { getEmbedKey: async () => embedKey } }));
vi.mock("../../shareState/decide", () => ({ decideShareState: async () => null }));

import { decryptEmbedShareKeyBlob, generateEmbedShareKeyBlob } from "../../embedShareEncryption";
import { decryptShareUrl, encryptShareUrl } from "../../shortUrlEncryption";

const fromB64 = (b64: string): Uint8Array => new Uint8Array(Buffer.from(b64, "base64"));

// jsdom has no full SubtleCrypto (deriveKey); use Node's, as the other share-encryption tests do.
beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, writable: true, configurable: true });
});

describe("frozen share-link vectors", () => {
  for (const c of vectors.embed_blobs) {
    // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
    it(`opens embed blob ${c.label}`, async () => {
      const opened = await decryptEmbedShareKeyBlob(vectors.embed_id, c.blob, vectors.generated_at + 10, c.password ?? undefined);
      expect(opened.success).toBe(true);
      expect(Buffer.from(opened.embedKey!).toString("base64")).toBe(c.embed_key_b64);
      embedKey = fromB64(c.embed_key_b64);
      const fresh = await generateEmbedShareKeyBlob(vectors.embed_id, c.duration_seconds as 0, c.password ?? undefined);
      const again = await decryptEmbedShareKeyBlob(vectors.embed_id, fresh, Math.floor(Date.now() / 1000), c.password ?? undefined);
      expect(again.success).toBe(true);
    });
  }
  for (const c of vectors.short_urls) {
    // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
    it(`opens short url ${c.label}`, async () => {
      expect(await decryptShareUrl(c.encrypted, c.token, c.short_key)).toBe(c.url);
      const fresh = await encryptShareUrl(c.url, c.token, c.short_key);
      expect(await decryptShareUrl(fresh, c.token, c.short_key)).toBe(c.url);
    });
  }
});
