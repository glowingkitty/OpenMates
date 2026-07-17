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
import { createApiKeyCryptoMaterial } from "../src/crypto.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
  expectedAuthorization = "Bearer x",
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      assert.equal(request.headers.authorization, expectedAuthorization);
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
  it("exposes task app-skill child embeds and pending client search state", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/apps/tasks/skills/create") {
          assert.deepEqual(body, {
            tasks: [{ title: "Draft checklist" }],
          });
          return {
            success: true,
            data: {
              success: true,
              app_id: "tasks",
              skill_id: "create",
              parent_embed_id: "app-skill-use-1",
              result_count: 1,
              results: [
                {
                  type: "task",
                  parent_app_skill_type: "app_skill_use",
                  child_embed_id: "task-embed-1",
                  task_id: "task-1",
                  short_id: "TASK-1",
                  title: "Draft checklist",
                  status: "todo",
                  assignee: "user",
                },
              ],
            },
          };
        }
        if (request.url === "/v1/apps/tasks/skills/search") {
          assert.deepEqual(body, {
            query: "checklist",
          });
          return {
            success: true,
            data: {
              success: true,
              app_id: "tasks",
              skill_id: "search",
              status: "waiting_for_client",
              requires_connected_client: true,
              pending_client_search: { request_id: "task-search-1", notification_queued: true },
              result_count: 0,
              results: [],
            },
          };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        const created = await client.apps.tasks.create<Record<string, any>>({
          tasks: [{ title: "Draft checklist" }],
        });
        const search = await client.apps.tasks.search<Record<string, any>>({ query: "checklist" });

        assert.equal(created.data.app_id, "tasks");
        assert.equal(created.data.parent_embed_id, "app-skill-use-1");
        assert.equal(created.data.results[0].parent_app_skill_type, "app_skill_use");
        assert.equal(created.data.results[0].child_embed_id, "task-embed-1");
        assert.equal(created.data.results[0].task_id, "task-1");
        assert.equal(search.data.status, "waiting_for_client");
        assert.equal(search.data.requires_connected_client, true);
        assert.deepEqual(search.data.results, []);
        assert.equal(search.data.pending_client_search.request_id, "task-search-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/apps/tasks/skills/create"],
          ["POST", "/v1/apps/tasks/skills/search"],
        ]);
      },
    );
  });

  it("manages decrypted tasks through API-key master-key recovery", async () => {
    const masterKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk task parity", masterKey.toString("base64"));
    const seen: SeenRequest[] = [];
    let storedTask: Record<string, any> | null = null;

    await withServer(
      (request, body) => {
        seen.push({ method: request.method, url: request.url, body });
        if (request.url === "/v1/sdk/session") {
          return {
            key_wrapper: {
              encrypted_key: material.encryptedMasterKey,
              salt: material.saltB64,
              key_iv: material.keyIv,
            },
          };
        }
        if (request.method === "GET" && request.url?.startsWith("/v1/user-tasks")) {
          return { tasks: storedTask ? [storedTask] : [] };
        }
        if (request.method === "POST" && request.url === "/v1/user-tasks") {
          assert.equal(typeof (body as Record<string, unknown>).encrypted_title, "string");
          assert.equal(typeof (body as Record<string, unknown>).encrypted_labels, "string");
          assert.equal(Array.isArray((body as Record<string, unknown>).label_hashes), true);
          assert.equal(((body as Record<string, unknown>).label_hashes as string[]).length, 2);
          assert.equal((body as Record<string, unknown>).priority, 3);
          assert.equal((body as Record<string, unknown>).title, undefined);
          assert.equal((body as Record<string, unknown>).labels, undefined);
          storedTask = { ...(body as Record<string, any>), short_id: "TASK-1" };
          return { task: storedTask };
        }
        if (request.method === "PATCH" && request.url?.startsWith("/v1/user-tasks/")) {
          if ((body as Record<string, unknown>).label_hashes) {
            assert.equal(((body as Record<string, unknown>).label_hashes as string[]).length, 2);
            assert.equal((body as Record<string, unknown>).priority, 4);
          }
          storedTask = { ...storedTask, ...(body as Record<string, any>) };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url?.endsWith("/start-ai")) {
          assert.equal(typeof (body as Record<string, any>).plaintext_title, "string");
          storedTask = { ...storedTask, status: "in_progress", ai_execution_state: "running" };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url?.endsWith("/block")) {
          storedTask = { ...storedTask, status: "blocked", blocked_reason_code: (body as Record<string, any>).blocked_reason_code };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url?.endsWith("/unblock")) {
          storedTask = { ...storedTask, status: "todo", blocked_reason_code: null };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url?.endsWith("/skip")) {
          storedTask = { ...storedTask, status: "backlog", queue_state: "skipped", ai_execution_state: "skipped" };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url?.endsWith("/complete")) {
          storedTask = { ...storedTask, status: "done" };
          return { task: storedTask };
        }
        if (request.method === "POST" && request.url === "/v1/user-tasks/reorder") {
          const move = (body as Record<string, any>).moves[0];
          storedTask = { ...storedTask, position: move.position, status: move.status ?? storedTask?.status };
          return { tasks: [storedTask] };
        }
        if (request.method === "DELETE" && request.url?.startsWith("/v1/user-tasks/")) {
          storedTask = null;
          return { deleted: true, task_id: "deleted-task" };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        const created = await client.tasks.create({ title: "SDK parity task", description: "Plain task body", labels: ["SDK", "Urgent"], priority: "high", assign: "user" });
        assert.equal(created.title, "SDK parity task");
        assert.deepEqual(created.labels, ["sdk", "urgent"]);
        assert.equal(created.priority, 3);
        assert.equal(created.priorityLevel, "high");
        assert.equal("encrypted" in created, false);

        const listed = await client.tasks.listDecrypted({ labels: ["sdk", "urgent"], priority: "high" });
        assert.equal(listed[0]?.title, "SDK parity task");

        const edited = await client.tasks.edit("TASK-1", { title: "SDK parity task edited", status: "in_progress", addLabels: ["docs"], removeLabels: ["urgent"], priority: "urgent" });
        assert.equal(edited.title, "SDK parity task edited");
        assert.equal(edited.status, "in_progress");
        assert.deepEqual(edited.labels, ["sdk", "docs"]);
        assert.equal(edited.priorityLevel, "urgent");

        assert.equal((await client.tasks.startAI("TASK-1")).status, "in_progress");
        assert.equal((await client.tasks.block("TASK-1", "needs_input")).status, "blocked");
        assert.equal((await client.tasks.unblock("TASK-1")).status, "todo");
        assert.equal((await client.tasks.skip("TASK-1")).queueState, "skipped");
        assert.equal((await client.tasks.done("TASK-1")).status, "done");
        assert.equal((await client.tasks.move("TASK-1", { position: 42, status: "todo" }))[0]?.position, 42);
        assert.equal((await client.tasks.delete("TASK-1", { confirmed: true })).deleted, true);
      },
      `Bearer ${material.apiKey}`,
    );

    assert.ok(seen.some((request) => request.url === "/v1/sdk/session"), "SDK session wrapper was not requested");
    assert.ok(seen.some((request) => request.url?.startsWith("/v1/user-tasks?") && request.url.includes("priority=3") && (request.url.match(/label_hash=/g) ?? []).length === 2));
  });
});
