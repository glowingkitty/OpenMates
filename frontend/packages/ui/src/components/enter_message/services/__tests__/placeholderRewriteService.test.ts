// frontend/packages/ui/src/components/enter_message/services/__tests__/placeholderRewriteService.test.ts
// Unit tests for the client-side placeholder rewrite layer.
// These tests protect the privacy boundary before outbound sends by proving
// known originals are rewritten to existing placeholders without guessing.
// Contract: feature.pii-protection / pii.outbound.known-original-rewrite.

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
  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("rewrites message-level original values to existing placeholders", () => {
    const result = rewriteKnownPIIPlaceholders(
      "Use alice@example.com for the signup form",
      { mappings },
    );

    expect(result.markdown).toBe("Use [EMAIL_1_com] for the signup form");
    expect(result.appliedMappings).toEqual([mappings[0]]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("preserves category-aware finance placeholders as opaque tokens", () => {
    const result = rewriteKnownPIIPlaceholders(
      "How much did I spend on Spotify this year?",
      { mappings },
    );

    expect(result.markdown).toBe(
      "How much did I spend on [MERCHANT_STREAMING_001] this year?",
    );
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
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

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("replaces all exact occurrences with the same placeholder", () => {
    const result = rewriteKnownPIIPlaceholders(
      "Spotify and Spotify Premium are related to Spotify",
      { mappings },
    );

    expect(result.markdown).toBe(
      "[MERCHANT_STREAMING_001] and [MERCHANT_STREAMING_001] Premium are related to [MERCHANT_STREAMING_001]",
    );
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("does not invent placeholders for unknown values", () => {
    const result = rewriteKnownPIIPlaceholders("Ask about New Merchant Ltd", {
      mappings,
    });

    expect(result.markdown).toBe("Ask about New Merchant Ltd");
    expect(result.appliedMappings).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
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

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("does not rewrite inside embed reference JSON blocks", () => {
    const result = rewriteKnownPIIPlaceholders(
      'Spotify\n```json\n{"embed_id":"Spotify","type":"finance"}\n```',
      { mappings },
    );

    expect(result.markdown).toBe(
      '[MERCHANT_STREAMING_001]\n```json\n{"embed_id":"Spotify","type":"finance"}\n```',
    );
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("never rewrites the fixed nonce of a placeholder emitted for another original", () => {
    const nonce = "ee424413efba42e1";
    const number = { original: "42", placeholder: `[ADDRESS_1_${nonce}]`, type: "ADDRESS" };
    const street = { original: "Maple Avenue", placeholder: `[ADDRESS_2_${nonce}]`, type: "ADDRESS" };
    const absent = { original: "ADDRESS", placeholder: "[WORD_1]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("42 Maple Avenue; Maple Avenue 42", { mappings: [number, street, absent] });
    expect(result.markdown).toBe(`${number.placeholder} ${street.placeholder}; ${street.placeholder} ${number.placeholder}`);
    expect(result.appliedMappings).toEqual([street, number]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("keeps existing canonical token nonces and overlapping labels opaque", () => {
    const token = "[PERSON_NAME_1_ee424413efba42e1]";
    const number = { original: "42", placeholder: "[ADDRESS_1_ee424413efba42e1]", type: "ADDRESS" };
    const name = { original: "NAME", placeholder: "[WORD_1]", type: "PERSON" };
    const label = { original: "PERSON_NAME", placeholder: "[LABEL_1]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders(`${token} 42 PERSON_NAME`, { mappings: [number, name, label] });
    expect(result.markdown).toBe(`${token} ${number.placeholder} ${label.placeholder}`);
    expect(result.appliedMappings).toEqual([label, number]);
    expect(rewriteKnownPIIPlaceholders(token, { mappings: [number, name, label] }).appliedMappings).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("redacts typed plain-text aliases without rescanning aliases emitted by another mapping", () => {
    const alice = { original: "Alice", placeholder: "Bob", type: "PERSON" };
    const bob = { original: "Bob", placeholder: "[PERSON_2]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("Bob and Alice", { mappings: [bob, alice] });
    expect(result.markdown).toBe("[PERSON_2] and Bob");
    expect(result.appliedMappings).toEqual([alice, bob]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("does not shield known originals merely because unrecognized bracket text resembles a label", () => {
    const alice = { original: "alice", placeholder: "[PERSON_1_ee424413efba42e1]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("[PERSON_alice] alice", { mappings: [alice] });
    expect(result.markdown).toBe(`[PERSON_${alice.placeholder}] ${alice.placeholder}`);
    expect(result.appliedMappings).toEqual([alice]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("preserves arbitrary literal replacements and known custom bracket forms", () => {
    const literal = { original: "a.b$[x]", placeholder: "literal $& Bob", type: "PERSON" };
    const bob = { original: "Bob", placeholder: "[PERSON_2]", type: "PERSON" };
    const alpha = { original: "Alpha", placeholder: "[my custom alias]", type: "PERSON" };
    const custom = { original: "custom", placeholder: "[WORD_1]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("a.b$[x] Bob [my custom alias] custom Alpha", { mappings: [literal, bob, alpha, custom] });
    expect(result.markdown).toBe("literal $& Bob [PERSON_2] [my custom alias] [WORD_1] [my custom alias]");
    expect(result.appliedMappings).toEqual([literal, custom, alpha, bob]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("reserves longer matches globally even when a shorter overlap starts earlier", () => {
    const short = { original: "ab", placeholder: "[SHORT]", type: "PERSON" };
    const long = { original: "bcde", placeholder: "[LONG]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("abcde ab", { mappings: [short, long] });
    expect(result.markdown).toBe("a[LONG] [SHORT]");
    expect(result.appliedMappings).toEqual([long, short]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("retains input mapping priority for equal-length overlaps", () => {
    const first = { original: "ab", placeholder: "[FIRST]", type: "PERSON" };
    const second = { original: "bc", placeholder: "[SECOND]", type: "PERSON" };
    expect(rewriteKnownPIIPlaceholders("abc", { mappings: [first, second] })).toEqual({ markdown: "[FIRST]c", appliedMappings: [first] });
    expect(rewriteKnownPIIPlaceholders("abc", { mappings: [second, first] })).toEqual({ markdown: "a[SECOND]", appliedMappings: [second] });
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("finds eligible overlapping occurrences after rejecting a candidate against a longer span", () => {
    const long = { original: "firsta", placeholder: "[LONG]", type: "PERSON" };
    const short = { original: "aa", placeholder: "[SHORT]", type: "PERSON" };
    const result = rewriteKnownPIIPlaceholders("firstaaa", { mappings: [short, long] });
    expect(result.markdown).toBe("[LONG][SHORT]");
    expect(result.appliedMappings).toEqual([long, short]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("preserves exact exclusions and mapping deduplication without touching existing tokens", () => {
    const number = { original: "42", placeholder: "[ADDRESS_1_ee424413efba42e1]", type: "ADDRESS" };
    const excluded = { original: "Maple Avenue", placeholder: "[ADDRESS_2_ee424413efba42e1]", type: "ADDRESS" };
    const active = { original: "Maple Avenue", placeholder: "[STREET_3_ee424413efba42e1]", type: "ADDRESS" };
    const result = rewriteKnownPIIPlaceholders(`42 Maple Avenue ${excluded.placeholder}`, {
      mappings: [number, excluded, active, active], excludedOriginals: new Set(["42"]), excludedPlaceholders: new Set([excluded.placeholder]),
    });
    expect(result.markdown).toBe(`42 ${active.placeholder} ${excluded.placeholder}`);
    expect(result.appliedMappings).toEqual([active]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("protects embed_id and embed_ids JSON spans without marker collisions or nonce rescans", () => {
    const number = { original: "42", placeholder: "[ADDRESS_1_ee424413efba42e1]", type: "ADDRESS" };
    const marker = { original: "OPENMATES", placeholder: "[PROJECT_1]", type: "PERSON" };
    const single = '```json\n{"embed_id":"42","type":"embed_ref","label":"OPENMATES"}\n```';
    const multiple = '```json\n{"embed_ids":["42","OPENMATES"],"type":"embed_ref"}\n```';
    const markerLiteral = "__OPENMATES_EMBED_REF_REWRITE_PROTECTED_0__";
    const result = rewriteKnownPIIPlaceholders(`42\n${single}\n${multiple}\n${markerLiteral}`, { mappings: [number, marker] });
    expect(result.markdown).toBe(`${number.placeholder}\n${single}\n${multiple}\n__[PROJECT_1]_EMBED_REF_REWRITE_PROTECTED_0__`);
    expect(result.appliedMappings).toEqual([marker, number]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.outbound.known-original-rewrite
  it("rewrites a large repeated-value paste without quadratic reserved-span scans", () => {
    const number = { original: "42", placeholder: "[ADDRESS_1_ee424413efba42e1]", type: "ADDRESS" };
    const shorter = { original: "4", placeholder: "[DIGIT_1]", type: "ADDRESS" };
    const repetitions = 30_000;
    const markdown = "42 ".repeat(repetitions);
    const started = performance.now();
    const result = rewriteKnownPIIPlaceholders(markdown, { mappings: [shorter, number] });
    const elapsed = performance.now() - started;
    expect(result.markdown).toBe(`${number.placeholder} `.repeat(repetitions));
    expect(result.appliedMappings).toEqual([number]);
    // A generous ceiling targets the observed multi-second quadratic stall,
    // with substantial headroom over this fixed 90 KB input's linear work.
    expect(elapsed).toBeLessThan(2_500);
  });
});
