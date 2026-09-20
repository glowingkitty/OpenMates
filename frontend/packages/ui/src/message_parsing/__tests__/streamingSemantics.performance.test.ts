import { describe, expect, it } from "vitest";
import { handleStreamingSemantics } from "../streamingSemantics";

describe("write-mode table scanning", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.drafts.preview-persistence
  it("emits one table block for one contiguous table", () => {
    const markdown = Array.from(
      { length: 1_000 },
      (_, index) => `| Item ${index} | value |`,
    ).join("\n");

    const result = handleStreamingSemantics(markdown, "write");
    const tables = result.unclosedBlocks.filter((block) => block.type === "table");

    expect(tables).toHaveLength(1);
    expect(tables[0]?.content).toContain("| Item 999 | value |");
  });
});
