/**
 * Collected randomness and compatibility tests for encrypted short URLs.
 *
 * Legacy six-character fragments remain parseable while new fragments carry
 * at least 128 unbiased bits. Controlled byte streams prove rejection sampling
 * without relying on statistical tests.
 */

import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { generateShortUrlParts, parseShortUrlParts } from "../shortUrlEncryption";

const originalCrypto = globalThis.crypto;
const BASE62_LENGTH = 62;

beforeEach(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
});

afterEach(() => {
  Object.defineProperty(globalThis, "crypto", { value: originalCrypto, configurable: true });
});

describe("short URL randomness", () => {
  it("issues an eight-character token and a 128-bit fragment secret", () => {
    const parts = generateShortUrlParts();

    expect(parts.token).toMatch(/^[A-Za-z0-9]{8}$/);
    expect(parts.shortKey).toMatch(/^[A-Za-z0-9]{22}$/);
    expect(parts.shortKey.length * Math.log2(BASE62_LENGTH)).toBeGreaterThanOrEqual(128);
  });

  it("rejects out-of-range bytes instead of applying modulo bias", () => {
    let calls = 0;
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: {
        getRandomValues<T extends ArrayBufferView>(values: T): T {
          new Uint8Array(values.buffer, values.byteOffset, values.byteLength).fill(calls++ % 2 === 0 ? 255 : 0);
          return values;
        },
      },
    });

    expect(generateShortUrlParts()).toEqual({ token: "AAAAAAAA", shortKey: "A".repeat(22) });
  });

  it("fails closed when secure randomness is unavailable", () => {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: { getRandomValues: () => { throw new Error("rng unavailable"); } },
    });

    expect(() => generateShortUrlParts()).toThrow("rng unavailable");
  });

  it("parses both legacy and new fragment lengths", () => {
    expect(parseShortUrlParts("/s/Ab12Cd34", "#0Oab12")).toEqual({
      token: "Ab12Cd34",
      shortKey: "0Oab12",
    });
    expect(parseShortUrlParts("/s/Ab12Cd34", `#${"A".repeat(22)}`)).toEqual({
      token: "Ab12Cd34",
      shortKey: "A".repeat(22),
    });
  });
});
