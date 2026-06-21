// frontend/packages/ui/src/demo_chats/__tests__/guestSmartSelection.test.ts
// Regression coverage for the guest interest smart-selection contract.
// These tests guard the deterministic, local-only ranking rules before the
// Svelte welcome screen consumes them.

import { describe, expect, it } from "vitest";

import {
  INTEREST_TAGS,
  type InterestTagId,
} from "../interestTags";
import {
  rankDailyInspirationsByInterests,
  rankExampleChatIdsByInterests,
  rankIntroChatIdsByInterests,
  rankInterestTagsForSelection,
  rankSuggestionKeysByInterests,
} from "../guestSmartSelection";

describe("guestSmartSelection", () => {
  it("keeps selected tags first and moves related tags next without hiding unrelated tags", () => {
    const ranked = rankInterestTagsForSelection(["software_development"]);
    const rankedIds = ranked.map((tag) => tag.id);

    expect(rankedIds[0]).toBe("software_development");
    expect(rankedIds).toEqual(
      expect.arrayContaining(INTEREST_TAGS.map((tag) => tag.id)),
    );
    expect(rankedIds.indexOf("use_the_cli")).toBeGreaterThan(0);
    expect(rankedIds.indexOf("use_the_cli")).toBeLessThan(
      rankedIds.indexOf("find_apartments"),
    );
    expect(rankedIds.indexOf("protect_my_privacy")).toBeLessThan(
      rankedIds.indexOf("local_life"),
    );
  });

  it("keeps multiple selected tags first in selection order and ignores invalid duplicates", () => {
    const rankedIds = rankInterestTagsForSelection([
      "protect_my_privacy",
      "unknown_tag",
      "software_development",
      "protect_my_privacy",
    ]).map((tag) => tag.id);

    expect(rankedIds.slice(0, 2)).toEqual([
      "protect_my_privacy",
      "software_development",
    ]);
    expect(rankedIds).toEqual(Array.from(new Set(rankedIds)));
    expect(rankedIds).toEqual(
      expect.arrayContaining(INTEREST_TAGS.map((tag) => tag.id)),
    );
  });

  it("ranks developer, CLI, and privacy inspirations before generic defaults", () => {
    const inspirations = [
      { inspiration_id: "openmates-intro", category: "openmates_official" },
      { inspiration_id: "generic-curiosity", category: "general_knowledge" },
      { inspiration_id: "cli-programmatic-use", category: "software_development" },
      { inspiration_id: "developer-docs-code", category: "software_development" },
      { inspiration_id: "privacy-pii-replacement", category: "openmates_official" },
      { inspiration_id: "apps-skills-tools", category: "openmates_official" },
    ];

    const ranked = rankDailyInspirationsByInterests(inspirations, [
      "software_development",
      "protect_my_privacy",
    ]).map((inspiration) => inspiration.inspiration_id);

    expect(ranked.slice(0, 4)).toEqual([
      "developer-docs-code",
      "cli-programmatic-use",
      "privacy-pii-replacement",
      "apps-skills-tools",
    ]);
    expect(ranked.indexOf("generic-curiosity")).toBeGreaterThan(
      ranked.indexOf("openmates-intro"),
    );
  });

  it("dedupes ranked example chats and remains deterministic", () => {
    const selected: InterestTagId[] = [
      "software_development",
      "protect_my_privacy",
    ];
    const exampleIds = [
      "example-gigantic-airplanes",
      "example-svelte-runes-docs",
      "example-python-squares-code-run",
      "example-pdf-search-encryption",
      "example-python-squares-code-run",
      "example-openmates-app-skills-embeds-docs",
      "example-privacy-website-hero-background",
    ];

    const first = rankExampleChatIdsByInterests(exampleIds, selected);
    const second = rankExampleChatIdsByInterests(exampleIds, selected);

    expect(first).toEqual(second);
    expect(first).toEqual(Array.from(new Set(first)));
    expect(first.slice(0, 4)).toEqual([
      "example-svelte-runes-docs",
      "example-python-squares-code-run",
      "example-openmates-app-skills-embeds-docs",
      "example-pdf-search-encryption",
    ]);
  });

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
      "demo-for-developers",
      "demo-who-develops-openmates",
      "demo-for-everyone",
    ]);

    expect(
      rankSuggestionKeysByInterests(
        [
          "chat.new_chat_suggestions.plan_trip_japan",
          "chat.new_chat_suggestions.learn_coding",
          "chat.new_chat_suggestions.cybersecurity",
          "chat.new_chat_suggestions.discover_video_search",
        ],
        ["software_development", "protect_my_privacy"],
      ).slice(0, 2),
    ).toEqual([
      "chat.new_chat_suggestions.learn_coding",
      "chat.new_chat_suggestions.cybersecurity",
    ]);
  });

  it("keeps personalized inspirations ahead of guest product explainers", () => {
    const ranked = rankDailyInspirationsByInterests(
      [
        {
          inspiration_id: "privacy-pii-replacement",
          category: "openmates_official",
        },
        {
          inspiration_id: "personalized-user-topic",
          category: "general_knowledge",
          personalized: true,
        },
      ],
      ["protect_my_privacy"],
    );

    expect(ranked[0].inspiration_id).toBe("personalized-user-topic");
  });
});
