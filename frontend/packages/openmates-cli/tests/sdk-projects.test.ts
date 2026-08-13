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

const CHAT_ID = "11111111-1111-4111-8111-111111111111";
const PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const WORKFLOW_ID = "33333333-3333-4333-8333-333333333333";

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
  // contract-test: direct surface=sdks.npm assertions=projects.access.explicit-context,projects.lifecycle.encrypted-crud,projects.keys.client-wrapped,projects.surface.semantic-parity,sdk.encryption.local-only,sdk.surface.semantic-parity
  it("provides explicit Personal and Team encrypted CRUD without live file methods", async () => {
    const masterKey = Buffer.alloc(32, 3);
    const teamKey = Buffer.alloc(32, 4);
    const personalProjectKey = Buffer.alloc(32, 5);
    const teamProjectKey = Buffer.alloc(32, 6);
    const material = await createApiKeyCryptoMaterial("sdk project crud", masterKey.toString("base64"));
    const teamId = "team-1";
    const teamHash = (await import("node:crypto")).createHash("sha256").update(teamId).digest("hex");
    const encryptedTeamKey = await encryptBytesWithAesGcm(teamKey, masterKey);
    const records = new Map<string, Record<string, unknown>>();
    const buildRecord = async (projectId: string, name: string, projectKey: Buffer, team = false) => ({
      project_id: projectId,
      encrypted_project_key: team ? null : await encryptBytesWithAesGcm(projectKey, masterKey),
      encrypted_name: await encryptWithAesGcmCombined(name, projectKey),
      encrypted_description: await encryptWithAesGcmCombined("", projectKey),
      encrypted_icon: await encryptWithAesGcmCombined("folder", projectKey),
      encrypted_color: await encryptWithAesGcmCombined("default", projectKey),
      archived: false,
      version: 1,
      key_wrappers: team ? [{
        key_type: "team",
        hashed_team_id: teamHash,
        team_key_epoch: 1,
        encrypted_project_key: await encryptBytesWithAesGcm(projectKey, teamKey),
      }] : [],
    });
    records.set("personal-1", await buildRecord("personal-1", "Personal Project", personalProjectKey));
    records.set("team-1-project", await buildRecord("team-1-project", "Team Project", teamProjectKey, true));

    await withServer(
      (request, body) => {
        const url = new URL(request.url ?? "/", "http://sdk.test");
        if (url.pathname === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && url.pathname === `/v1/teams/${teamId}`) {
          return { team: { team_id: teamId, encrypted_team_key: encryptedTeamKey } };
        }
        const team = url.searchParams.get("team_id") === teamId;
        if (request.method === "GET" && url.pathname === "/v1/projects") {
          return { projects: [records.get(team ? "team-1-project" : "personal-1")] };
        }
        if (request.method === "GET" && url.pathname.startsWith("/v1/projects/")) {
          const projectId = url.pathname.split("/").at(-1) ?? "";
          return { project: records.get(projectId), folders: [], items: [] };
        }
        if (request.method === "POST" && url.pathname === "/v1/projects") {
          const record = body as Record<string, unknown>;
          records.set(String(record.project_id), { ...record, version: 1 });
          return { project: records.get(String(record.project_id)) };
        }
        if (request.method === "PATCH" && url.pathname.startsWith("/v1/projects/")) {
          const projectId = url.pathname.split("/").at(-1) ?? "";
          const record = { ...records.get(projectId), ...(body as Record<string, unknown>), version: 2 };
          records.set(projectId, record);
          return { project: record };
        }
        if (request.method === "DELETE" && url.pathname.startsWith("/v1/projects/")) return { deleted: true };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        assert.equal((await client.projects.list({ personal: true }))[0]?.name, "Personal Project");
        assert.equal((await client.projects.list({ teamId }))[0]?.name, "Team Project");
        assert.equal((await client.projects.show("team-1-project", { teamId })).name, "Team Project");
        const created = await client.projects.create({ name: "Created Team" }, { teamId });
        assert.equal(created.name, "Created Team");
        assert.equal((await client.projects.update(created.projectId, { name: "Updated Team" }, { teamId })).name, "Updated Team");
        assert.equal((await client.projects.archive(created.projectId, { teamId })).archived, true);
        assert.equal((await client.projects.unarchive(created.projectId, { teamId })).archived, false);
        await assert.rejects(() => client.projects.delete(created.projectId, { teamId, confirmed: false }), /confirmed: true/);
        assert.deepEqual(await client.projects.delete(created.projectId, { teamId, confirmed: true }), { deleted: true });
        await assert.rejects(() => client.projects.list({}), /explicit Personal or Team context/);
        assert.equal("files" in client.projects, false);
        assert.ok(seen.some((request) => request.url?.includes(`team_id=${teamId}`)));
      },
      `Bearer ${material.apiKey}`,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity,sdk.encryption.local-only,sdk.surface.semantic-parity
  it("links and unlinks embeds, chats, and workflows as OpenMates-only Project items", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const projectKey = Buffer.alloc(32, 8);
    const chatKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk project links", masterKey.toString("base64"));
    const encryptedProjectKey = await encryptBytesWithAesGcm(projectKey, masterKey);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedTitle = await encryptWithAesGcmCombined("Planning Chat", chatKey);
    const workflow = {
      id: WORKFLOW_ID,
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
          return { projects: [{ project_id: PROJECT_ID, encrypted_project_key: encryptedProjectKey }] };
        }
        if (request.method === "GET" && request.url === `/v1/projects/${PROJECT_ID}`) {
          return { project: { project_id: PROJECT_ID, encrypted_project_key: encryptedProjectKey } };
        }
        if (request.method === "GET" && request.url === "/v1/projects?include_archived=false") {
          return { projects: [{ project_id: PROJECT_ID, encrypted_project_key: encryptedProjectKey }] };
        }
        if (request.method === "GET" && request.url === "/v1/sdk/chats?limit=0") {
          return { chats: [{ id: CHAT_ID, encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle, updated_at: 200 }] };
        }
        if (request.method === "GET" && request.url === `/v1/sdk/chats/${CHAT_ID}`) {
          return { chat: { id: CHAT_ID, encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle, updated_at: 200 }, messages: [] };
        }
        if (request.method === "GET" && request.url === `/v1/workflows/${WORKFLOW_ID}`) return { workflow };
        if (request.method === "POST" && request.url === `/v1/projects/${PROJECT_ID}/items`) return { item: { ...(body as Record<string, unknown>) } };
        if (request.method === "DELETE" && request.url?.startsWith(`/v1/projects/${PROJECT_ID}/items?`)) return { deleted: true, deleted_count: 1 };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        assert.equal((await client.projects.list({ includeArchived: false, personal: true }))[0]?.projectId, PROJECT_ID);

        const chatLink = await client.chats.addToProject(CHAT_ID, PROJECT_ID, { folder: "folder-1" });
        assert.equal(chatLink.item_type, "chat");
        assert.equal(chatLink.folder_id, "folder-1");
        assert.equal("targetMode" in chatLink, false);
        assert.equal("remoteCopyProposal" in chatLink, false);

        const workflowLink = await client.workflows.addToProject(WORKFLOW_ID, PROJECT_ID);
        assert.equal(workflowLink.item_type, "workflow");
        assert.equal("targetMode" in workflowLink, false);
        assert.equal("remoteCopyProposal" in workflowLink, false);

        const embedLink = await client.embeds.addToProject("embed-1", PROJECT_ID);
        assert.equal(embedLink.item_type, "embed");
        assert.equal("targetMode" in embedLink, false);
        assert.equal("remoteCopyProposal" in embedLink, false);

        assert.deepEqual(await client.chats.removeFromProject(CHAT_ID, PROJECT_ID), { deleted: true, deletedCount: 1 });
        assert.deepEqual(await client.workflows.removeFromProject(WORKFLOW_ID, PROJECT_ID), { deleted: true, deletedCount: 1 });
        assert.deepEqual(await client.embeds.removeFromProject("embed-1", PROJECT_ID), { deleted: true, deletedCount: 1 });

        const itemBodies = seen
          .filter((request) => request.method === "POST" && request.url === `/v1/projects/${PROJECT_ID}/items`)
          .map((request) => request.body as Record<string, string>);
        const metadata = await decryptWithAesGcmCombined(itemBodies[0].encrypted_metadata, projectKey);
        assert.deepEqual(JSON.parse(metadata ?? "{}"), { storage: "save_only_in_openmates", source: "sdk_add_to_project" });
        const deleteUrls = seen.filter((request) => request.method === "DELETE").map((request) => request.url ?? "");
        assert.ok(deleteUrls.some((url) => url.includes("item_type=chat") && url.includes(`target_id=${CHAT_ID}`)));
        assert.ok(deleteUrls.some((url) => url.includes("item_type=workflow") && url.includes(`target_id=${WORKFLOW_ID}`)));
        assert.ok(deleteUrls.some((url) => url.includes("item_type=embed") && url.includes("target_id=embed-1")));
        assert.equal(seen.some((request) => request.url?.includes("/sources")), false);
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
