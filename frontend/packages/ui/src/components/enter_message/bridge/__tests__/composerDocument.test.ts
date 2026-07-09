// Cross-client contract tests for the product-owned composer document schema.
// Canonical markdown remains durable; Tiptap and native Apple are adapters.
// Fixtures are synthetic and shared with Swift tests to prevent semantic drift.
// These tests intentionally fail until the ComposerDocument adapter exists.
// No chat content, encryption material, or private identifiers are included.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  parseCanonicalMarkdownToComposerDocument,
  serializeComposerDocumentToCanonicalMarkdown,
  utf16Length,
} from "../composerDocument";

interface SelectionFixture {
  label: string;
  source: string;
  utf16_offset: number;
}

interface ComposerFixtureCase {
  id: string;
  canonical_markdown: string;
  document: Record<string, unknown>;
  selection_fixtures: SelectionFixture[];
}

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../../../../shared/composer/fixtures/composer-document-v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as { schema_version: number; cases: ComposerFixtureCase[] };

describe("ComposerDocumentV1 cross-client contract", () => {
  it("uses the supported schema version", () => {
    expect(fixture.schema_version).toBe(1);
  });

  for (const testCase of fixture.cases) {
    it(`parses and serializes ${testCase.id}`, () => {
      const document = parseCanonicalMarkdownToComposerDocument(
        testCase.canonical_markdown,
      );

      expect(document).toEqual(testCase.document);
      expect(serializeComposerDocumentToCanonicalMarkdown(document)).toBe(
        testCase.canonical_markdown,
      );
    });

    for (const selection of testCase.selection_fixtures) {
      it(`uses UTF-16 positions for ${testCase.id}/${selection.label}`, () => {
        expect(utf16Length(selection.source)).toBe(selection.utf16_offset);
      });
    }
  }
});
