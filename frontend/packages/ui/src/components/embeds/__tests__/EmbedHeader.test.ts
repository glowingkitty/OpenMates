// frontend/packages/ui/src/components/embeds/__tests__/EmbedHeader.test.ts
// Unit tests for EmbedHeader swipe navigation behavior.
// Covers the same decision path the Svelte component uses for mobile touch
// navigation, without mounting the component in Vitest's server-resolved
// Svelte environment.
// Architecture: docs/architecture/frontend/accessibility.md

import { describe, expect, it } from "vitest";
import { resolveHeaderSwipeNavigation } from "../../headerSwipeNavigation";

describe("resolveHeaderSwipeNavigation", () => {
  it("returns previous for an available left swipe", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: -80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: true,
      }),
    ).toBe("previous");
  });

  it("returns next for an available right swipe", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: 80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: true,
      }),
    ).toBe("next");
  });

  it("ignores unavailable directions", () => {
    expect(
      resolveHeaderSwipeNavigation({
        deltaX: -80,
        deltaY: 4,
        hasPrevious: false,
        hasNext: true,
      }),
    ).toBeNull();

    expect(
      resolveHeaderSwipeNavigation({
        deltaX: 80,
        deltaY: 4,
        hasPrevious: true,
        hasNext: false,
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
