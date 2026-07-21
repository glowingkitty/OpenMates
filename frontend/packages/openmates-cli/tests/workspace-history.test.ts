/**
 * OpenMates workspace history CLI-client contract tests.
 *
 * Purpose: lock the CLI transport used by namespace history, restore, and ask
 * commands without a real API server.
 * Architecture: docs/specs/workspace-change-history/spec.yml.
 * Security: local HTTP mock only; payloads use synthetic ciphertext markers.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/workspace-history.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient, type OpenMatesSession, type UserPlanCreateInput, type UserTaskCreateInput } from "../src/client.ts";

type SeenRequest = { method?: string; url?: string; body?: unknown };

function testSession(apiUrl: string): OpenMatesSession {
  return {
    apiUrl,
    sessionId: "session-1",
    wsToken: "ws-token",
    cookies: { auth_refresh_token: "refresh-token" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
  };
}

async function withServer(
  handler: (request: IncomingMessage, response: ServerResponse, seen: SeenRequest[]) => void,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request, response) => handler(request, response, seen));
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

function readJsonBody(request: IncomingMessage, onBody: (body: unknown) => void): void {
  let raw = "";
  request.setEncoding("utf8");
  request.on("data", (chunk) => { raw += chunk; });
  request.on("end", () => onBody(raw ? JSON.parse(raw) : {}));
}

function encryptedTaskCreate(): UserTaskCreateInput {
  return {
    task_id: "task-1",
    encrypted_task_key: "cipher-task-key",
    encrypted_title: "cipher-title",
    encrypted_description: "cipher-description",
    encrypted_tags: "cipher-tags",
    status: "todo",
    assignee_type: "user",
    version: 1,
  };
}

function encryptedPlanCreate(): UserPlanCreateInput {
  return {
    plan_id: "plan-1",
    encrypted_plan_key: "cipher-plan-key",
    encrypted_title: "cipher-title",
    encrypted_goal: "cipher-goal",
    status: "draft",
    version: 1,
  };
}

describe("OpenMatesClient workspace history", () => {
  it("uses global and namespace-specific history endpoints", async () => {
    await withServer((request, response, seen) => {
      seen.push({ method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      if (request.method === "GET" && request.url === "/v1/workspace/history?object_type=task&object_id=task-1&limit=5") {
        response.end(JSON.stringify({ change_sets: [{ change_set_id: "cs-1" }] }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/workspace/history/cs-1") {
        response.end(JSON.stringify({ change_set: { change_set_id: "cs-1" }, entries: [] }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/workspace/history/cs-1/undo") {
        readJsonBody(request, (body) => {
          seen[seen.length - 1].body = body;
          response.end(JSON.stringify({ undone: true, change_set_id: "cs-undo" }));
        });
        return;
      }
      if (request.method === "GET" && request.url === "/v1/user-plans/plan-1/history?limit=3") {
        response.end(JSON.stringify({ entries: [{ entry_id: "entry-1" }] }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/projects/project-1/restore") {
        readJsonBody(request, (body) => {
          seen[seen.length - 1].body = body;
          response.end(JSON.stringify({ history: { change_set: { change_set_id: "cs-restore" } } }));
        });
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: `unexpected ${request.method} ${request.url}` }));
    }, async (apiUrl, seen) => {
      const client = new OpenMatesClient({ apiUrl, session: testSession(apiUrl) });

      assert.deepEqual(await client.listWorkspaceHistory({ objectType: "task", objectId: "task-1", limit: 5 }), [{ change_set_id: "cs-1" }]);
      assert.deepEqual(await client.getWorkspaceHistory("cs-1"), { change_set: { change_set_id: "cs-1" }, entries: [] });
      assert.deepEqual(await client.undoWorkspaceHistory("cs-1"), { undone: true, change_set_id: "cs-undo" });
      assert.deepEqual(await client.listObjectHistory("plan", "plan-1", 3), [{ entry_id: "entry-1" }]);
      assert.deepEqual(await client.restoreObjectHistory("project", "project-1", "entry-1", "before"), { history: { change_set: { change_set_id: "cs-restore" } } });

      assert.deepEqual(seen.map((request) => [request.method, request.url]), [
        ["GET", "/v1/workspace/history?object_type=task&object_id=task-1&limit=5"],
        ["GET", "/v1/workspace/history/cs-1"],
        ["POST", "/v1/workspace/history/cs-1/undo"],
        ["GET", "/v1/user-plans/plan-1/history?limit=3"],
        ["POST", "/v1/projects/project-1/restore"],
      ]);
      assert.deepEqual(seen[2]?.body, {});
      assert.deepEqual(seen[4]?.body, { entry_id: "entry-1", state: "before" });
    });
  });

  it("uses namespace-specific ask endpoints", async () => {
    await withServer((request, response, seen) => {
      seen.push({ method: request.method, url: request.url });
      if (request.method === "POST") {
        readJsonBody(request, (body) => {
          seen[seen.length - 1].body = body;
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            applied: true,
            change_set_id: "cs-ask",
            undo_all_command: "openmates history undo cs-ask",
            undo_entry_commands: ["openmates tasks restore task-1 --entry entry-1 --state before"],
          }));
        });
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: `unexpected ${request.method} ${request.url}` }));
    }, async (apiUrl, seen) => {
      const client = new OpenMatesClient({ apiUrl, session: testSession(apiUrl) });

      const taskAsk = await client.askUserTasks({ instruction: "Prepare launch", encryptedCreate: encryptedTaskCreate() });
      assert.equal(taskAsk.change_set_id, "cs-ask");
      assert.equal(taskAsk.undo_all_command, "openmates history undo cs-ask");
      assert.deepEqual(taskAsk.undo_entry_commands, ["openmates tasks restore task-1 --entry entry-1 --state before"]);
      assert.equal((await client.askUserPlans({ instruction: "Launch plan", applyMode: "confirm_first", encryptedCreate: encryptedPlanCreate() })).change_set_id, "cs-ask");
      assert.equal((await client.askProject({ instruction: "Launch", encryptedCreate: { project_id: "project-1", encrypted_name: "cipher-name" } })).change_set_id, "cs-ask");
      assert.equal((await client.askWorkflow({ instruction: "Rain alert", create: { title: "Rain alert" } })).change_set_id, "cs-ask");

      assert.deepEqual(seen.map((request) => [request.method, request.url]), [
        ["POST", "/v1/user-tasks/ask"],
        ["POST", "/v1/user-plans/ask"],
        ["POST", "/v1/projects/ask"],
        ["POST", "/v1/workflows/ask"],
      ]);
      assert.deepEqual(seen[0]?.body, { instruction: "Prepare launch", apply_mode: "auto_apply", encrypted_create: encryptedTaskCreate() });
      assert.deepEqual(seen[1]?.body, { instruction: "Launch plan", apply_mode: "confirm_first", encrypted_create: encryptedPlanCreate() });
      assert.deepEqual(seen[2]?.body, { instruction: "Launch", apply_mode: "auto_apply", encrypted_create: { project_id: "project-1", encrypted_name: "cipher-name" } });
      assert.deepEqual(seen[3]?.body, { instruction: "Rain alert", apply_mode: "auto_apply", create: { title: "Rain alert" } });
    });
  });
});
