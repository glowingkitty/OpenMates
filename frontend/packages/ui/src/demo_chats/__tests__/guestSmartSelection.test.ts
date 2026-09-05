// frontend/packages/ui/src/demo_chats/__tests__/guestSmartSelection.test.ts
// Regression coverage for the guest interest smart-selection contract.
// These tests guard the deterministic, local-only ranking rules before the
// Svelte welcome screen consumes them.

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  INTEREST_TAGS,
  normalizeInterestTagIds,
  type InterestTagId,
} from "../interestTags";
import { ALL_EXAMPLE_CHATS } from "../exampleChatData";
import {
  rankDailyInspirationsByInterests,
  rankExampleChatIdsByInterests,
  rankIntroChatIdsByInterests,
  rankInterestTagsForSelection,
  rankSuggestionKeysByInterests,
} from "../guestSmartSelection";

describe("guestSmartSelection", () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("defines the approved 21-work and 13-personal tag taxonomy", () => {
    expect(INTEREST_TAGS).toHaveLength(34);
    expect(INTEREST_TAGS.filter((tag) => tag.audience === "work")).toHaveLength(21);
    expect(INTEREST_TAGS.filter((tag) => tag.audience === "personal")).toHaveLength(13);
    expect(INTEREST_TAGS.slice(0, 10).map((tag) => tag.id)).toEqual([
      "marketing",
      "software_development",
      "finance_bookkeeping",
      "ui_ux_design",
      "business_planning",
      "content_creation",
      "project_management",
      "admin_operations",
      "find_local_events",
      "plan_trips",
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("maps every interest to registered public example chats", () => {
    const registeredIds = new Set(ALL_EXAMPLE_CHATS.map((chat) => chat.chat_id));
    const unknownMappings = INTEREST_TAGS.flatMap((tag) =>
      tag.exampleChats
        .filter((chatId) => !registeredIds.has(chatId))
        .map((chatId) => `${tag.id}:${chatId}`),
    );

    expect(unknownMappings).toEqual([]);
    expect(INTEREST_TAGS.filter((tag) => tag.exampleChats.length === 0)).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("migrates legacy stored tag IDs to canonical tags", () => {
    expect(normalizeInterestTagIds([
      "marketing_sales",
      "finance",
      "design",
      "find_events",
      "marketing_sales",
    ])).toEqual([
      "marketing",
      "sales",
      "finance_bookkeeping",
      "personal_finances",
      "ui_ux_design",
      "branding_images",
      "find_local_events",
      "events_networking",
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it("uses interest translation keys for every guest-selectable tag", () => {
    const source = readFileSync(
      new URL("../../i18n/sources/chat/interests.yml", import.meta.url),
      "utf-8",
    );

    expect(
      INTEREST_TAGS.filter((tag) => !tag.labelKey.startsWith("chat.interests."))
        .map((tag) => `${tag.id}:${tag.labelKey}`),
    ).toEqual([]);
    expect(
      INTEREST_TAGS.filter((tag) => {
        const sourceKey = tag.labelKey.replace("chat.interests.", "");
        return !source.includes(`${sourceKey}:`);
      }).map((tag) => `${tag.id}:${tag.labelKey}`),
    ).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("keeps selected tags first and moves related tags next without hiding unrelated tags", () => {
    const ranked = rankInterestTagsForSelection(["software_development"]);
    const rankedIds = ranked.map((tag) => tag.id);

    expect(rankedIds[0]).toBe("software_development");
    expect(rankedIds).toEqual(
      expect.arrayContaining(INTEREST_TAGS.map((tag) => tag.id)),
    );
    expect(rankedIds.indexOf("automation_workflows")).toBeGreaterThan(0);
    expect(rankedIds.indexOf("automation_workflows")).toBeLessThan(
      rankedIds.indexOf("find_apartments"),
    );
    expect(rankedIds.indexOf("privacy_personal_data")).toBeLessThan(
      rankedIds.indexOf("find_restaurants_cafes"),
    );
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("keeps multiple selected tags first in selection order and ignores invalid duplicates", () => {
    const rankedIds = rankInterestTagsForSelection([
      "privacy_personal_data",
      "unknown_tag",
      "software_development",
      "privacy_personal_data",
    ]).map((tag) => tag.id);

    expect(rankedIds.slice(0, 2)).toEqual([
      "privacy_personal_data",
      "software_development",
    ]);
    expect(rankedIds).toEqual(Array.from(new Set(rankedIds)));
    expect(rankedIds).toEqual(
      expect.arrayContaining(INTEREST_TAGS.map((tag) => tag.id)),
    );
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("ranks developer, CLI, and privacy feature inspirations before generic defaults", () => {
    const inspirations = [
      { inspiration_id: "openmates-intro", category: "openmates_official" },
      { inspiration_id: "generic-curiosity", category: "general_knowledge" },
      { inspiration_id: "cli-parity", category: "software_development" },
      { inspiration_id: "sandbox-code-execution", category: "software_development" },
      { inspiration_id: "pii-detection", category: "openmates_official" },
      { inspiration_id: "relevant-memories", category: "openmates_official" },
    ];

    const ranked = rankDailyInspirationsByInterests(inspirations, [
      "software_development",
      "privacy_personal_data",
    ]).map((inspiration) => inspiration.inspiration_id);

    expect(ranked.slice(0, 4)).toEqual([
      "sandbox-code-execution",
      "cli-parity",
      "pii-detection",
      "relevant-memories",
    ]);
    expect(ranked.indexOf("generic-curiosity")).toBeGreaterThan(
      ranked.indexOf("openmates-intro"),
    );
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.catalog.discoverable
  it("dedupes ranked example chats and remains deterministic", () => {
    const selected: InterestTagId[] = [
      "software_development",
      "privacy_personal_data",
    ];
    const exampleIds = [
      "example-gigantic-airplanes",
      "example-svelte-runes-docs",
      "example-python-squares-code-run",
      "example-pdf-search-encryption",
      "example-python-squares-code-run",
      "example-privacy-website-hero-background",
    ];

    const first = rankExampleChatIdsByInterests(exampleIds, selected);
    const second = rankExampleChatIdsByInterests(exampleIds, selected);

    expect(first).toEqual(second);
    expect(first).toEqual(Array.from(new Set(first)));
    expect(first.slice(0, 4)).toEqual([
      "example-svelte-runes-docs",
      "example-python-squares-code-run",
      "example-pdf-search-encryption",
      "example-privacy-website-hero-background",
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=landing-onboarding.legacy-intros-retired
  it("ranks intro chats and suggestion keys from the shared registry", () => {
    expect(
      rankIntroChatIdsByInterests(
        [
          "demo-for-everyone",
          "demo-who-develops-openmates",
          "demo-for-developers",
        ],
        ["software_development"],
      ),
    ).toEqual([
      "demo-who-develops-openmates",
      // Retired intros no longer receive registry interest boosts.
      "demo-for-everyone",
      "demo-for-developers",
    ]);

    expect(
      rankSuggestionKeysByInterests(
        [
          "chat.new_chat_suggestions.plan_trip_japan",
          "chat.new_chat_suggestions.learn_coding",
          "chat.new_chat_suggestions.cybersecurity",
          "chat.new_chat_suggestions.discover_video_search",
        ],
        ["software_development", "privacy_personal_data"],
      ).slice(0, 2),
    ).toEqual([
      "chat.new_chat_suggestions.cybersecurity",
      "chat.new_chat_suggestions.learn_coding",
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated
  it("keeps personalized inspirations ahead of guest product explainers", () => {
    const ranked = rankDailyInspirationsByInterests(
      [
        {
          inspiration_id: "pii-detection",
          category: "openmates_official",
        },
        {
          inspiration_id: "personalized-user-topic",
          category: "general_knowledge",
          personalized: true,
        },
      ],
      ["privacy_personal_data"],
    );

    expect(ranked[0].inspiration_id).toBe("personalized-user-topic");
  });
});
