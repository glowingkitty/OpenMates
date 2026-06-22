/**
 * OpenMates npm SDK workflow contract tests.
 *
 * Purpose: verify API-key SDK workflow CRUD/run/history parity with CLI and pip.
 * Security: uses a local HTTP server and synthetic API key only; no real account
 * cookies, API keys, or workflow payloads leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-workflows.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

function minimalGraph() {
  return {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [
      { id: "trigger", type: "manual_trigger", config: {} },
      { id: "end", type: "end", config: {} },
    ],
    edges: [{ from: "trigger", to: "end" }],
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

describe("OpenMates SDK workflows", () => {
  it("manages workflows through the shared API contract", async () => {
    const graph = minimalGraph();
    await withServer(
      (request, body) => {
        if (request.url === "/v1/workflows" && request.method === "GET") {
          return { workflows: [{ id: "wf-1", title: "Morning", status: "disabled", enabled: false, run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1 }] };
        }
        if (request.url === "/v1/workflows/capabilities") {
          return { capabilities: [{ id: "weather:forecast", type: "app_skill", title: "Weather forecast", enabled: true }] };
        }
        if (request.url === "/v1/workflows/wf-1/runs") {
          return { runs: [{ id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [] }] };
        }
        if (request.url === "/v1/workflows/wf-1/runs/run-1") {
          return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [] } };
        }
        if (request.url === "/v1/workflows/wf-1/run") {
          assert.deepEqual(body, { mode: "test", input: { dry: true } });
          return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "test", status: "completed", content_retention_mode: "none", content_available: true, content_storage: "ephemeral", node_runs: [] } };
        }
        if (request.method === "DELETE") return { deleted: true };
        return { workflow: { id: "wf-1", title: "Morning", status: "active", enabled: true, run_content_retention: (body as any)?.run_content_retention ?? "last_5", current_version_id: "v1", created_at: 1, updated_at: 2, graph } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.workflows.list())[0]?.id, "wf-1");
        assert.equal((await client.workflows.capabilities())[0]?.id, "weather:forecast");
        assert.equal((await client.workflows.create({ title: "Morning", graph, enabled: true, runContentRetention: "none" })).run_content_retention, "none");
        assert.equal((await client.workflows.get("wf-1")).id, "wf-1");
        assert.equal((await client.workflows.update("wf-1", { enabled: false, runContentRetention: "last_5" })).id, "wf-1");
        assert.equal((await client.workflows.enable("wf-1")).enabled, true);
        assert.equal((await client.workflows.disable("wf-1")).id, "wf-1");
        assert.equal((await client.workflows.run("wf-1", { mode: "test", input: { dry: true } })).content_storage, "ephemeral");
        assert.equal((await client.workflows.runs("wf-1"))[0]?.content_storage, "durable");
        assert.equal((await client.workflows.runDetail("wf-1", "run-1")).id, "run-1");
        assert.equal((await client.workflows.delete("wf-1", { confirmed: true })).deleted, true);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/workflows"],
          ["GET", "/v1/workflows/capabilities"],
          ["POST", "/v1/workflows"],
          ["GET", "/v1/workflows/wf-1"],
          ["PATCH", "/v1/workflows/wf-1"],
          ["POST", "/v1/workflows/wf-1/enable"],
          ["POST", "/v1/workflows/wf-1/disable"],
          ["POST", "/v1/workflows/wf-1/run"],
          ["GET", "/v1/workflows/wf-1/runs"],
          ["GET", "/v1/workflows/wf-1/runs/run-1"],
          ["DELETE", "/v1/workflows/wf-1"],
        ]);
      },
    );
  });
});
