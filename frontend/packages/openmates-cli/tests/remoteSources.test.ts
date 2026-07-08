/**
 * Unit tests for OpenMates Project remote source CLI client methods.
 *
 * Purpose: lock the encrypted /v1/projects/{id}/sources contract before the
 * remote bridge implementation starts using it.
 * Security: uses a local HTTP server and synthetic session only; source
 * metadata remains opaque ciphertext in the test payload.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/remoteSources.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient, type ProjectSourceCreateInput } from "../src/client.ts";
import type { OpenMatesSession } from "../src/storage.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const source: ProjectSourceCreateInput = {
  source_id: "source-1",
  source_type: "remote_git_repository",
  encrypted_display_name: "cipher-name",
  encrypted_metadata: "cipher-metadata",
  capabilities: ["read", "search", "import"],
  status: "connected",
  created_at: 100,
  updated_at: 100,
};

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

describe("OpenMatesClient Project sources", () => {
  it("lists and creates encrypted Project source records", async () => {
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { sources: [source] };
        return { source: { ...source, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.listProjectSources("project-1"))[0]?.source_id, "source-1");
        assert.equal((await client.createProjectSource("project-1", source)).encrypted_display_name, "cipher-name");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/projects/project-1/sources"],
          ["POST", "/v1/projects/project-1/sources"],
        ]);
        assert.deepEqual(seen[1]?.body, source);
      },
    );
  });
});
