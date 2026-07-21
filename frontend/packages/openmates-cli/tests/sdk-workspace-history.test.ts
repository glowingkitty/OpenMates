/**
 * OpenMates workspace-history SDK contract tests.
 *
 * Purpose: verify list/show/undo helpers hit the shared history API.
 * Architecture: docs/specs/workspace-change-history/spec.yml.
 * Security: responses are metadata-only; no plaintext workspace content is used.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-workspace-history.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const { OpenMates } = await import("../src/sdk.ts");

async function withServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void,
  run: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMates workspace history SDK", () => {
  it("lists, shows, and undoes workspace change sets", async () => {
    const seen: Array<{ method?: string; url?: string; body?: unknown }> = [];
    await withServer((request, response) => {
      seen.push({ method: request.method, url: request.url });
      assert.equal(request.headers.authorization, "Bearer sk-api-test");
      assert.equal(request.headers["x-openmates-sdk"], "npm");
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
        let raw = "";
        request.setEncoding("utf8");
        request.on("data", (chunk) => { raw += chunk; });
        request.on("end", () => {
          seen[seen.length - 1].body = JSON.parse(raw || "{}");
          response.end(JSON.stringify({ undone: true, change_set_id: "undo-1" }));
        });
        return;
      }

      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: `unexpected ${request.method} ${request.url}` }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "device-1" });
      assert.deepEqual(await client.history.list({ objectType: "task", objectId: "task-1", limit: 5 }), [{ change_set_id: "cs-1" }]);
      assert.deepEqual(await client.history.show("cs-1"), { change_set: { change_set_id: "cs-1" }, entries: [] });
      assert.deepEqual(await client.history.undo("cs-1"), { undone: true, change_set_id: "undo-1" });
    });

    assert.deepEqual(seen.map((request) => [request.method, request.url]), [
      ["GET", "/v1/workspace/history?object_type=task&object_id=task-1&limit=5"],
      ["GET", "/v1/workspace/history/cs-1"],
      ["POST", "/v1/workspace/history/cs-1/undo"],
    ]);
    assert.deepEqual(seen.at(-1)?.body, {});
  });

  it("uses namespace-specific object history and restore endpoints", async () => {
    const seen: Array<{ method?: string; url?: string; body?: unknown }> = [];
    await withServer((request, response) => {
      seen.push({ method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      if (request.method === "GET" && request.url === "/v1/projects/project-1/history?limit=3") {
        response.end(JSON.stringify({ entries: [{ entry_id: "che-project" }] }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/workflows/wf-1/restore") {
        let raw = "";
        request.setEncoding("utf8");
        request.on("data", (chunk) => { raw += chunk; });
        request.on("end", () => {
          seen[seen.length - 1].body = JSON.parse(raw || "{}");
          response.end(JSON.stringify({ workflow: { id: "wf-1" }, history: { change_set: { change_set_id: "cs-restore" } } }));
        });
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: `unexpected ${request.method} ${request.url}` }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "device-1" });
      assert.deepEqual(await client.projects.history("project-1", { limit: 3 }), [{ entry_id: "che-project" }]);
      assert.deepEqual(await client.workflows.restore("wf-1", { entryId: "che-workflow", state: "before" }), {
        workflow: { id: "wf-1" },
        history: { change_set: { change_set_id: "cs-restore" } },
      });
    });

    assert.deepEqual(seen.map((request) => [request.method, request.url]), [
      ["GET", "/v1/projects/project-1/history?limit=3"],
      ["POST", "/v1/workflows/wf-1/restore"],
    ]);
    assert.deepEqual(seen.at(-1)?.body, { entry_id: "che-workflow", state: "before" });
  });

  it("uses namespace-specific ask endpoints with encrypted create payloads", async () => {
    const seen: Array<{ method?: string; url?: string; body?: unknown }> = [];
    await withServer((request, response) => {
      seen.push({ method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      if (request.method === "POST" && (request.url === "/v1/user-tasks/ask" || request.url === "/v1/projects/ask" || request.url === "/v1/workflows/ask")) {
        let raw = "";
        request.setEncoding("utf8");
        request.on("data", (chunk) => { raw += chunk; });
        request.on("end", () => {
          seen[seen.length - 1].body = JSON.parse(raw || "{}");
          response.end(JSON.stringify({ applied: true, change_set_id: "chg-ask", changed_entries: [] }));
        });
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: `unexpected ${request.method} ${request.url}` }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "device-1" });
      assert.deepEqual(await client.tasks.ask({ instruction: "Prepare launch", encryptedCreate: { task_id: "task-1" } }), { applied: true, change_set_id: "chg-ask", changed_entries: [] });
      assert.deepEqual(await client.projects.ask({ instruction: "Launch", encryptedCreate: { project_id: "project-1" } }), { applied: true, change_set_id: "chg-ask", changed_entries: [] });
      assert.deepEqual(await client.workflows.ask({ instruction: "Rain alert", create: { title: "Rain alert" } }), { applied: true, change_set_id: "chg-ask", changed_entries: [] });
    });

    assert.deepEqual(seen.map((request) => [request.method, request.url]), [
      ["POST", "/v1/user-tasks/ask"],
      ["POST", "/v1/projects/ask"],
      ["POST", "/v1/workflows/ask"],
    ]);
    assert.deepEqual(seen[0]?.body, { instruction: "Prepare launch", apply_mode: "auto_apply", encrypted_create: { task_id: "task-1" } });
    assert.deepEqual(seen[1]?.body, { instruction: "Launch", apply_mode: "auto_apply", encrypted_create: { project_id: "project-1" } });
    assert.deepEqual(seen[2]?.body, { instruction: "Rain alert", apply_mode: "auto_apply", create: { title: "Rain alert" } });
  });
});
