import { describe, expect, it } from "vitest";
import { stripVoiceDeliveryCues } from "../voiceDeliveryCues";

describe("assistant voice delivery projection", () => {
  // contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response
  it("hides complete and streamed cues without changing links or rich source", () => {
    const source = "<!-- voice:curious -->Read [the guide](https://example.org). <!-- voice:short pause -->Then continue.";
    const clean = " Read [the guide](https://example.org).  Then continue.";
    expect(stripVoiceDeliveryCues(source)).toBe(clean);
    expect(stripVoiceDeliveryCues("Useful answer. <!-- voice:cur")).toBe("Useful answer.  ");
    expect(source).toContain("<!-- voice:curious -->");
  });

  // contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.privacy
  it("preserves inline and fenced code literals, including nested shorter fences", () => {
    for (const literal of ["`<!-- voice:curious -->`", "```text\n<!-- voice:excited -->\n```", "~~~text\n<!-- voice:laughs -->\n~~~", "````markdown\n```\n<!-- voice:excited -->\n````"]) {
      expect(stripVoiceDeliveryCues(literal)).toBe(literal);
    }
  });
});
