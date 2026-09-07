/**
 * Codex Task connection transport and execution-boundary tests.
 * Uses a temporary Unix socket with synthetic thread metadata only.
 * Asserts that status never resumes, sends a prompt or starts a daemon.
 * Legacy links are preserved as data but cannot launch an old runtime.
 * Live installed-daemon proof is recorded separately in TASK-7543.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import { WebSocketServer } from "ws";
import { codexResumeArguments, readCodexThread } from "../src/codexConnection.ts";

const THREAD = "00000000-0000-4000-8000-000000000001";

// contract-test: supporting surface=cli assertions=tasks.assignment.identity-separated,tasks.external-chat.encrypted-context
test("Codex resume only accepts an explicit Codex UUID", () => {
  assert.deepEqual(codexResumeArguments({ provider: "codex", id: THREAD }), ["resume", THREAD]);
  assert.throws(() => codexResumeArguments({ provider: "opencode", id: "ses_old" }), /read-only/);
  assert.throws(() => codexResumeArguments({ provider: "codex", id: "--last" }), /UUID/);
});

// contract-test: supporting surface=cli assertions=tasks.external-chat.encrypted-context
test("connection reads metadata without resume, prompt, transcript or compression", async () => {
  const directory = await mkdtemp(join(tmpdir(), "om-codex-"));
  const socket = join(directory, "test.sock");
  const http = createServer();
  const wss = new WebSocketServer({ server: http });
  const methods: string[] = [];
  let compression: string | undefined;
  wss.on("connection", (ws, req) => {
    compression = req.headers["sec-websocket-extensions"];
    ws.on("message", raw => {
      const request = JSON.parse(raw.toString());
      methods.push(request.method);
      if (request.method === "initialize") ws.send(JSON.stringify({ id: request.id, result: {} }));
      if (request.method === "thread/read") {
        assert.deepEqual(request.params, { threadId: THREAD, includeTurns: false });
        ws.send(JSON.stringify({ id: request.id, result: { thread: { id: THREAD, name: "Test", status: { type: "idle" } } } }));
      }
    });
  });
  await new Promise<void>(resolve => http.listen(socket, resolve));
  try {
    assert.deepEqual(await readCodexThread(THREAD, socket), {
      provider: "codex", id: THREAD, title: "Test", status: "idle", url: `codex://threads/${THREAD}`,
    });
    assert.deepEqual(methods, ["initialize", "initialized", "thread/read"]);
    assert.equal(compression, undefined);
  } finally {
    for (const client of wss.clients) client.terminate();
    await new Promise<void>(resolve => wss.close(() => resolve()));
    await new Promise<void>(resolve => http.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  }
});
