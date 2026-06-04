// frontend/packages/ui/src/components/enter_message/services/__tests__/pasteClassification.test.ts
//
// Unit tests for message composer paste classification.
// The classifier is intentionally conservative so short prose remains editable,
// while obvious code, formatted documents, and tables become the right embed type.

import { describe, expect, it } from "vitest";
import { classifyPastedContent } from "../pasteClassification";

describe("classifyPastedContent", () => {
  it("keeps short plain multi-line prose as editable text", () => {
    const result = classifyPastedContent({
      text: "Liebe Familie,\n\nich freue mich sehr, heute hier zu sein.",
    });

    expect(result.kind).toBe("text");
  });

  it("turns long prose into a docs embed", () => {
    const paragraph = "This is a normal paragraph with enough natural language words to resemble a pasted document rather than a quick chat message.";
    const text = Array.from({ length: 18 }, () => paragraph).join("\n\n");

    const result = classifyPastedContent({ text });

    expect(result.kind).toBe("document");
    expect(result.documentHtml).toContain("<p>");
  });

  it("turns formatted HTML into a docs embed", () => {
    const result = classifyPastedContent({
      text: "Quarterly plan\nGoal one",
      html: "<h1>Quarterly plan</h1><p>Goal one</p>",
    });

    expect(result.kind).toBe("document");
    expect(result.reason).toBe("formatted-document");
  });

  it("turns detected code into a code embed", () => {
    const result = classifyPastedContent({
      text: "const answer = 42;\nconsole.log(answer);",
      detectedLanguage: "typescript",
    });

    expect(result.kind).toBe("code");
  });

  it("turns tab-separated rows into a sheet embed", () => {
    const result = classifyPastedContent({
      text: "Name\tScore\nAda\t10\nGrace\t9",
    });

    expect(result.kind).toBe("sheet");
    expect(result.sheetMarkdown).toContain("| Name | Score |");
  });

  it("turns HTML tables into a sheet embed", () => {
    const result = classifyPastedContent({
      text: "Name Score Ada 10",
      html: "<table><tr><th>Name</th><th>Score</th></tr><tr><td>Ada</td><td>10</td></tr></table>",
    });

    expect(result.kind).toBe("sheet");
    expect(result.sheetMarkdown).toContain("| Name | Score |");
  });
});
