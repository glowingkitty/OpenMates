// frontend/packages/ui/src/stores/__tests__/aiTypingStore.test.ts
// A resumed turn types under its running task id, while its final carries the
// shared assistant message id; the final must still end the Thinking state.
import { describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { aiTypingByChatStore, aiTypingStore } from "../aiTypingStore";

describe("aiTypingStore.clearTypingForTurn", () => {
  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("clears when the task id, the message id or the user message matches", () => {
    aiTypingStore.setTyping("chat-1", "user-1", "task-2", "software_development");
    aiTypingStore.clearTypingForTurn("chat-1", ["assistant-shared", "task-2"], "user-1");
    expect(get(aiTypingStore).isTyping).toBe(false);
    expect(get(aiTypingByChatStore)["chat-1"]).toBeUndefined();

    aiTypingStore.setTyping("chat-1", "user-1", "task-3", "software_development");
    aiTypingStore.clearTypingForTurn("chat-1", ["assistant-shared"], "user-1");
    expect(get(aiTypingStore).isTyping).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("keeps typing of a newer turn and of another chat", () => {
    aiTypingStore.setTyping("chat-1", "user-2", "task-9", "software_development");
    aiTypingStore.clearTypingForTurn("chat-1", ["assistant-old", "task-1"], "user-1");
    expect(get(aiTypingStore).isTyping).toBe(true);
    aiTypingStore.clearTypingForTurn("chat-2", ["task-9"], "user-2");
    expect(get(aiTypingByChatStore)["chat-1"]?.aiMessageId).toBe("task-9");
    aiTypingStore.clearTypingForChat("chat-1");
  });
});
