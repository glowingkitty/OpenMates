// frontend/packages/ui/src/utils/__tests__/internalLinkValidation.test.ts
//
// Regression coverage for markdown-rendered internal links. The AI may emit
// plausible-looking settings hashes that do not map to any real settings route.
// Invalid settings destinations degrade to safe #message prefill links while
// only valid settings destinations become clickable settings links.

import { describe, expect, it, vi } from "vitest";

vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: {
    getState: () => ({
      apps: {
        openmates: {
          id: "openmates",
          skills: [{ id: "share-usecase" }],
          focus_modes: [],
          settings_and_memories: [],
        },
        maps: {
          id: "maps",
          skills: [{ id: "search" }],
          focus_modes: [],
          settings_and_memories: [
            {
              id: "favorite_places",
              schema_definition: {
                properties: {
                  name: { type: "string" },
                  address: { type: "string" },
                },
              },
            },
          ],
        },
      },
    }),
  },
}));

import {
  getRenderableInternalHref,
  isRenderableInternalHref,
  normalizeSettingsDeepLinkPath,
} from "../internalLinkValidation";

describe("internal link validation", () => {
  it("rejects hallucinated app settings routes", () => {
    expect(
      isRenderableInternalHref(
        "/#settings/apps/openmates/settings_memories/billing",
      ),
    ).toBe(false);
  });

  it("accepts real settings routes after normalization", () => {
    expect(normalizeSettingsDeepLinkPath("/#settings/billing/referral-code")).toBe(
      "billing/referral-code",
    );
    expect(isRenderableInternalHref("/#settings/billing/referral-code")).toBe(true);
  });

  it("keeps chat deep links renderable because existence is runtime data", () => {
    expect(isRenderableInternalHref("/#chat-id=abc123")).toBe(true);
  });

  it("keeps message prefill links renderable as internal composer actions", () => {
    expect(isRenderableInternalHref("#message=Save%20place")).toBe(true);
    expect(getRenderableInternalHref("/#message=Save%20place")).toBe("#message=Save%20place");
  });

  it("accepts public memories aliases for app settings and canonicalizes them", () => {
    const href = "/#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kottbusser%20Tor%22%7D";

    expect(normalizeSettingsDeepLinkPath(href)).toBe(
      "apps/maps/settings_memories/favorite_places/create",
    );
    expect(getRenderableInternalHref(href, "Save Kottbusser Tor")).toBe(
      "#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kottbusser%20Tor%22%7D",
    );
  });

  it("preserves valid public all-apps memory filters", () => {
    expect(getRenderableInternalHref("/#settings/apps/all/settings_memories", "Memories")).toBe(
      "#settings/apps/all/memories",
    );
  });

  it("ignores unrelated query params after a valid encoded prefill", () => {
    expect(
      getRenderableInternalHref(
        "/#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kotti%22%7D&source=chat",
        "Save place",
      ),
    ).toBe(
      "#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kotti%22%7D",
    );
  });

  it("falls back to a message prefill link for nonexistent memory categories", () => {
    expect(
      getRenderableInternalHref(
        "/#settings/apps/maps/memories/goals/create?prefill=%7B%22name%22%3A%22Explore%22%7D",
        "Set a goal",
      ),
    ).toBe("#message=Set%20a%20goal");
  });

  it("falls back when prefill fields are not in the category schema", () => {
    expect(
      getRenderableInternalHref(
        "/#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22city%22%3A%22Berlin%22%7D",
        "Save place",
      ),
    ).toBe("#message=Save%20place");
  });
});
