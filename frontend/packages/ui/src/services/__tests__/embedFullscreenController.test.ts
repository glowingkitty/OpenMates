// frontend/packages/ui/src/services/__tests__/embedFullscreenController.test.ts
//
// Unit coverage for the unified embed fullscreen controller.
// These tests lock the product contract that direct child links stay direct,
// while parent-origin child navigation records a return point.
// See docs/specs/unified-embed-fullscreen-routing/spec.yml.

import { beforeEach, describe, expect, it, vi } from "vitest";

const activeEmbedCalls: Array<{ embedId: string | null; chatId?: string | null }> = [];
let storedResolution = {
  targetEmbedId: "stored-target",
  focusChildEmbedId: undefined as string | undefined,
};

vi.mock("../../stores/activeEmbedStore", () => ({
  activeEmbedStore: {
    setActiveEmbed: (embedId: string | null, chatId?: string | null) => {
      activeEmbedCalls.push({ embedId, chatId });
    },
    clearActiveEmbed: () => {
      activeEmbedCalls.push({ embedId: null });
    },
  },
}));

vi.mock("../embedStore", () => ({
  embedStore: {
    resolveFullscreenTarget: vi.fn(async () => storedResolution),
  },
}));

import {
  clearFullscreenRoute,
  resolveEmbedFullscreenTarget,
  restorePreviousFullscreenRoute,
  setChildFullscreenRouteFromParent,
  setCanonicalFullscreenRoute,
} from "../embedFullscreenController";

describe("embedFullscreenController", () => {
  beforeEach(() => {
    activeEmbedCalls.length = 0;
    storedResolution = {
      targetEmbedId: "stored-target",
      focusChildEmbedId: undefined,
    };
    clearFullscreenRoute();
    activeEmbedCalls.length = 0;
  });

  it("keeps registered Models3D children as direct fullscreen targets", async () => {
    const target = await resolveEmbedFullscreenTarget("embed:model-child-1", {
      embedType: "model_result",
    });

    expect(target).toEqual({ targetEmbedId: "model-child-1" });
  });

  it("keeps registered Weather children as direct fullscreen targets", async () => {
    const target = await resolveEmbedFullscreenTarget("weather-child-1", {
      embedType: "weather_day",
    });

    expect(target).toEqual({ targetEmbedId: "weather-child-1" });
  });

  it("falls back to stored parent routing for non-direct child embeds", async () => {
    storedResolution = {
      targetEmbedId: "parent-search-1",
      focusChildEmbedId: "child-result-1",
    };

    const target = await resolveEmbedFullscreenTarget("child-result-1");

    expect(target).toEqual({
      targetEmbedId: "parent-search-1",
      focusChildEmbedId: "child-result-1",
    });
  });

  it("records parent return state for parent-origin child navigation", () => {
    setCanonicalFullscreenRoute("parent-search-1", { chatId: "chat-1" });
    setChildFullscreenRouteFromParent("child-result-1", "parent-search-1", "chat-1");

    expect(activeEmbedCalls).toEqual([
      { embedId: "parent-search-1", chatId: "chat-1" },
      { embedId: "child-result-1", chatId: "chat-1" },
    ]);

    const restored = restorePreviousFullscreenRoute(null, "chat-1");

    expect(restored).toEqual({ embedId: "parent-search-1", chatId: "chat-1" });
    expect(activeEmbedCalls[activeEmbedCalls.length - 1]).toEqual({
      embedId: "parent-search-1",
      chatId: "chat-1",
    });
  });
});
