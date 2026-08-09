// frontend/packages/ui/src/demo_chats/__tests__/loadDefaultInspirations.test.ts
// Regression coverage for authenticated Daily Inspiration fallback continuity.
// Authenticated users must never see the banner disappear while personalized
// recovery, IndexedDB, or public defaults are still loading. These tests keep
// the loader's synchronous fallback behavior separate from async fetch results.

import { get } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DailyInspiration } from "../../stores/dailyInspirationStore";

vi.mock("svelte-i18n", async () => {
  const { writable } = await import("svelte/store");
  return {
    locale: writable("en"),
    waitLocale: vi.fn(async () => {}),
  };
});

import { getHardcodedInspirationsForSurface } from "../hardcodedInspirations";
import { loadDefaultInspirations } from "../loadDefaultInspirations";
import { authInitialState, authStore } from "../../stores/authStore";
import { dailyInspirationStore } from "../../stores/dailyInspirationStore";

function authenticate(): void {
  authStore.set({ ...authInitialState, isAuthenticated: true, isInitialized: true });
}

function stubDelayedDefaultFetch(data: { inspirations: DailyInspiration[] }): () => void {
  let resolveFetch!: () => void;
  const fetchPromise = new Promise<Response>((resolve) => {
    resolveFetch = () => {
      resolve(
        new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    };
  });
  vi.stubGlobal("fetch", vi.fn(() => fetchPromise));
  return resolveFetch;
}

describe("loadDefaultInspirations", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    dailyInspirationStore.reset();
    authStore.set({ ...authInitialState });
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-continuity
  it("shows authenticated fallback synchronously on authenticated cold boot", async () => {
    authenticate();
    const resolveFetch = stubDelayedDefaultFetch({ inspirations: [] });

    const loading = loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });

    const immediateState = get(dailyInspirationStore);
    expect(immediateState.source).toBe("authenticated-fallback");
    expect(immediateState.inspirations).toHaveLength(10);
    expect(
      immediateState.inspirations.every((inspiration) =>
        inspiration.inspiration_id.startsWith("authenticated-fallback-"),
      ),
    ).toBe(true);

    resolveFetch();
    await loading;
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-continuity
  it("replaces guest onboarding with authenticated fallback without an empty emission", async () => {
    dailyInspirationStore.restoreGuestOnboarding(
      getHardcodedInspirationsForSurface("en", "chats"),
    );
    authenticate();
    const emittedLengths: number[] = [];
    const unsubscribe = dailyInspirationStore.subscribe((state) => {
      emittedLengths.push(state.inspirations.length);
    });
    const resolveFetch = stubDelayedDefaultFetch({ inspirations: [] });

    const loading = loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });

    const immediateState = get(dailyInspirationStore);
    expect(immediateState.source).toBe("authenticated-fallback");
    expect(immediateState.inspirations).toHaveLength(10);
    expect(emittedLengths).not.toContain(0);

    resolveFetch();
    await loading;
    unsubscribe();
  });
});
