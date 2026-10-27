// frontend/packages/ui/src/stores/__tests__/dailyInspirationStore.test.ts
// Regression coverage for authenticated daily inspiration carousel stability.
// Duplicate WebSocket deliveries can arrive while the user manually navigates
// the banner; the store must preserve the visible index for the same ordered
// inspiration set so arrow clicks and touch swipes do not appear to be ignored.

import { get } from "svelte/store";
import { locale } from "svelte-i18n";
import { afterEach, describe, expect, it } from "vitest";
import {
  dailyInspirationStore,
  hasCompleteAuthenticatedDailySet,
  type DailyInspiration,
} from "../dailyInspirationStore";
import {
  getAuthenticatedFallbackInspirations,
  getHardcodedInspirationsForSurface,
} from "../../demo_chats/hardcodedInspirations";

const GUEST_ONBOARDING_IDS = [
  "openmates-intro",
  "openmates-actionable-events",
  "openmates-privacy-safety",
  "openmates-mates-focus",
  "openmates-provider-cross-platform",
  "openmates-signup-cta",
];

const INSPIRATIONS: DailyInspiration[] = [
  {
    inspiration_id: "daily-1",
    phrase: "First inspiration",
    title: "First",
    category: "science",
    content_type: "text",
    video: null,
    generated_at: 1,
  },
  {
    inspiration_id: "daily-2",
    phrase: "Second inspiration",
    title: "Second",
    category: "biology",
    content_type: "text",
    video: null,
    generated_at: 2,
  },
  {
    inspiration_id: "daily-3",
    phrase: "Third inspiration",
    title: "Third",
    category: "technology",
    content_type: "text",
    video: null,
    generated_at: 3,
  },
];

