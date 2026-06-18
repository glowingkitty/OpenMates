// frontend/packages/ui/src/utils/__tests__/internalLinkValidation.test.ts
//
// Regression coverage for markdown-rendered internal links. The AI may emit
// plausible-looking settings hashes that do not map to any real settings route.
// The renderer should keep those labels visible as text while only valid
// settings destinations become clickable links.

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
      },
    }),
  },
}));

import {
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
});
