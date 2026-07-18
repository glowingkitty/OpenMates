/**
 * Account Export V1 CLI client contract tests.
 *
 * Purpose: verify the CLI client uses the new resumable export job endpoints.
 * Architecture: docs/specs/account-export-v1/spec.yml.
 * Security: uses a fake local HTTP server and fake session, no real account data.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/account-export.test.ts
 */

import { after, describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

const originalHome = process.env.HOME;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-account-export-"));
process.env.HOME = tempHome;
mkdirSync(join(tempHome, ".openmates"), { recursive: true, mode: 0o700 });

const { OpenMatesClient } = await import("../src/client.ts");
const { assertAccountExportPayloadSafe, writeAccountExportArchive } = await import("../src/accountExportArchive.ts");

after(() => {
  if (originalHome === undefined) delete process.env.HOME;
  else process.env.HOME = originalHome;
  rmSync(tempHome, { recursive: true, force: true });
});

function writeSession(apiUrl: string): void {
  writeFileSync(join(tempHome, ".openmates", "session.json"), JSON.stringify({
    apiUrl,
    sessionId: "session-1",
    wsToken: "ws-token",
    cookies: { auth_refresh_token: "refresh-token" },
    masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    hashedEmail: "hashed-email",
    userEmailSalt: "email-salt",
    createdAt: Date.now(),
  }));
}

describe("account export client", () => {
  it("starts, reads, completes, and cancels export jobs through /v1/account-exports", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.on("data", (chunk) => { raw += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined });
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/account-exports") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "queued" } }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "queued" } }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/manifest") {
          response.end(JSON.stringify({ manifest: { export_id: "export-1" } }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks") {
          response.end(JSON.stringify({ chunks: [{ chunk_id: "chats-0001" }] }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-exports/export-1/chunks/chats-0001") {
          response.end(JSON.stringify({ chunk: { chunk_id: "chats-0001", payload: { items: [] } } }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-exports/export-1/complete") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "complete" } }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-exports/export-1/cancel") {
          response.end(JSON.stringify({ export: { export_id: "export-1", status: "cancelled" } }));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ detail: "not found" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeSession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      await client.startAccountExport({ domains: ["chats"], filters: { chats: { from: "2026-01-01" } } });
      await client.getAccountExport("export-1");
      await client.getAccountExportManifest("export-1");
      await client.listAccountExportChunks("export-1");
      await client.getAccountExportChunk("export-1", "chats-0001");
      await client.completeAccountExport("export-1");
      await client.cancelAccountExport("export-1");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      "POST /v1/account-exports",
      "GET /v1/account-exports/export-1",
      "GET /v1/account-exports/export-1/manifest",
      "GET /v1/account-exports/export-1/chunks",
      "GET /v1/account-exports/export-1/chunks/chats-0001",
      "POST /v1/account-exports/export-1/complete",
      "POST /v1/account-exports/export-1/cancel",
    ]);
    assert.deepEqual(requests[0].body, {
      domains: ["chats"],
      filters: { chats: { from: "2026-01-01" } },
      format: "zip",
      include_advanced_metadata: false,
    });
  });

  it("writes Account Export V1 directory layout without root checksums", async () => {
    const outputDir = join(tempHome, "account-export-layout");
    const result = await writeAccountExportArchive({
      export: { export_id: "export-1", status: "complete" },
      manifest: {
        export_id: "export-1",
        schema_version: "account-export-v1",
        selected_domains: ["chats"],
        filters: { chats: { from: "2026-01-01" } },
        report: { status: "complete", redactions: ["api_key", "refresh_token"], failures: [] },
      },
      chunks: [
        {
          chunk_id: "chats-0001",
          domain: "chats",
          sequence: 1,
          status: "ready",
          payload: {
            source: "chats",
            items: [
              {
                id: "chat-1",
                title: "Readable Chat",
                summary: "Short summary",
                messages: [{ role: "user", content: "Hello" }],
              },
            ],
          },
        },
      ],
    }, { output: outputDir, format: "directory" });

    assert.equal(result.format, "directory");
    assert.ok(existsSync(join(outputDir, "README.md")));
    assert.ok(existsSync(join(outputDir, "manifest.yml")));
    assert.ok(existsSync(join(outputDir, "export-report.yml")));
    assert.ok(existsSync(join(outputDir, "domains", "chats.json")));
    assert.ok(existsSync(join(outputDir, "chats", "chat-1.md")));
    assert.ok(existsSync(join(outputDir, "chats", "chat-1.yml")));
    assert.equal(existsSync(join(outputDir, "checksums.sha256")), false);
    assert.match(readFileSync(join(outputDir, "chats", "chat-1.md"), "utf-8"), /# Readable Chat/);
    assert.doesNotMatch(readFileSync(join(outputDir, "export-report.yml"), "utf-8"), /api_key|refresh_token/);
  });

  it("rejects forbidden credential fields before writing archive payloads", () => {
    assert.throws(
      () => assertAccountExportPayloadSafe({ payload: { api_key: "sk-api-secret-value" } }),
      /forbidden secret field 'api_key'/,
    );
  });
});