describe("dailyInspirationStore", () => {
  afterEach(() => {
    dailyInspirationStore.reset();
    locale.set("en");
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.personalized-priority,daily-inspiration.opened-state
  it("preserves manual carousel index for duplicate authenticated deliveries", () => {
    dailyInspirationStore.setInspirations(INSPIRATIONS, { personalized: true });
    dailyInspirationStore.goTo(1);
    dailyInspirationStore.setEmbedId("daily-2", "embed-2");
    dailyInspirationStore.markOpened("daily-2", "chat-2", {
      preserveCurrentIndex: true,
    });

    dailyInspirationStore.setInspirations(INSPIRATIONS, { personalized: true });

    const state = get(dailyInspirationStore);
    expect(state.currentIndex).toBe(1);
    expect(state.inspirations[1]).toMatchObject({
      embed_id: "embed-2",
      is_opened: true,
      opened_chat_id: "chat-2",
    });
    expect(state.source).toBe("personalized");
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-continuity
  it("replaces guest onboarding with an authenticated public source", () => {
    dailyInspirationStore.setSurfaceInspirations(
      "chats",
      [{ ...INSPIRATIONS[0], inspiration_id: "openmates-signup-cta" }],
      { source: "guest-onboarding" },
    );

    dailyInspirationStore.setSurfaceInspirations("chats", INSPIRATIONS, {
      source: "public-daily",
    });

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("public-daily");
    expect(state.inspirations.map((item) => item.inspiration_id)).not.toContain(
      "openmates-signup-cta",
    );
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.personalized-priority
  it("does not let guest onboarding overwrite personalized records", () => {
    dailyInspirationStore.setInspirations(INSPIRATIONS, {
      personalized: true,
      source: "personalized",
    });

    dailyInspirationStore.setSurfaceInspirations(
      "chats",
      [{ ...INSPIRATIONS[0], inspiration_id: "openmates-signup-cta" }],
      { source: "guest-onboarding" },
    );

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("personalized");
    expect(state.inspirations).toHaveLength(3);
    expect(state.inspirations.map((item) => item.inspiration_id)).not.toContain(
      "openmates-signup-cta",
    );
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("restores the public-safe ten-card guest fallback after authenticated data races with logout", () => {
    dailyInspirationStore.setInspirations(INSPIRATIONS, {
      personalized: true,
      source: "personalized",
    });

    dailyInspirationStore.restoreGuestOnboarding(
      getHardcodedInspirationsForSurface("en", "chats"),
    );

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("guest-onboarding");
    expect(state.inspirations).toHaveLength(10);
    expect(state.inspirations.every((item) => !GUEST_ONBOARDING_IDS.includes(item.feature?.feature_id ?? ""))).toBe(true);
    expect(state.inspirations.filter((item) => item.feature).every((item) => item.feature?.requires_authentication === false)).toBe(true);
    expect(state.inspirations.map((item) => item.inspiration_id)).toEqual(
      getHardcodedInspirationsForSurface("en", "chats").map((item) => item.inspiration_id),
    );
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("preserves the guest source when local interest ranking rewrites its order", () => {
    dailyInspirationStore.setSurfaceInspirations("chats", INSPIRATIONS, {
      source: "guest-onboarding",
    });

    dailyInspirationStore.setSurfaceInspirations("chats", [...INSPIRATIONS].reverse());

    expect(get(dailyInspirationStore).source).toBe("guest-onboarding");
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-fallback-content
  it("provides an authenticated-only 3/3/4 fallback", () => {
    const fallback = getAuthenticatedFallbackInspirations("en");
    const counts = fallback.reduce<Record<string, number>>((result, inspiration) => {
      result[inspiration.content_type] = (result[inspiration.content_type] ?? 0) + 1;
      return result;
    }, {});

    expect(counts).toEqual({ video: 3, wiki: 3, feature: 4 });
    expect(fallback.map((item) => item.inspiration_id)).not.toContain("openmates-signup-cta");
    expect(fallback.filter((item) => item.content_type === "feature").every((item) => item.feature?.settings_path)).toBe(true);
    expect(hasCompleteAuthenticatedDailySet(fallback)).toBe(true);
    expect(hasCompleteAuthenticatedDailySet(fallback.slice(1))).toBe(false);
    expect(
      hasCompleteAuthenticatedDailySet(
        fallback.map((item) => ({ ...item, content_type: "feature" })),
      ),
    ).toBe(false);
    expect(
      hasCompleteAuthenticatedDailySet([
        { ...fallback[0], feature: { ...fallback[6].feature!, feature_id: "openmates-actionable-events" } },
        ...fallback.slice(1),
      ]),
    ).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.authenticated-continuity,daily-inspiration.personalized-priority
  it("allows authenticated fallback to replace incomplete personalized records", () => {
    dailyInspirationStore.setInspirations(INSPIRATIONS, {
      personalized: true,
      source: "personalized",
    });

    dailyInspirationStore.setSurfaceInspirations(
      "chats",
      getAuthenticatedFallbackInspirations("en"),
      { source: "authenticated-fallback" },
    );

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("authenticated-fallback");
    expect(state.isPersonalized).toBe(false);
    expect(hasCompleteAuthenticatedDailySet(state.inspirations)).toBe(true);
  });
});

// contract-test: supporting surface=gui.web assertions=language-preferences.content-language,daily-inspiration.opened-state
describe("inspiration language recovery", () => {
  afterEach(() => { dailyInspirationStore.reset(); locale.set("en"); });

  it("keeps German fallback when stale English personalized sync arrives", () => {
    locale.set("de");
    const german = getAuthenticatedFallbackInspirations("de");
    dailyInspirationStore.setInspirations(german, { source: "authenticated-fallback" });
    dailyInspirationStore.setInspirations(getAuthenticatedFallbackInspirations("en"), { personalized: true });
    expect(get(dailyInspirationStore).inspirations).toEqual(german);
    expect(get(dailyInspirationStore).isPersonalized).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=language-preferences.content-language,daily-inspiration.opened-state
  it("restores matching language with existing chat ownership and opened state", () => {
    locale.set("de");
    const german = getAuthenticatedFallbackInspirations("de");
    german[0] = { ...german[0], is_opened: true, opened_chat_id: "saved-chat" };
    dailyInspirationStore.setInspirations(german, { personalized: true });
    dailyInspirationStore.setInspirations(german.map((item) => ({ ...item, is_opened: false, opened_chat_id: null })), { personalized: true });
    expect(get(dailyInspirationStore).inspirations[0]).toMatchObject({ language: "de", is_opened: true, opened_chat_id: "saved-chat" });
  });
});
