/**
 * OpenMates npm SDK user task contract tests.
 *
 * Purpose: verify API-key SDK task CRUD/start parity with CLI and pip.
 * Security: uses a local HTTP server and synthetic API key only; no task data or
 * API keys leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-tasks.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const task = {
  task_id: "task-1",
  encrypted_task_key: "cipher-key",
  encrypted_title: "cipher-title",
  status: "todo" as const,
  assignee_type: "user" as const,
  created_at: 100,
  updated_at: 100,
};

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      assert.equal(request.headers.authorization, "Bearer x");
      assert.equal(request.headers["x-openmates-sdk"], "npm");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(handler(request, body)));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMates SDK user tasks", () => {
  it("manages encrypted tasks through the shared API contract", async () => {
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { tasks: [task] };
        return { task: { ...task, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.tasks.list({ status: "todo", chatId: "chat-1" }))[0]?.task_id, "task-1");
        assert.equal((await client.tasks.create(task)).encrypted_title, "cipher-title");
        assert.equal((await client.tasks.update("task-1", { status: "done", version: 1 })).status, "done");
        assert.equal((await client.tasks.startAI("task-1", {
          version: 2,
          plaintext_title: "Draft launch plan",
        })).task_id, "task-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-tasks?status=todo&chat_id=chat-1"],
          ["POST", "/v1/user-tasks"],
          ["PATCH", "/v1/user-tasks/task-1"],
          ["POST", "/v1/user-tasks/task-1/start-ai"],
        ]);
        assert.deepEqual(seen[1]?.body, task);
        assert.deepEqual(seen[3]?.body, {
          version: 2,
          plaintext_title: "Draft launch plan",
        });
      },
    );
  });
});
