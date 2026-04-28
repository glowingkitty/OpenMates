// frontend/packages/ui/src/components/__tests__/headerSwipeNavigation.test.ts
// Unit tests for the shared header swipe navigation helper.
// Verifies horizontal swipe direction, availability gating, and vertical-scroll
// rejection for chat and embed header consumers.
// Kept separate from component rendering so the behavior is testable in Vitest's
// current Svelte server-resolution environment.

import { describe, expect, it } from "vitest";
import { resolveHeaderSwipeNavigation } from "../headerSwipeNavigation";

describe("resolveHeaderSwipeNavigation", () => {
  it("returns next for an available right-to-left swipe", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: -80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: true,
      }),
    ).toBe("next");
  });

  it("returns previous for an available left-to-right swipe", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: 80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: true,
      }),
    ).toBe("previous");
  });

  it("ignores unavailable directions", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: -80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: false,
      }),
    ).toBeNull();

    expect(
      resolveHeaderSwipeNavigation({
        deltaX: 80,
        deltaY: 4,
        hasPrevious: false,
        hasNext: true,
      }),
    ).toBeNull();
  });

  it("ignores vertical scroll gestures", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: 20,
        deltaY: 80,
        hasPrevious: true,
        hasNext: true,
      }),
    ).toBeNull();
  });
});
