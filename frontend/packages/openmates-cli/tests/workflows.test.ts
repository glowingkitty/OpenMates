/**
 * Unit tests for OpenMates workflow CLI/SDK client methods.
 *
 * Purpose: lock the shared npm SDK contract for workflow CRUD/run/history.
 * Security: uses a local HTTP server and synthetic session only; no real account
 * cookies, API keys, or workflow payloads leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/workflows.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { OpenMatesClient, type WorkflowGraph } from "../src/client.ts";
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

function minimalGraph(): WorkflowGraph {
  return {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [
      { id: "trigger", type: "manual_trigger", config: {} },
    ],
    edges: [],
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
    request.on("data", (chunk) => {
      raw += chunk;
    });
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

describe("OpenMatesClient workflows", () => {
  it("creates, lists, and updates workflows through typed endpoints", async () => {
    const graph = minimalGraph();
    await withServer(
      (request) => {
        if (request.method === "GET") {
          return {
            workflows: [
              { id: "wf-1", title: "Morning", status: "disabled", enabled: false, run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1 },
            ],
          };
        }
        return {
          workflow: { id: "wf-1", title: "Morning", status: "active", enabled: true, run_content_retention: "none", current_version_id: "v1", created_at: 1, updated_at: 2, graph },
        };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.listWorkflows())[0]?.id, "wf-1");
        assert.equal((await client.listTemporaryWorkflows())[0]?.id, "wf-1");
        assert.equal((await client.createWorkflow({ title: "Morning", graph, enabled: true, runContentRetention: "none", lifecycle: "temporary", source: "chat", sourceChatId: "chat-1", createdByAssistant: true })).enabled, true);
        assert.equal((await client.updateWorkflow("wf-1", { enabled: false, runContentRetention: "last_5" })).id, "wf-1");
        assert.equal((await client.keepWorkflow("wf-1")).id, "wf-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/workflows"],
          ["GET", "/v1/workflows/temporary"],
          ["POST", "/v1/workflows"],
          ["PATCH", "/v1/workflows/wf-1"],
          ["POST", "/v1/workflows/wf-1/keep"],
        ]);
        assert.deepEqual(seen[2]?.body, { title: "Morning", graph, enabled: true, run_content_retention: "none", lifecycle: "temporary", source: "chat", source_chat_id: "chat-1", created_by_assistant: true });
        assert.deepEqual(seen[3]?.body, { enabled: false, run_content_retention: "last_5" });
      },
    );
  });

  it("runs workflows and reads run history", async () => {
    await withServer(
      (request) => {
        if (request.url === "/v1/workflows/wf-1/runs") {
          return { runs: [{ id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable" }] };
        }
        return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [] } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.runWorkflow("wf-1", { mode: "test", input: { dry: true } })).id, "run-1");
        assert.equal((await client.listWorkflowRuns("wf-1"))[0]?.id, "run-1");
        assert.equal((await client.getWorkflowRun("wf-1", "run-1")).status, "completed");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/workflows/wf-1/run"],
          ["GET", "/v1/workflows/wf-1/runs"],
          ["GET", "/v1/workflows/wf-1/runs/run-1"],
        ]);
        assert.deepEqual(seen[0]?.body, { mode: "test", input: { dry: true } });
      },
    );
  });

  it("manages durable workflow input sessions", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/workflows/input" && request.method === "POST") {
          assert.deepEqual(body, { text: "alert me if it rains", input_type: "text", selected_project_id: "project-1" });
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
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.startWorkflowInput({ text: "alert me if it rains", selectedProjectId: "project-1" })).session_id, "session-1");
        assert.equal((await client.getWorkflowInputSession("session-1")).status, "executed");
        assert.equal((await client.listWorkflowInputEvents("session-1", 2))[0]?.type, "validation_passed");
        assert.equal((await client.followUpWorkflowInput("session-1", "weekdays only")).event_cursor, 7);
        assert.equal((await client.stopWorkflowInput("session-1")).status, "stopped");
        assert.equal((await client.undoWorkflowInput("session-1")).status, "undone");

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

  it("requires a CLI session before workflow calls", async () => {
    const originalHome = process.env.HOME;
    const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-workflows-no-session-"));
    process.env.HOME = tempHome;
    try {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
      await assert.rejects(() => client.listWorkflows(), /Not logged in/);
    } finally {
      if (originalHome === undefined) {
        delete process.env.HOME;
      } else {
        process.env.HOME = originalHome;
      }
      rmSync(tempHome, { recursive: true, force: true });
    }
  });
});
