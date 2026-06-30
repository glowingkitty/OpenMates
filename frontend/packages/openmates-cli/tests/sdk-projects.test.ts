/**
 * OpenMates npm SDK Project source contract tests.
 *
 * Purpose: verify API-key SDK parity for encrypted Project source create/list.
 * Security: uses a local HTTP server and synthetic API key only; source metadata
 * is opaque ciphertext and no API keys leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-projects.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates, type ProjectSourceCreateInput } from "../src/sdk.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const source: ProjectSourceCreateInput = {
  source_id: "source-1",
  source_type: "remote_git_repository",
  encrypted_display_name: "cipher-name",
  encrypted_metadata: "cipher-metadata",
  capabilities: ["read", "search"],
  status: "connected",
  created_at: 100,
  updated_at: 100,
};

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

describe("OpenMates SDK Project sources", () => {
  it("manages encrypted Project sources through the shared API contract", async () => {
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { sources: [source] };
        return { source: { ...source, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.projects.listSources("project-1"))[0]?.source_id, "source-1");
        assert.equal((await client.projects.createSource("project-1", source)).encrypted_display_name, "cipher-name");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/projects/project-1/sources"],
          ["POST", "/v1/projects/project-1/sources"],
        ]);
        assert.deepEqual(seen[1]?.body, source);
      },
    );
  });
});
