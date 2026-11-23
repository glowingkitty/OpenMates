import { describe, expect, it } from "vitest";
import { getSchema } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { parse_message } from "../parse_message";

// Issue WRPEB: a pasted CV with lists produced listItem nodes the composer
// schema lacks; Tiptap discarded the document and the send hung.
const longCv = [
  "# Curriculum vitae",
  "",
  "Example Person, product designer based in Example City.",
  "",
  "## Experience",
  "",
  ...Array.from({ length: 30 }, (_, i) => `- Led design project ${i + 1} for an example client, shipped on time`),
  "  - Nested detail about the toolchain",
  "",
  "## Steps I follow",
  "",
  ...Array.from({ length: 12 }, (_, i) => `${i + 1}. Step ${i + 1} of the research process`),
  "",
  "> Quote from a reference letter",
  "",
  "---",
  "",
  "Thanks for reading.",
].join("\n");

function paragraphTexts(doc: any): string[] {
  return (doc.content ?? []).map((block: any) => (block.content ?? []).map((n: any) => n.text ?? "").join(""));
}

describe("parse_message write mode with pasted lists", () => {
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it("produces only nodes the composer schema knows", () => {
    expect(longCv.length).toBeGreaterThan(1000);
    // Same block nodes as the write-mode composer (editorConfig.ts), without
    // importing its send handlers and their service side effects.
    const schema = getSchema([
      StarterKit.configure({
        bold: false, italic: false, strike: false, code: false, heading: false, blockquote: false,
        bulletList: false, orderedList: false, listItem: false, horizontalRule: false, codeBlock: false, link: false,
      }),
    ]);
    for (const unifiedParsingEnabled of [true, false]) {
      const doc = parse_message(longCv, "write", { unifiedParsingEnabled });
      expect(JSON.stringify(doc)).not.toContain('"listItem"');
      expect(() => schema.nodeFromJSON(doc)).not.toThrow();
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it("keeps the list markers and text the user pasted", () => {
    const texts = paragraphTexts(parse_message(longCv, "write", { unifiedParsingEnabled: true }));
    expect(texts).toContain("- Led design project 1 for an example client, shipped on time");
    expect(texts.filter((t) => t.includes("project 30") || t.includes("Nested"))).toEqual([
      "- Led design project 30 for an example client, shipped on time",
      "  - Nested detail about the toolchain",
    ]);
    expect(texts).toContain("1. Step 1 of the research process");
    expect(texts).toContain("12. Step 12 of the research process");
    expect(texts).toContain("# Curriculum vitae");
    expect(texts).toContain("> Quote from a reference letter");
    expect(texts).toContain("Thanks for reading.");
  });
});
