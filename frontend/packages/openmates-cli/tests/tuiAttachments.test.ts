import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { OpenMatesClient } from "../src/client.js";
import { prepareTuiMessage } from "../src/tuiAttachments.js";

const client = (signedIn: boolean, onMemories?: () => void): OpenMatesClient => ({
  hasSession: () => signedIn,
  listMemories: async () => { onMemories?.(); return []; },
  getSession: () => ({}),
} as unknown as OpenMatesClient);

// contract-test: supporting surface=cli assertions=tasks.content.client-encrypted,cli.surface.semantic-parity
test("messages without explicit file paths pass through without reading account state", async () => {
  const result = await prepareTuiMessage({hasSession: () => {throw new Error("unexpected account lookup");}} as unknown as OpenMatesClient, "Hello @TASK-123 and @Maya");
  assert.deepEqual(result, {message: "Hello @TASK-123 and @Maya", preparedEmbeds: [], displayNames: []});
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("signed-out file mentions fail before file reads or memory loading", async () => {
  let memoriesLoaded = false;
  const fake = client(false, () => { memoriesLoaded = true; });
  await assert.rejects(prepareTuiMessage(fake, "Please read @./missing-file.txt"), /signed-in account/);
  assert.equal(memoriesLoaded, false);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("missing and sensitive file paths surface useful errors", async () => {
  const directory = mkdtempSync(join(tmpdir(), "tui-attachments-"));
  try {
    const key = join(directory, "private.pem");
    writeFileSync(key, "private key material");
    const missing = join(directory, "missing.txt");
    await assert.rejects(prepareTuiMessage(client(true), `Read @${missing} and @${key}`), (error: Error) => {
      assert.match(error.message, /missing\.txt.*File not found/);
      assert.match(error.message, /Blocked .*private\.pem/);
      return true;
    });
  } finally { rmSync(directory, {recursive: true, force: true}); }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("explicit text and env paths become local embeds and leave other mentions intact", async () => {
  const directory = mkdtempSync(join(tmpdir(), "tui-attachments-"));
  try {
    const textPath = join(directory, "notes.txt");
    const envPath = join(directory, ".env");
    writeFileSync(textPath, "Meeting notes");
    writeFileSync(envPath, "SECRET=somethingveryprivate\n");
    const result = await prepareTuiMessage(client(true), `Read @${textPath} @${envPath} and ask @Maya`);
    assert.deepEqual(result.displayNames, ["notes.txt", ".env"]);
    assert.equal(result.preparedEmbeds.length, 2);
    assert.ok(result.preparedEmbeds.every((embed) => embed.type === "code-code"));
    assert.match(result.message, /@Maya/);
    assert.doesNotMatch(result.message, /@\//);
    assert.match(result.message, /\[!\]\(embed:/);
    assert.doesNotMatch(result.preparedEmbeds[1].content, /somethingveryprivate/);
  } finally { rmSync(directory, {recursive: true, force: true}); }
});
