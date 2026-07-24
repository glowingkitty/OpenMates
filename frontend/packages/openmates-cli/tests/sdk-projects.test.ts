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

import { OpenMates, OpenMatesConfigError, type ProjectItemCreateInput } from "../src/sdk.ts";
import { createApiKeyCryptoMaterial, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../src/crypto.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const sourceInput = {
  sourceId: "source-1",
  sourceType: "remote_git_repository" as const,
  displayName: "Repository Source",
  metadata: { root: "/repo", redacted: true },
  capabilities: ["read", "search"] as const,
  status: "connected" as const,
  createdAt: 100,
  updatedAt: 100,
};

const source = {
  source_id: "source-1",
  source_type: "remote_git_repository",
  encrypted_display_name: "cipher-name-placeholder",
  encrypted_metadata: "cipher-metadata-placeholder",
  capabilities: ["read", "search"],
  status: "connected",
  created_at: 100,
  updated_at: 100,
};

const item: ProjectItemCreateInput = {
  project_item_id: "project-item-1",
  item_type: "chat",
  target_id: "chat-1",
  target_id_encrypted: "cipher-target",
  encrypted_display_name: "cipher-display",
  encrypted_note: "cipher-note",
  encrypted_metadata: "cipher-metadata",
  created_at: 100,
  updated_at: 100,
};

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

describe("OpenMates SDK Project sources", () => {
  it("manages cleartext Project sources through encrypted shared API payloads", async () => {
    const masterKey = Buffer.alloc(32, 5);
    const projectKey = Buffer.alloc(32, 6);
    const material = await createApiKeyCryptoMaterial("sdk source parity", masterKey.toString("base64"));
    const encryptedProjectKey = await encryptBytesWithAesGcm(projectKey, masterKey);
    const encryptedSource = {
      ...source,
      encrypted_display_name: await encryptWithAesGcmCombined(sourceInput.displayName, projectKey),
      encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify(sourceInput.metadata), projectKey),
    };
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === "/v1/projects?include_archived=true") {
          return { projects: [{ project_id: "project-1", encrypted_project_key: encryptedProjectKey }] };
        }
        if (request.method === "GET" && request.url?.endsWith("/sources")) return { sources: [encryptedSource] };
        if (request.url?.endsWith("/items")) return { item: { ...item, ...(body as Record<string, unknown>) } };
        return { source: { ...encryptedSource, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        assert.equal((await client.projects.listSources("project-1"))[0]?.displayName, "Repository Source");
        const createdSource = await client.projects.createSource("project-1", sourceInput);
        assert.equal(createdSource.displayName, "Repository Source");
        assert.equal((await client.projects.createItem("project-1", item)).project_item_id, "project-item-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/projects?include_archived=true"],
          ["POST", "/v1/sdk/session"],
          ["GET", "/v1/projects/project-1/sources"],
          ["GET", "/v1/projects?include_archived=true"],
          ["POST", "/v1/projects/project-1/sources"],
          ["POST", "/v1/projects/project-1/items"],
        ]);
        assert.notEqual((seen[4]?.body as Record<string, unknown>).encrypted_display_name, sourceInput.displayName);
        assert.deepEqual(seen[5]?.body, item);
      },
      `Bearer ${material.apiKey}`,
    );
  });

  it("returns non-mutating remote-copy proposals for Project chat and workflow links", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const projectKey = Buffer.alloc(32, 8);
    const chatKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk project proposals", masterKey.toString("base64"));
    const encryptedProjectKey = await encryptBytesWithAesGcm(projectKey, masterKey);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedTitle = await encryptWithAesGcmCombined("Planning Chat", chatKey);
    const encryptedMessage = await encryptWithAesGcmCombined("Email me at test@example.com", chatKey);
    const workflow = {
      id: "workflow-1",
      title: "Release Workflow",
      description: "Ship safely",
      status: "draft",
      enabled: false,
      current_version_id: "version-1",
      created_at: 100,
      updated_at: 200,
        graph: {
          version: 1,
          nodes: [{ id: "manual:trigger", type: "manual_trigger", title: "Manual trigger" }],
          edges: [{ from: "manual:trigger", to: "end" }],
        },
    };

    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === "/v1/projects/project-1/sources") return { sources: [source] };
        if (request.method === "GET" && request.url === "/v1/projects?include_archived=true") {
          return { projects: [{ project_id: "project-1", encrypted_project_key: encryptedProjectKey }] };
        }
        if (request.method === "GET" && request.url === "/v1/sdk/chats/chat-1") {
          return {
            chat: { id: "chat-1", encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle, updated_at: 200 },
            messages: [JSON.stringify({ id: "message-1", role: "user", created_at: 100, encrypted_content: encryptedMessage })],
          };
        }
        if (request.method === "GET" && request.url === "/v1/workflows/workflow-1") return { workflow };
        if (request.method === "POST" && request.url === "/v1/projects/project-1/items") return { item: { ...(body as Record<string, unknown>) } };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        const chatLink = await client.chats.addToProject("chat-1", "project-1", { remoteCacheCopy: true });
        assert.equal(chatLink.targetMode, "store_local_only_on_remote_machine");
        assert.equal(chatLink.remoteCopyProposal?.writes_files, false);
        assert.equal(chatLink.remoteCopyProposal?.diff_or_create_file_patch.operation, "create_file");
        assert.match(chatLink.remoteCopyProposal?.target_path ?? "", /^~\/\.openmates\/remote-cache\/source-1\/exports\/chat\/planning-chat\.md$/);
        assert.equal(chatLink.remoteCopyProposal?.pii_scan_result.found, true);

        const workflowLink = await client.workflows.addToProject("workflow-1", "project-1", { remoteCopy: true });
        assert.equal(workflowLink.targetMode, "store_on_remote_machine_and_include_in_git");
        assert.equal(workflowLink.remoteCopyProposal?.target_path, ".openmates/workflows/release-workflow.yml");
        const workflowYaml = workflowLink.remoteCopyProposal?.diff_or_create_file_patch.content ?? "";
        assert.match(workflowYaml, /graph:\n {2}version: 1\n {2}nodes:\n {4}-\n {6}id: "manual:trigger"/);
        assert.match(workflowYaml, / {2}edges:\n {4}-\n {6}from: "manual:trigger"\n {6}to: end/);
      },
      `Bearer ${material.apiKey}`,
    );
  });

  it("exposes reserved instruction-audit methods with explicit consent gates", async () => {
    const client = new OpenMates({ apiKey: "x", apiUrl: "http://127.0.0.1:9" });
    await assert.rejects(
      () => client.projects.auditInstructions("project-1", "source-1"),
      { name: OpenMatesConfigError.name, message: /requires confirmed: true/ },
    );
    await assert.rejects(
      () => client.projects.auditInstructions("project-1", "source-1", { confirmed: true }),
      { name: OpenMatesConfigError.name, message: /Project instruction audit is not available/ },
    );
    await assert.rejects(
      () => client.projects.applySelectedInstructionAuditSuggestions("project-1", "source-1", ["suggestion-1"]),
      { name: OpenMatesConfigError.name, message: /requires confirmed: true/ },
    );
    await assert.rejects(
      () => client.projects.getInstructionAuditStatus("project-1", "source-1"),
      { name: OpenMatesConfigError.name, message: /Project instruction audit status is not available/ },
    );
  });
});
