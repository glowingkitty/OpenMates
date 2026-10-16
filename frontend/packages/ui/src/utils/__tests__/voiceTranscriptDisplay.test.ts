import { describe, expect, it } from "vitest";
import { voiceTranscriptDisplayText } from "../voiceTranscriptDisplay";

describe("saved voice transcript display", () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
  it.each(["_((interrupted))_", "_(Interrupted)_", "_((unterbrochen))_"])("hides the legacy %s suffix", marker => {
    expect(voiceTranscriptDisplayText(`Spoken answer.\n\n${marker}`, "assistant")).toBe("Spoken answer.");
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
  it("preserves user-authored text and inline discussion of interruption", () => {
    const userText = "Example:\n\n_((interrupted))_";
    expect(voiceTranscriptDisplayText(userText, "user")).toBe(userText);
    expect(voiceTranscriptDisplayText("The word ((interrupted)) is quoted here.", "assistant"))
      .toBe("The word ((interrupted)) is quoted here.");
  });
});
