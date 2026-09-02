// contract-test-file: feature
/**
 * Contracts for owner-authenticated historical assistant speech generation.
 * Projection remains local to the paired CLI and output summaries exclude
 * plaintext, encryption material, provider identifiers, and private paths.
 * Network lifecycle coverage lives in the focused client and live-dev gates.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

import {
  projectAssistantSpeech,
  selectAssistantMessagesForSpeech,
  summarizeAssistantSpeech,
} from "../dist/index.js";

const messages = [
  { id: "user-1", role: "user", content: "Question" },
  { id: "row-1", clientMessageId: "assistant-1", role: "assistant", content: "First paragraph.\n\nSecond [source](https://example.com)." },
  { id: "assistant-2", role: "assistant", content: "Final answer." },
];

describe("chats speak", () => {
  // contract-test: direct surface=cli assertions=assistant-speech.cli.owner-generated-existing-messages,assistant-speech.privacy.transient-plaintext-encrypted-audio
  it("projects assistant paragraphs without speaking raw URLs", () => {
    assert.deepEqual(projectAssistantSpeech(messages[1].content), [
      { sequence: 0, kind: "prose_paragraph", speakableText: "First paragraph." },
      { sequence: 1, kind: "prose_paragraph", speakableText: "Second source." },
    ]);
  });

  // contract-test: direct surface=cli assertions=assistant-speech.cli.owner-generated-existing-messages,assistant-speech.access.first-party-owner-scoped
  it("selects one assistant message or every eligible assistant message", () => {
    assert.deepEqual(selectAssistantMessagesForSpeech(messages, { messageId: "assistant-1" }).map((message) => message.clientMessageId), ["assistant-1"]);
    assert.deepEqual(selectAssistantMessagesForSpeech(messages, { messageId: "assistant-2" }).map((message) => message.id), ["assistant-2"]);
    assert.deepEqual(selectAssistantMessagesForSpeech(messages, { all: true }).map((message) => message.id), ["row-1", "assistant-2"]);
    assert.throws(() => selectAssistantMessagesForSpeech(messages, {}), /exactly one/i);
    assert.throws(() => selectAssistantMessagesForSpeech(messages, { messageId: "user-1" }), /assistant message/i);
  });

  // contract-test: direct surface=cli assertions=assistant-speech.cli.owner-generated-existing-messages,assistant-speech.privacy.transient-plaintext-encrypted-audio
  it("returns a safe terminal summary", () => {
    const summary = summarizeAssistantSpeech("chat-1", [
      { messageId: "assistant-1", generated: 1, reused: 1, failed: 0, charged: 1 },
    ]);
    assert.deepEqual(summary, {
      chat_id: "chat-1",
      messages: 1,
      generated_segments: 1,
      reused_segments: 1,
      failed_segments: 0,
      charged_segments: 1,
    });
    assert.doesNotMatch(JSON.stringify(summary), /speakable|aes|vault|s3|voice/i);
  });

  // contract-test: direct surface=cli assertions=assistant-speech.access.first-party-owner-scoped
  it("requires a paired CLI session before generation", () => {
    const home = mkdtempSync(join(tmpdir(), "openmates-speak-no-session-"));
    try {
      const result = spawnSync("node", ["dist/cli.js", "chats", "speak", "chat-1", "--all"], {
        cwd: new URL("..", import.meta.url),
        encoding: "utf8",
        env: { ...process.env, HOME: home, USERPROFILE: home },
      });
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /openmates login/i);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
