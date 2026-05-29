// frontend/packages/ui/src/components/enter_message/utils/__tests__/fileContentParsers.test.ts
//
// Unit tests for lightweight client-side file parsers used before embed PII
// redaction. These parsers intentionally avoid heavy document dependencies and
// must preserve enough structure for sheet/mail embeds to stay useful.

import { describe, expect, it } from "vitest";
import { delimitedTextToMarkdownTable, parseEmlText } from "../fileContentParsers";

describe("delimitedTextToMarkdownTable", () => {
  it("converts CSV rows and preserves quoted commas", () => {
    const markdown = delimitedTextToMarkdownTable(
      'Name,Email,Note\nAda,ada@example.com,"Hello, team"',
      ",",
    );

    expect(markdown).toContain("| Name | Email | Note |");
    expect(markdown).toContain("| Ada | ada@example.com | Hello, team |");
  });

  it("converts TSV rows", () => {
    const markdown = delimitedTextToMarkdownTable("Name\tScore\nGrace\t9", "\t");

    expect(markdown).toContain("| Name | Score |");
    expect(markdown).toContain("| Grace | 9 |");
  });
});

describe("parseEmlText", () => {
  it("extracts standard email headers and body", () => {
    const parsed = parseEmlText([
      "From: Ada <ada@example.com>",
      "To: Grace <grace@example.com>",
      "Subject: Launch notes",
      "Date: Fri, 29 May 2026 10:00:00 +0000",
      "",
      "Please call +1 555 123 4567 before launch.",
    ].join("\n"));

    expect(parsed.receiver).toBe("Grace <grace@example.com>");
    expect(parsed.subject).toBe("Launch notes");
    expect(parsed.content).toContain("Please call");
    expect(parsed.footer).toContain("ada@example.com");
  });
});
