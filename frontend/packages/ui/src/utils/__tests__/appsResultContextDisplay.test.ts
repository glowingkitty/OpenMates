import { describe, expect, it } from "vitest";
import { appsRequestContextText } from "../../services/appsWorkspaceChatHandoffService";
import { appsResultContextDisplayText } from "../appsResultContextDisplay";

describe("appsResultContextDisplayText", () => {
  const sent = appsRequestContextText({
    text: "Which of these is closest?",
    context: { skill_id: "search", embed_id: "embed-1", result: { results: [{ name: "Example venue" }] } },
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it("shows only the user's words for an Apps result follow-up", () => {
    expect(sent).toContain('{"skill_id":"search"');
    const shown = appsResultContextDisplayText(sent, "user");
    expect(shown).toBe("Which of these is closest?");
    expect(shown).not.toContain("skill_id");
    expect(shown).not.toContain("Result context");
  });

  // contract-test: supporting surface=gui.web assertions=apps.requests.natural-language
  it("leaves assistant text and ordinary user text untouched", () => {
    expect(appsResultContextDisplayText(sent, "assistant")).toBe(sent);
    const plain = "Result context is a phrase I can type.\n\nSecond line.";
    expect(appsResultContextDisplayText(plain, "user")).toBe(plain);
  });
});
