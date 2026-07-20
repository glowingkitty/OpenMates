// frontend/packages/ui/src/components/enter_message/services/__tests__/placeholderRewriteService.test.ts
// Unit tests for the client-side placeholder rewrite layer.
// These tests protect the privacy boundary before outbound sends by proving
// known originals are rewritten to existing placeholders without guessing.
// See docs/specs/pii-placeholder-rewrite-v1/spec.yml.

import { describe, expect, it } from "vitest";
import { rewriteKnownPIIPlaceholders } from "../placeholderRewriteService";
import type { PIIMapping } from "../../../../types/chat";

const mappings: PIIMapping[] = [
  {
    placeholder: "[EMAIL_1_com]",
    original: "alice@example.com",
    type: "EMAIL",
  },
  {
    placeholder: "[MERCHANT_STREAMING_001]",
    original: "Spotify",
    type: "MERCHANT",
  },
];

describe("rewriteKnownPIIPlaceholders", () => {
  it("rewrites message-level original values to existing placeholders", () => {
    const result = rewriteKnownPIIPlaceholders(
      "Use alice@example.com for the signup form",
      { mappings },
    );

    expect(result.markdown).toBe("Use [EMAIL_1_com] for the signup form");
    expect(result.appliedMappings).toEqual([mappings[0]]);
  });

  it("preserves category-aware finance placeholders as opaque tokens", () => {
    const result = rewriteKnownPIIPlaceholders(
      "How much did I spend on Spotify this year?",
      { mappings },
    );

    expect(result.markdown).toBe(
      "How much did I spend on [MERCHANT_STREAMING_001] this year?",
    );
  });

  it("uses the longest original first when two mappings overlap", () => {
    const result = rewriteKnownPIIPlaceholders("Ask Alice Smith about Alice", {
      mappings: [
        { placeholder: "[FIRST_NAME]", original: "Alice", type: "PERSON" },
        {
          placeholder: "[FULL_NAME]",
          original: "Alice Smith",
          type: "PERSON",
        },
      ],
    });

    expect(result.markdown).toBe("Ask [FULL_NAME] about [FIRST_NAME]");
  });

  it("replaces all exact occurrences with the same placeholder", () => {
    const result = rewriteKnownPIIPlaceholders(
      "Spotify and Spotify Premium are related to Spotify",
      { mappings },
    );

    expect(result.markdown).toBe(
      "[MERCHANT_STREAMING_001] and [MERCHANT_STREAMING_001] Premium are related to [MERCHANT_STREAMING_001]",
    );
  });

  it("does not invent placeholders for unknown values", () => {
    const result = rewriteKnownPIIPlaceholders("Ask about New Merchant Ltd", {
      mappings,
    });

    expect(result.markdown).toBe("Ask about New Merchant Ltd");
    expect(result.appliedMappings).toEqual([]);
  });

  it("current-send exclusions suppress rewrite for exact values", () => {
    const result = rewriteKnownPIIPlaceholders(
      "Use alice@example.com and Spotify",
      {
        mappings,
        excludedOriginals: new Set(["alice@example.com"]),
      },
    );

    expect(result.markdown).toBe(
      "Use alice@example.com and [MERCHANT_STREAMING_001]",
    );
  });

  it("does not rewrite inside embed reference JSON blocks", () => {
    const result = rewriteKnownPIIPlaceholders(
      'Spotify\n```json\n{"embed_id":"Spotify","type":"finance"}\n```',
      { mappings },
    );

    expect(result.markdown).toBe(
      '[MERCHANT_STREAMING_001]\n```json\n{"embed_id":"Spotify","type":"finance"}\n```',
    );
  });
});
