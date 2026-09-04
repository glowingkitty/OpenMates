// Regression guard for the authenticated welcome-screen resume-card effect.
// The effect invokes an async loader that writes resumeChatData after reading
// IndexedDB. Its context-safety read must remain untracked, otherwise each
// successful load schedules the effect again and creates an unbounded loop.
// Deployed flow coverage verifies the resulting user-visible behavior.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("../ActiveChat.svelte", import.meta.url), "utf8");

describe("ActiveChat resume-card effect", () => {
  // contract-test: direct surface=gui.web assertions=chats.local-state.precedence,sync.startup.bounded-phases
  it("does not track the resume state that its async loader writes", () => {
    expect(source).toContain(
      "const currentResumeChat = untrack(() => resumeChatData);",
    );
    expect(source).toContain(
      "if (currentResumeChat && !isChatInActiveTeamContext(currentResumeChat, contextTeamId))",
    );
  });
});
