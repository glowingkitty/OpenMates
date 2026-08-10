// Cross-client contract tests for the product-owned composer document schema.
// Canonical markdown remains durable; Tiptap and native Apple are adapters.
// Fixtures are synthetic and shared with Swift tests to prevent semantic drift.
// These tests intentionally fail until the ComposerDocument adapter exists.
// No chat content, encryption material, or private identifiers are included.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ComposerDocumentError,
  parseCanonicalMarkdownToComposerDocument,
  serializeComposerDocumentToCanonicalMarkdown,
  type ComposerDocumentV1,
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

interface InvalidDocumentFixture {
  id: string;
  expected_error: string;
  document: Record<string, unknown>;
}

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../../../../shared/composer/fixtures/composer-document-v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as {
  schema_version: number;
  cases: ComposerFixtureCase[];
  invalid_documents: InvalidDocumentFixture[];
};

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

  for (const invalidCase of fixture.invalid_documents) {
    it(`rejects ${invalidCase.id} without partial serialization`, () => {
      try {
        serializeComposerDocumentToCanonicalMarkdown(
          invalidCase.document as unknown as ComposerDocumentV1,
        );
        expect.fail("Expected ComposerDocument serialization to fail");
      } catch (error) {
        expect(error).toBeInstanceOf(ComposerDocumentError);
        expect((error as ComposerDocumentError).code).toBe(
          invalidCase.expected_error,
        );
      }
    });
  }
});
