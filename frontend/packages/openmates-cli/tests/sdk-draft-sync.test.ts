/** npm SDK read-only encrypted draft access contract tests. */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";

const { OpenMates } = await import("../src/sdk.ts");

describe("npm SDK drafts", () => {
  it("lists and loads encrypted drafts without exposing mutation methods", async () => {
    const requests: Array<{ method?: string; url?: string; body: string }> = [];
    const server = createServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.url === "/v1/sdk/session") {
          response.end(JSON.stringify({ key_wrapper: {} }));
        } else if (request.method === "GET" && request.url === "/v1/sdk/drafts") {
          response.end(JSON.stringify({ drafts: [{ chat_id: "chat-1", encrypted_draft_md: "cipher-1", draft_v: 2 }] }));
        } else if (request.method === "GET" && request.url === "/v1/sdk/drafts/chat-1") {
          response.end(JSON.stringify({ draft: { chat_id: "chat-1", encrypted_draft_md: "cipher-1", draft_v: 2 } }));
        } else {
          response.end(JSON.stringify({ draft: null }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: `http://127.0.0.1:${address.port}` });
      assert.equal((await client.drafts.listEncrypted())[0]?.chatId, "chat-1");
      assert.equal((await client.drafts.getEncrypted("chat-1"))?.draftV, 2);
      assert.equal("create" in client.drafts, false);
      assert.equal("clear" in client.drafts, false);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.filter((request) => request.url !== "/v1/sdk/session").map(({ method, url }) => ({ method, url })), [
      { method: "GET", url: "/v1/sdk/drafts" },
      { method: "GET", url: "/v1/sdk/drafts/chat-1" },
    ]);
    assert.equal(requests.some((request) => request.body.includes("draft plaintext")), false);
  });
});
