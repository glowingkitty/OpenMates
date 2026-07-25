/**
 * OpenMates npm SDK Project contract tests.
 *
 * Purpose: verify API-key SDK Project listing and plain encrypted Project links.
 * Security: uses a local HTTP server and synthetic API key only; no API keys or
 * Project ciphertext leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-projects.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";
import { createApiKeyCryptoMaterial, decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../src/crypto.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
  expectedAuthorization = "Bearer x",
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      assert.equal(request.headers.authorization, expectedAuthorization);
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

describe("OpenMates SDK Projects", () => {
  it("links chats and workflows as OpenMates-only encrypted Project items", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const projectKey = Buffer.alloc(32, 8);
    const chatKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk project links", masterKey.toString("base64"));
    const encryptedProjectKey = await encryptBytesWithAesGcm(projectKey, masterKey);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedTitle = await encryptWithAesGcmCombined("Planning Chat", chatKey);
    const workflow = {
      id: "workflow-1",
      title: "Release Workflow",
      description: "Ship safely",
      status: "draft",
      enabled: false,
      current_version_id: "version-1",
      created_at: 100,
      updated_at: 200,
      graph: { version: 1, nodes: [], edges: [] },
    };

    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === "/v1/projects?include_archived=true") {
          return { projects: [{ project_id: "project-1", encrypted_project_key: encryptedProjectKey }] };
        }
        if (request.method === "GET" && request.url === "/v1/projects?include_archived=false") {
          return { projects: [{ project_id: "project-1" }] };
        }
        if (request.method === "GET" && request.url === "/v1/sdk/chats/chat-1") {
          return { chat: { id: "chat-1", encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle, updated_at: 200 }, messages: [] };
        }
        if (request.method === "GET" && request.url === "/v1/workflows/workflow-1") return { workflow };
        if (request.method === "POST" && request.url === "/v1/projects/project-1/items") return { item: { ...(body as Record<string, unknown>) } };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        assert.equal((await client.projects.list({ includeArchived: false }))[0]?.project_id, "project-1");

        const chatLink = await client.chats.addToProject("chat-1", "project-1", { folder: "folder-1" });
        assert.equal(chatLink.item_type, "chat");
        assert.equal(chatLink.folder_id, "folder-1");
        assert.equal("targetMode" in chatLink, false);
        assert.equal("remoteCopyProposal" in chatLink, false);

        const workflowLink = await client.workflows.addToProject("workflow-1", "project-1");
        assert.equal(workflowLink.item_type, "workflow");
        assert.equal("targetMode" in workflowLink, false);
        assert.equal("remoteCopyProposal" in workflowLink, false);

        const itemBodies = seen
          .filter((request) => request.method === "POST" && request.url === "/v1/projects/project-1/items")
          .map((request) => request.body as Record<string, string>);
        const metadata = await decryptWithAesGcmCombined(itemBodies[0].encrypted_metadata, projectKey);
        assert.deepEqual(JSON.parse(metadata ?? "{}"), { storage: "save_only_in_openmates", source: "sdk_add_to_project" });
        assert.equal(seen.some((request) => request.url?.includes("/sources")), false);
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
