// frontend/packages/ui/src/__tests__/test-setup.test.ts
// Infrastructure coverage for shared Vitest environment shims.
//
// These tests verify behavior provided by `src/test-setup.ts` after Vitest
// loads it globally. They intentionally do not prove product contracts.
// contract-test-file: infrastructure

import { afterEach, describe, expect, it, vi } from "vitest";
import { blockedUnitFetch, installUnitFetchGuard } from "../test-mocks/unit-fetch-guard";

describe("test setup shims", () => {
  it("provides Blob.arrayBuffer for generated file assertions", async () => {
    const blob = new Blob(["OpenMates"]);
    const bytes = new Uint8Array(await blob.arrayBuffer());

    expect(Array.from(bytes)).toEqual([79, 112, 101, 110, 77, 97, 116, 101, 115]);
  });
});


describe("unit fetch isolation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("replaces the original transport without calling it", async () => {
    const original = vi.fn();
    const target = { fetch: original as typeof fetch };
    installUnitFetchGuard(target);
    await expect(target.fetch("https://unit.invalid/")).rejects.toThrow("Unmocked fetch blocked");
    expect(original).not.toHaveBeenCalled();
  });

  it("blocks global and window requests by default", async () => {
    expect(globalThis.fetch).toBe(blockedUnitFetch);
    expect(window.fetch).toBe(blockedUnitFetch);
    await expect(fetch("https://unit.invalid/")).rejects.toThrow("Unmocked fetch blocked");
    await expect(window.fetch("/unit-only")).rejects.toThrow("Unmocked fetch blocked");
  });

  it("restores the guard after stubGlobal cleanup and allows explicit request mocks", async () => {
    const response = new Response("mock response");
    const mock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", mock);
    expect(await fetch("https://unit.invalid/")).toBe(response);
    expect(mock).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
    expect(fetch).toBe(blockedUnitFetch);
    await expect(fetch("https://unit.invalid/")).rejects.toThrow("Unmocked fetch blocked");
  });

  it("restores the guard after spies and blocks asynchronous teardown requests", async () => {
    const response = new Response("mock response");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    expect(await fetch("/mocked-request")).toBe(response);
    // Model background work that runs after a test retires its transport mock.
    const pending = Promise.resolve().then(() => fetch("https://unit.invalid/after-cleanup"));
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    await expect(pending).rejects.toThrow("Unmocked fetch blocked");
    expect(fetch).toBe(blockedUnitFetch);
  });
});
