// frontend/packages/ui/src/stores/__tests__/dailyInspirationStore.test.ts
// Regression coverage for authenticated daily inspiration carousel stability.
// Duplicate WebSocket deliveries can arrive while the user manually navigates
// the banner; the store must preserve the visible index for the same ordered
// inspiration set so arrow clicks and touch swipes do not appear to be ignored.

import { get } from "svelte/store";
import { afterEach, describe, expect, it } from "vitest";
import {
  dailyInspirationStore,
  type DailyInspiration,
} from "../dailyInspirationStore";

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
  });
});
