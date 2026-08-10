/**
 * Account Export V1 npm SDK contract tests.
 *
 * Purpose: keep SDK export helpers aligned with the CLI/backend job contract.
 * Architecture: docs/specs/account-export-v1/spec.yml.
 * Security: uses a fake local API and never touches real credentials.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/account-export-sdk.test.ts
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

describe("OpenMates account export SDK", () => {
  it("starts, iterates, and completes export jobs through the shared endpoint", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
    await withServer((request, response) => {
      let raw = "";
      request.on("data", (chunk) => { raw += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined });
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/account-exports") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "queued" } }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/manifest") {
          response.end(JSON.stringify({ manifest: { selected_domains: ["chats"], report: { redactions: ["api_key"], failures: [] } } }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks") {
          response.end(JSON.stringify({ chunks: [{ chunk_id: "chats-0001" }] }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks/chats-0001") {
          response.end(JSON.stringify({ chunk: { chunk_id: "chats-0001", domain: "chats", payload: { items: [{ id: "chat-1" }] } } }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-exports/export-1/complete") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "complete" } }));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ detail: "not found" }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "device-1" });
      const bundle = await client.account.downloadExport({ domains: ["chats"] });
      assert.equal((bundle.export as Record<string, unknown>).status, "complete");
      assert.deepEqual(((bundle.manifest as Record<string, unknown>).report as Record<string, unknown>).redactions, [
        "api_credentials",
        "authentication_tokens",
        "key_material",
        "password_and_recovery_hashes",
        "webhook_secrets",
      ]);
      assert.deepEqual((bundle.chunks as Array<Record<string, unknown>>)[0].payload, { items: [{ id: "chat-1" }] });
      const chunks: Array<Record<string, unknown>> = [];
      for await (const chunk of client.account.iterExportChunks("export-1")) chunks.push(chunk);
      assert.equal(chunks[0].chunk_id, "chats-0001");
    });

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      "POST /v1/account-exports",
      "GET /v1/account-exports/export-1/manifest",
      "GET /v1/account-exports/export-1/chunks",
      "GET /v1/account-exports/export-1/chunks/chats-0001",
      "POST /v1/account-exports/export-1/complete",
      "GET /v1/account-exports/export-1/chunks",
      "GET /v1/account-exports/export-1/chunks/chats-0001",
    ]);
    assert.deepEqual(requests[0].body, {
      domains: ["chats"],
      filters: {},
      format: "zip",
      include_advanced_metadata: false,
    });
  });

  it("cancels SDK export jobs when a downloaded chunk contains forbidden secrets", async () => {
    const requests: string[] = [];
    await withServer((request, response) => {
      requests.push(`${request.method} ${request.url}`);
      response.setHeader("content-type", "application/json");
      if (request.method === "POST" && request.url === "/v1/account-exports") {
        response.end(JSON.stringify({ export: { export_id: "export-1", status: "queued" } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/account-exports/export-1/manifest") {
        response.end(JSON.stringify({ manifest: { selected_domains: ["connected_account_overview"] } }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks") {
        response.end(JSON.stringify({ chunks: [{ chunk_id: "connected-0001" }] }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks/connected-0001") {
        response.end(JSON.stringify({ chunk: { chunk_id: "connected-0001", payload: { api_key: "sk-api-secret-value" } } }));
        return;
      }
      if (request.method === "POST" && request.url === "/v1/account-exports/export-1/cancel") {
        response.end(JSON.stringify({ export: { export_id: "export-1", status: "cancelled" } }));
        return;
      }
      response.statusCode = 404;
      response.end(JSON.stringify({ detail: "not found" }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "device-1" });
      await assert.rejects(() => client.account.downloadExport({ domains: ["connected_account_overview"] }), /forbidden secret field 'api_key'/);
    });

    assert.ok(requests.includes("POST /v1/account-exports/export-1/cancel"));
    assert.ok(!requests.includes("POST /v1/account-exports/export-1/complete"));
  });
});
