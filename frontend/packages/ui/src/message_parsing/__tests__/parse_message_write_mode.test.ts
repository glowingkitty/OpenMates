// Unit tests for write-mode message parsing.
// Write mode feeds the editable TipTap composer, whose schema intentionally
// disables rendered links so users edit raw text and PII detection can decorate
// emails. These tests guard draft-restore parsing from producing unsupported
// link marks that TipTap rejects by clearing the composer.

import { describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";

function collectMarks(node: any, marks: string[] = []): string[] {
  if (!node || typeof node !== "object") return marks;

  if (Array.isArray(node.marks)) {
    for (const mark of node.marks) {
      if (mark?.type) marks.push(mark.type);
    }
  }

  if (Array.isArray(node.content)) {
    for (const child of node.content) {
      collectMarks(child, marks);
    }
  }

  return marks;
}

describe("parse_message write mode", () => {
  it("keeps bare emails as editable text without link marks", () => {
    const doc = parse_message(
      "Write from max@posteo.de to sarah@proton.com about the broken heater.",
      "write",
      { unifiedParsingEnabled: true },
    );

    expect(JSON.stringify(doc)).toContain("max@posteo.de");
    expect(JSON.stringify(doc)).toContain("sarah@proton.com");
    expect(collectMarks(doc)).not.toContain("link");
  });
});
