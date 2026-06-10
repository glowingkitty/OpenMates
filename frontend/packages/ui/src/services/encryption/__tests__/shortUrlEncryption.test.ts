// frontend/packages/ui/src/services/encryption/__tests__/shortUrlEncryption.test.ts
// Unit tests for shortUrlEncryption — client-side encryption for durable share short links.
//
// The public token must be in the URL path so crawlers can fetch OG metadata.
// The shortKey remains in the fragment so the server never receives the secret
// needed to decrypt the opaque long share URL blob.

import { describe, it, expect, beforeAll } from "vitest";
import { webcrypto } from "node:crypto";

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    writable: true,
    configurable: true,
  });

  if (typeof globalThis.btoa === "undefined") {
    globalThis.btoa = (str: string) =>
      Buffer.from(str, "binary").toString("base64");
  }
  if (typeof globalThis.atob === "undefined") {
    globalThis.atob = (str: string) =>
      Buffer.from(str, "base64").toString("binary");
  }
});

import {
  buildShortUrl,
  decryptShareUrl,
  encryptShareUrl,
  parseShortUrlParts,
} from "../../shortUrlEncryption";

describe("shortUrlEncryption", () => {
  it("builds short URLs with token in path and secret in fragment", () => {
    const url = buildShortUrl("Abc123XY", "Zz99qq", "https://app.dev.openmates.org");

    expect(url).toBe("https://app.dev.openmates.org/s/Abc123XY#Zz99qq");
    expect(url).not.toContain("#Abc123XY-");
  });

  it("parses path token and fragment secret", () => {
    const parsed = parseShortUrlParts("/s/Abc123XY", "#Zz99qq");

    expect(parsed).toEqual({ token: "Abc123XY", shortKey: "Zz99qq" });
  });

  it("encrypts and decrypts the opaque long share URL", async () => {
    const longShareUrl = "https://app.dev.openmates.org/share/chat/chat-1#key=encrypted-long-key";
    const token = "Abc123XY";
    const shortKey = "Zz99qq";

    const encrypted = await encryptShareUrl(longShareUrl, token, shortKey);

    expect(encrypted).not.toContain("share/chat");
    expect(encrypted).not.toContain("encrypted-long-key");
    await expect(decryptShareUrl(encrypted, token, shortKey)).resolves.toBe(longShareUrl);
  });
});
