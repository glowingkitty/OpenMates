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
          focus_modes: []
        },
        maps: {
          id: "maps",
          skills: [{ id: "search" }],
          focus_modes: [],
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
  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("rejects hallucinated app settings routes", () => {
    expect(
      isRenderableInternalHref(
        "/#settings/apps/openmates/settings_memories/billing",
      ),
    ).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("accepts real settings routes after normalization", () => {
    expect(normalizeSettingsDeepLinkPath("/#settings/billing/referral-code")).toBe(
      "billing/referral-code",
    );
    expect(isRenderableInternalHref("/#settings/billing/referral-code")).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("keeps chat deep links renderable because existence is runtime data", () => {
    expect(isRenderableInternalHref("/#chat-id=abc123")).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("keeps message prefill links renderable as internal composer actions", () => {
    expect(isRenderableInternalHref("#message=Save%20place")).toBe(true);
    expect(getRenderableInternalHref("/#message=Save%20place")).toBe("#message=Save%20place");
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("falls back to a message prefill link for removed typed memory routes", () => {
    const href = "/#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kottbusser%20Tor%22%7D";

    expect(getRenderableInternalHref(href, "Save Kottbusser Tor")).toBe("#message=Save%20Kottbusser%20Tor");
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.catalog.no-typed-types
  it("preserves valid public all-apps memory filters", () => {
    expect(getRenderableInternalHref("/#settings/apps/all/settings_memories", "Memories")).toBe(
      "#settings/apps/all/memories",
    );
  });
});
