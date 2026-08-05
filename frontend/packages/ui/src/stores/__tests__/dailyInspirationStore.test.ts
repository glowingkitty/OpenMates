// @vitest-environment jsdom
// frontend/packages/ui/src/stores/__tests__/dailyInspirationStore.test.ts
// Regression coverage for authenticated daily inspiration carousel stability.
// Duplicate WebSocket deliveries can arrive while the user manually navigates
// the banner; the store must preserve the visible index for the same ordered
// inspiration set so arrow clicks and touch swipes do not appear to be ignored.

import { get } from "svelte/store";
import { afterEach, describe, expect, it } from "vitest";
import {
  dailyInspirationStore,
  hasCompleteAuthenticatedDailySet,
  type DailyInspiration,
} from "../dailyInspirationStore";
import { getAuthenticatedFallbackInspirations } from "../../demo_chats/hardcodedInspirations";
import { loadGuestOnboardingInspirations } from "../../demo_chats/loadDefaultInspirations";

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
  });

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

  it("forces the exact guest onboarding set after authenticated data races with logout", () => {
    dailyInspirationStore.setInspirations(INSPIRATIONS, {
      personalized: true,
      source: "personalized",
    });

    loadGuestOnboardingInspirations();

    const state = get(dailyInspirationStore);
    expect(state.source).toBe("guest-onboarding");
    expect(state.inspirations.map((item) => item.inspiration_id)).toEqual(
      GUEST_ONBOARDING_IDS,
    );
  });

  it("preserves the guest source when local interest ranking rewrites its order", () => {
    dailyInspirationStore.setSurfaceInspirations("chats", INSPIRATIONS, {
      source: "guest-onboarding",
    });

    dailyInspirationStore.setSurfaceInspirations("chats", [...INSPIRATIONS].reverse());

    expect(get(dailyInspirationStore).source).toBe("guest-onboarding");
  });

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
});
