// frontend/packages/ui/src/stores/__tests__/learningModeStore.test.ts
//
// Regression coverage for Learning Mode store load state.
// A failed authenticated status load must not leave the store in a state that
// lets settings effects retry forever and flood users with notifications.

import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { learningMode } from "../learningModeStore";

vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
}));

describe("learningModeStore", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    learningMode.reset();
  });

  it("marks failed authenticated loads as terminal to prevent settings retry loops", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "Invalid or expired token" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      )
    );

    await expect(learningMode.load()).rejects.toThrow("Invalid or expired token");

    expect(get(learningMode)).toMatchObject({
      loaded: true,
      loading: false,
      source: "account",
    });
  });
});
