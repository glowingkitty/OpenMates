/**
 * OpenMates npm SDK contract tests.
 *
 * Purpose: verify lazy API-key SDK behavior before product implementation.
 * Architecture: docs/specs/sdk-packages-v1/spec.yml.
 * Security: tests cover API-key unwrap vectors and non-persistent default chats.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk.test.ts
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

describe("OpenMates SDK", () => {
  it("does not require connect before running an app skill", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/apps/web/skills/search");
      assert.equal(request.headers.authorization, "Bearer sk-api-test");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { results: [{ title: "ok" }] } }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const result = await client.apps.run("web", "search", {
        requests: [{ query: "hello" }],
      });
      assert.deepEqual(result, { success: true, data: { results: [{ title: "ok" }] } });
    });
  });

  it("defaults new chats to non-persistent mode", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.equal(JSON.parse(body).save_to_account, false);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ persistent: false, response: { content: "hi" } }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const chat = await client.chats.create();
      const response = await chat.send("hello");
      assert.equal(response.content, "hi");
    });
  });

  it("lists latest encrypted account chats with a limit", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats?limit=3");
      assert.equal(request.method, "GET");
      assert.equal(request.headers.authorization, "Bearer sk-api-test");
      assert.equal(request.headers["x-openmates-sdk"], "npm");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ chats: [{ id: "chat-1", encrypted_title: "ciphertext" }] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const chats = await client.chats.list({ limit: 3 });
      assert.deepEqual(chats, [{ id: "chat-1", encrypted_title: "ciphertext" }]);
    });
  });

  it("defaults chat listing to 10 and allows limit 0 for all chats", async () => {
    const urls: string[] = [];
    await withServer((request, response) => {
      urls.push(request.url ?? "");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ chats: [] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      await client.chats.list();
      await client.chats.list({ limit: 0 });
      assert.deepEqual(urls, ["/v1/sdk/chats?limit=10", "/v1/sdk/chats?limit=0"]);
    });
  });
});
