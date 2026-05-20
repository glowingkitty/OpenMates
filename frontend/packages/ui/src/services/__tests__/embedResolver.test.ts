// Unit tests for embed resolver decoding behavior.
// Code embeds can contain arbitrary multiline source text.
// These tests cover the defensive recovery path used when the TOON decoder
// misinterprets multiline code as a malformed key instead of a `code` field.
// The test keeps the fixture close to the failing dev issue payload shape.

import { describe, expect, it } from "vitest";
import { recoverCodeEmbedFromToon } from "../embedResolver";

describe("recoverCodeEmbedFromToon", () => {
  it("recovers multiline code and lineCount from malformed decoded TOON", () => {
    const toonContent = `type: code
language: python
code: "# Sample list
numbers = [5, 2, 9]
print(f"sorted list: {sorted(numbers)}")"
filename: sorting_basics.py
status: finished
line_count: 3`;
    const malformedDecoded = {
      type: "code",
      language: "python",
      'code: "# Sample list\nnumbers =': "",
      filename: "sorting_basics.py",
      status: "finished",
    };

    const recovered = recoverCodeEmbedFromToon(
      toonContent,
      malformedDecoded,
    ) as Record<string, unknown>;

    expect(recovered.code).toContain("numbers = [5, 2, 9]");
    expect(recovered.code).toContain("sorted list");
    expect(recovered.filename).toBe("sorting_basics.py");
    expect(recovered.lineCount).toBe(3);
  });
});
