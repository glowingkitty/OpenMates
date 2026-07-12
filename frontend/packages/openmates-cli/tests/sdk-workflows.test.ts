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
    ],
    edges: [],
  };
}

function templateImportPayload() {
  return {
    template_version: 1,
    title: "Morning",
    trigger_template: { type: "manual_trigger", config: {} },
    node_templates: [],
    edge_templates: [],
    variables_schema: {},
    required_capabilities: [],
    binding_requirements: [],
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
        if (request.url === "/v1/workflows/temporary" && request.method === "GET") {
          return { workflows: [{ id: "wf-temp", title: "Temporary", status: "disabled", enabled: false, lifecycle: "temporary", run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1 }] };
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
        if (request.url === "/v1/workflows/wf-1/template-projection") {
          assert.equal(request.method, "PUT");
          assert.deepEqual(body, {
            template_id: "tpl-1",
            source_version: 2,
            ciphertext: "opaque-ciphertext",
            ciphertext_checksum: "sha256:abc",
            owner_wrapped_key: "wrapped-key",
            projection_schema_version: 1,
          });
          return { template_id: "tpl-1", source_version: 2, updated_at: 123 };
        }
        if (request.url === "/v1/share/short-url") {
          assert.deepEqual(body, {
            token: "Abc123XY",
            encrypted_url: "opaque-url",
            content_type: "workflow_template",
            content_id: "tpl-1",
            password_protected: false,
            ttl_seconds: 3600,
          });
          return { success: true, expires_at: 999 };
        }
        if (request.url === "/v1/share/short-url/Abc123XY") {
          assert.equal(request.method, "DELETE");
          return { success: true, revoked_at: 1000 };
        }
        if (request.url === "/v1/workflows/template-import") {
          assert.deepEqual(body, templateImportPayload());
          return { workflow: { id: "wf-imported", title: "Morning", status: "disabled", enabled: false, current_version_id: "v1", created_at: 1, updated_at: 1, graph, binding_requirements: [] } };
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
        assert.equal((await client.workflows.temporary())[0]?.id, "wf-temp");
        assert.equal((await client.workflows.capabilities())[0]?.id, "weather:forecast");
        assert.equal((await client.workflows.create({ title: "Morning", graph, enabled: true, runContentRetention: "none", lifecycle: "temporary", source: "chat", sourceChatId: "chat-1", createdByAssistant: true })).run_content_retention, "none");
        assert.equal((await client.workflows.get("wf-1")).id, "wf-1");
        assert.equal((await client.workflows.update("wf-1", { enabled: false, runContentRetention: "last_5" })).id, "wf-1");
        assert.equal((await client.workflows.enable("wf-1")).enabled, true);
        assert.equal((await client.workflows.disable("wf-1")).id, "wf-1");
        assert.equal((await client.workflows.keep("wf-1")).id, "wf-1");
        assert.equal((await client.workflows.run("wf-1", { mode: "test", input: { dry: true } })).content_storage, "ephemeral");
        assert.equal((await client.workflows.runs("wf-1"))[0]?.content_storage, "durable");
        assert.equal((await client.workflows.runDetail("wf-1", "run-1")).id, "run-1");
        assert.equal((await client.workflows.upsertTemplateProjection("wf-1", { templateId: "tpl-1", sourceVersion: 2, ciphertext: "opaque-ciphertext", ciphertextChecksum: "sha256:abc", ownerWrappedKey: "wrapped-key", projectionSchemaVersion: 1 })).updated_at, 123);
        assert.equal((await client.workflows.createTemplateShortUrl({ token: "Abc123XY", encryptedUrl: "opaque-url", templateId: "tpl-1", ttlSeconds: 3600 })).expires_at, 999);
        assert.equal((await client.workflows.revokeShortUrl("Abc123XY")).revoked_at, 1000);
        assert.equal((await client.workflows.importTemplate(templateImportPayload())).id, "wf-imported");
        assert.equal((await client.workflows.delete("wf-1", { confirmed: true })).deleted, true);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/workflows"],
          ["GET", "/v1/workflows/temporary"],
          ["GET", "/v1/workflows/capabilities"],
          ["POST", "/v1/workflows"],
          ["GET", "/v1/workflows/wf-1"],
          ["PATCH", "/v1/workflows/wf-1"],
          ["POST", "/v1/workflows/wf-1/enable"],
          ["POST", "/v1/workflows/wf-1/disable"],
          ["POST", "/v1/workflows/wf-1/keep"],
          ["POST", "/v1/workflows/wf-1/run"],
          ["GET", "/v1/workflows/wf-1/runs"],
          ["GET", "/v1/workflows/wf-1/runs/run-1"],
          ["PUT", "/v1/workflows/wf-1/template-projection"],
          ["POST", "/v1/share/short-url"],
          ["DELETE", "/v1/share/short-url/Abc123XY"],
          ["POST", "/v1/workflows/template-import"],
          ["DELETE", "/v1/workflows/wf-1"],
        ]);
        assert.deepEqual(seen[3]?.body, { title: "Morning", graph, enabled: true, run_content_retention: "none", lifecycle: "temporary", source: "chat", source_chat_id: "chat-1", created_by_assistant: true });
      },
    );
  });

  it("manages durable workflow input sessions", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/workflows/input" && request.method === "POST") {
          assert.deepEqual(body, { text: "alert me if it rains", input_type: "text", selected_workflow_id: "wf-1" });
          return { session: { session_id: "session-1", status: "executed", event_cursor: 4, undo_available: true } };
        }
        if (request.url === "/v1/workflows/input/session-1" && request.method === "GET") {
          return { session: { session_id: "session-1", status: "executed", event_cursor: 4, undo_available: true, events: [] } };
        }
        if (request.url === "/v1/workflows/input/session-1/events?after_event_id=2") {
          return { events: [{ id: "event-3", session_id: "session-1", event_id: 3, type: "validation_passed", status: "ok", redacted_summary: "object:0", created_at: 1 }] };
        }
        if (request.url === "/v1/workflows/input/session-1/follow-up") {
          assert.deepEqual(body, { text: "weekdays only" });
          return { session: { session_id: "session-1", status: "executed", event_cursor: 7, undo_available: true } };
        }
        if (request.url === "/v1/workflows/input/session-1/stop") {
          return { session: { session_id: "session-1", status: "stopped", event_cursor: 8, undo_available: true } };
        }
        if (request.url === "/v1/workflows/input/session-1/undo") {
          return { session: { session_id: "session-1", status: "undone", event_cursor: 9, undo_available: false } };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.workflows.startInput({ text: "alert me if it rains", selectedWorkflowId: "wf-1" })).session_id, "session-1");
        assert.equal((await client.workflows.inputSession("session-1")).status, "executed");
        assert.equal((await client.workflows.inputEvents("session-1", 2))[0]?.type, "validation_passed");
        assert.equal((await client.workflows.followUpInput("session-1", "weekdays only")).event_cursor, 7);
        assert.equal((await client.workflows.stopInput("session-1")).status, "stopped");
        assert.equal((await client.workflows.undoInput("session-1")).status, "undone");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/workflows/input"],
          ["GET", "/v1/workflows/input/session-1"],
          ["GET", "/v1/workflows/input/session-1/events?after_event_id=2"],
          ["POST", "/v1/workflows/input/session-1/follow-up"],
          ["POST", "/v1/workflows/input/session-1/stop"],
          ["POST", "/v1/workflows/input/session-1/undo"],
        ]);
      },
    );
  });
});
