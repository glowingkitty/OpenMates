/**
 * Unit tests for OpenMates user task CLI client methods.
 *
 * Purpose: lock the shared encrypted /v1/user-tasks contract without a real API.
 * Security: uses a local HTTP server and synthetic session only; no account data
 * or task ciphertext leaves the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/tasks.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient, type UserTaskCreateInput } from "../src/client.ts";
import { findTask, type DecryptedUserTask } from "../src/tasksCli.ts";
import type { OpenMatesSession } from "../src/storage.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

function testSession(): OpenMatesSession {
  return {
    apiUrl: "http://127.0.0.1",
    sessionId: "session-1",
    wsToken: "x",
    cookies: { auth_refresh_token: "x" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
  };
}

function encryptedTaskInput(): UserTaskCreateInput {
  return {
    task_id: "task-1",
    encrypted_task_key: "cipher-key",
    encrypted_title: "cipher-title",
    encrypted_description: "cipher-description",
    encrypted_tags: "cipher-tags",
    status: "todo",
    assignee_type: "user",
    version: 1,
    linked_project_ids: ["project-1"],
    primary_chat_id: "chat-1",
    created_at: 100,
    updated_at: 100,
  };
}

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

describe("OpenMatesClient user tasks", () => {
  it("lists, creates, updates, and starts encrypted user tasks", async () => {
    const task = encryptedTaskInput();
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { tasks: [task] };
        return { task: { ...task, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.listUserTasks({ status: "todo", chatId: "chat-1", projectId: "project-1" }))[0]?.task_id, "task-1");
        assert.equal((await client.createUserTask(task)).encrypted_title, "cipher-title");
        assert.equal((await client.updateUserTask("task-1", { status: "done", version: 1 })).status, "done");
        assert.equal((await client.startUserTaskWithAI("task-1", {
          version: 2,
          plaintext_title: "Draft launch plan",
          plaintext_description: "Use project context",
        })).task_id, "task-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-tasks?status=todo&chat_id=chat-1&project_id=project-1"],
          ["POST", "/v1/user-tasks"],
          ["PATCH", "/v1/user-tasks/task-1"],
          ["POST", "/v1/user-tasks/task-1/start-ai"],
        ]);
        assert.deepEqual(seen[1]?.body, task);
        assert.deepEqual(seen[2]?.body, { status: "done", version: 1 });
        assert.deepEqual(seen[3]?.body, {
          version: 2,
          plaintext_title: "Draft launch plan",
          plaintext_description: "Use project context",
        });
      },
    );
  });

  it("rejects ambiguous short task IDs", () => {
    const tasks = [
      { taskId: "task-1", shortId: "TASK-1234" },
      { taskId: "task-2", shortId: "TASK-1234" },
    ] as DecryptedUserTask[];

    assert.throws(() => findTask(tasks, "TASK-1234"), /ambiguous/);
    assert.equal(findTask(tasks, "task-2").taskId, "task-2");
  });
});
