import { describe, expect, it } from "vitest";
import { transactionInsertedTriggerCharacter } from "../composerParsingSchedule";

const triggers = new Set([" ", ".", "\n"]);

function transaction(insertedText: string, docChanged = true) {
  return {
    docChanged,
    steps: [{
      toJSON: () => ({
        stepType: "replace",
        from: 4,
        to: 4,
        slice: { content: [{ type: "text", text: insertedText }] },
      }),
    }],
  };
}

describe("transactionInsertedTriggerCharacter", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.drafts.preview-persistence
  it("does not use an unrelated delimiter at the end of the document", () => {
    expect(transactionInsertedTriggerCharacter(transaction("x"), triggers)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.drafts.preview-persistence
  it("detects delimiters inserted by the current transaction", () => {
    expect(transactionInsertedTriggerCharacter(transaction("word "), triggers)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.drafts.preview-persistence
  it("ignores selection-only transactions", () => {
    expect(transactionInsertedTriggerCharacter(transaction(" ", false), triggers)).toBe(false);
  });
});
