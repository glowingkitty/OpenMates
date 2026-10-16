// frontend/packages/ui/src/demo_chats/__tests__/loadDefaultInspirations.test.ts
// Regression coverage for authenticated Daily Inspiration fallback continuity.
// Authenticated users must never see the banner disappear while personalized
// recovery, IndexedDB, or public defaults are still loading. These tests keep
// the loader's synchronous fallback behavior separate from async fetch results.

import { get } from "svelte/store";
import { locale } from "svelte-i18n";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DailyInspiration } from "../../stores/dailyInspirationStore";
import { SUPPORTED_LOCALES } from "../../i18n/languages";

vi.mock("svelte-i18n", async () => {
  const { writable } = await import("svelte/store");
  return {
    _: writable((key: string) => key),
    addMessages: vi.fn(),
    getLocaleFromNavigator: vi.fn(() => "en"),
    init: vi.fn(),
    locale: writable("en"),
    register: vi.fn(),
    waitLocale: vi.fn(async () => {}),
  };
});

vi.mock("../../stores/authStore", async () => {
  const { writable } = await import("svelte/store");
  const authInitialState = { isAuthenticated: false, isInitialized: true };
  return { authInitialState, authStore: writable({ ...authInitialState }) };
});

import { getAuthenticatedFallbackInspirations, getHardcodedInspirationsForSurface } from "../hardcodedInspirations";
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
    locale.set("en");
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

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
  it("shows ordinary guest fallback immediately and replaces it with public defaults", async () => {
    const publicInspirations = getHardcodedInspirationsForSurface("en", "chats").slice(0, 3);
    const resolveFetch = stubDelayedDefaultFetch({ inspirations: publicInspirations });

    const loading = loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });
    const immediateState = get(dailyInspirationStore);
    expect(immediateState.source).toBe("guest-onboarding");
    expect(immediateState.inspirations).toHaveLength(10);
    expect(immediateState.inspirations.some((inspiration) =>
      inspiration.inspiration_id === "guest-fallback-events",
    )).toBe(true);
    expect(immediateState.inspirations.filter((inspiration) =>
      inspiration.inspiration_id !== "guest-fallback-events",
    ).every((inspiration) => inspiration.inspiration_id.startsWith("authenticated-fallback-"))).toBe(true);

    resolveFetch();
    await loading;
    const publicState = get(dailyInspirationStore);
    expect(publicState.source).toBe("guest-onboarding");
    expect(publicState.inspirations.map((inspiration) => inspiration.inspiration_id)).toEqual(
      publicInspirations.map((inspiration) => inspiration.inspiration_id),
    );
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("does not replace the guest fallback with promotional public records", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      inspirations: [{ inspiration_id: "openmates-intro", feature: { feature_id: "openmates-intro" } }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });

    const state = get(dailyInspirationStore);
    expect(state.inspirations).toHaveLength(10);
    expect(state.inspirations.some((inspiration) => inspiration.inspiration_id === "openmates-intro")).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
  it("keeps offline German guest fallback localized when public defaults fail", async () => {
    locale.set("de");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));

    await loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("guest-onboarding");
    expect(state.inspirations).toHaveLength(10);
    expect(state.inspirations.map((item) => item.content_type)).toEqual([
      "video", "video", "video", "wiki", "wiki", "wiki",
      "feature", "feature", "feature", "feature",
    ]);
    expect(state.inspirations[0].phrase).toBe(
      "Warum erschafft dein Gehirn ganze Welten, während du schläfst?",
    );
    expect(state.inspirations[0].assistant_response).toContain("REM-Schlaf");
    const wiki = state.inspirations[3];
    expect(wiki.phrase).toBe("Ein antikes Schiffswrack barg eine Maschine, die den Himmel vorhersagte.");
    expect(wiki.wiki?.title).toBe("Der Mechanismus von Antikythera");
    expect(wiki.wiki?.description).toContain("griechisches");
    expect(wiki.assistant_response).toContain("Bronzezahnräder");
    const feature = state.inspirations[6];
    expect(feature.phrase).toContain("Veranstaltungen in deiner Nähe");
    expect(feature.feature?.title).toBe("Lokale Veranstaltungen finden");
    expect(feature.feature?.description).toContain("Kursen");
    expect(feature.assistant_response).toContain("Events-Suche");
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
  it("keeps ten public guest cards while retaining export in the authenticated fallback", () => {
    const guest = getHardcodedInspirationsForSurface("en", "chats");
    const authenticated = getAuthenticatedFallbackInspirations("en");
    expect(guest).toHaveLength(10);
    expect(guest.map((card) => card.content_type)).toEqual([
      "video", "video", "video", "wiki", "wiki", "wiki",
      "feature", "feature", "feature", "feature",
    ]);
    expect(guest.every((card) => card.feature?.requires_authentication !== true)).toBe(true);
    expect(guest[6].inspiration_id).toBe("guest-fallback-events");
    expect(guest[6].feature).toMatchObject({
      feature_id: "events-search",
      settings_path: "apps/events/skill/search",
      requires_authentication: false,
    });
    expect(guest.filter((card) => card.inspiration_id !== "guest-fallback-events").map((card) => card.inspiration_id))
      .toEqual(authenticated.filter((card) => card.inspiration_id !== "authenticated-fallback-export")
        .map((card) => card.inspiration_id));
    expect(authenticated[6].feature).toMatchObject({
      feature_id: "export-data",
      requires_authentication: true,
    });
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("keeps the ten-card guest mix and localized copy in every supported locale", () => {
    const english = getHardcodedInspirationsForSurface("en", "chats");
    for (const lang of SUPPORTED_LOCALES) {
      const cards = getHardcodedInspirationsForSurface(lang, "chats");
      expect(cards.map((card) => card.inspiration_id)).toEqual(
        english.map((card) => card.inspiration_id),
      );
      expect(cards).toHaveLength(10);
      if (lang !== "en") {
        for (let index = 3; index < 10; index += 1) {
          expect(cards[index].phrase, `${lang} card ${index}`).not.toBe(english[index].phrase);
          expect(cards[index].assistant_response, `${lang} card ${index}`).toBeTruthy();
        }
      }
    }
    expect(getHardcodedInspirationsForSurface("xx", "chats")[3].phrase).toBe(english[3].phrase);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.authenticated-continuity
  it("does not let a late guest public response overwrite authenticated recovery", async () => {
    const resolveFetch = stubDelayedDefaultFetch({
      inspirations: getHardcodedInspirationsForSurface("en", "chats").slice(0, 3),
    });
    const loading = loadDefaultInspirations({ allowIndexedDB: false, surface: "chats" });

    authenticate();
    dailyInspirationStore.setSurfaceInspirations(
      "chats",
      getHardcodedInspirationsForSurface("en", "chats"),
      { source: "authenticated-fallback" },
    );
    resolveFetch();
    await loading;

    expect(get(dailyInspirationStore).source).toBe("authenticated-fallback");
    expect(get(dailyInspirationStore).inspirations).toHaveLength(10);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-continuity
  it("replaces guest daily content with authenticated fallback without an empty emission", async () => {
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
