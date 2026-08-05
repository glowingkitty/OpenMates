// frontend/packages/ui/src/utils/__tests__/contentCache.test.ts
// Verifies exact semantic keys, immutable values, TTL, and access-order eviction.
// Streaming snapshots commonly share long prefixes and must never cross-resolve.
// The canonical streaming path must also be able to bypass this final-content cache.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContentCache } from "../contentCache";

describe("ContentCache", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("distinguishes complete keys that share the first 200 characters", () => {
    const cache = new ContentCache({ maxSize: 100, maxAgeMs: 300_000 });
    const prefix = "x".repeat(200);
    cache.set(`${prefix}:one`, { type: "doc", content: [{ type: "text", text: "one" }] });
    cache.set(`${prefix}:two`, { type: "doc", content: [{ type: "text", text: "two" }] });

    expect(cache.get(`${prefix}:one`)?.content[0].text).toBe("one");
    expect(cache.get(`${prefix}:two`)?.content[0].text).toBe("two");
  });

  it("returns mutation-isolated values", () => {
    const cache = new ContentCache();
    cache.set("message", { type: "doc", content: [{ type: "text", text: "safe" }] });
    const first = cache.get("message");
    first.content[0].text = "mutated";

    expect(cache.get("message")?.content[0].text).toBe("safe");
  });

  it("expires entries and evicts the least recently accessed key", () => {
    const cache = new ContentCache({ maxSize: 2, maxAgeMs: 100 });
    cache.set("a", { value: "a" });
    cache.set("b", { value: "b" });
    expect(cache.get("a")?.value).toBe("a");
    cache.set("c", { value: "c" });

    expect(cache.get("b")).toBeNull();
    expect(cache.get("a")?.value).toBe("a");
    vi.advanceTimersByTime(101);
    expect(cache.get("a")).toBeNull();
    expect(cache.get("c")).toBeNull();
  });
});
