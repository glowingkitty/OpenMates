/**
 * OpenMates npm SDK workflow contract tests.
 *
 * Purpose: verify API-key SDK workflow CRUD/run/history parity with CLI and pip.
 * Security: uses a local HTTP server and synthetic API key only; no real account
 * cookies, API keys, or workflow payloads leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-workflows.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";
import { createApiKeyCryptoMaterial } from "../src/crypto.ts";
import { buildEncryptedObjectSlugMetadata } from "../src/objectSlugs.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const CHAT_ID = "11111111-1111-4111-8111-111111111111";

function minimalGraph() {
  return {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [
      { id: "trigger", type: "manual_trigger", config: {} },
    ],
    edges: [],
  };
}

function blankGraph() {
  return {
    version: 1,
    trigger_node_id: null,
    nodes: [],
    edges: [],
  };
}

function templateImportPayload() {
  return {
    template_version: 1,
    title: "Morning",
    trigger_template: { type: "manual_trigger", config: {} },
    node_templates: [],
    edge_templates: [],
    variables_schema: {},
    required_capabilities: [],
    binding_requirements: [],
  };
}

function assertPublicWorkflowSlug(workflow: Record<string, unknown>, slug: string): void {
  assert.equal(workflow.slug, slug);
  assert.equal("encrypted_slug" in workflow, false);
  assert.equal("slug_lookup_hash" in workflow, false);
}

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
        if (request.url?.startsWith("/v1/workflows/template-projections/")) {
          assert.equal(request.headers.authorization, undefined);
        } else {
          assert.equal(request.headers.authorization, expectedAuthorization);
        }
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

describe("OpenMates SDK workflows", () => {
  // contract-test: direct surface=sdks.npm assertions=workflows.activation.reachable-side-effect,workflows.surface.semantic-parity,workflows-ui.identity.automatic-category-icon,sdk.encryption.local-only,sdk.surface.semantic-parity
  it("manages workflows through the shared API contract", async () => {
    const graph = minimalGraph();
    const masterKey = Buffer.alloc(32, 11);
    const material = await createApiKeyCryptoMaterial("sdk workflow parity", masterKey.toString("base64"));
    const slugMetadata = await buildEncryptedObjectSlugMetadata({ value: "Morning", encryptionKey: masterKey, lookupKey: masterKey });
    const tempSlugMetadata = await buildEncryptedObjectSlugMetadata({ value: "Temporary", encryptionKey: masterKey, lookupKey: masterKey });
    const encryptedSlugFields = {
      encrypted_slug: slugMetadata.encrypted_slug,
      slug_lookup_hash: slugMetadata.slug_lookup_hash,
    };
    const encryptedTempSlugFields = {
      encrypted_slug: tempSlugMetadata.encrypted_slug,
      slug_lookup_hash: tempSlugMetadata.slug_lookup_hash,
    };
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.url === "/v1/workflows" && request.method === "GET") {
          return { workflows: [{ id: "wf-1", title: "Morning", category: "science", icon: "cloud-rain", status: "disabled", enabled: false, run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1, ...encryptedSlugFields }] };
        }
        if (request.url === "/v1/workflows/temporary" && request.method === "GET") {
          return { workflows: [{ id: "wf-temp", title: "Temporary", status: "disabled", enabled: false, lifecycle: "temporary", run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1, ...encryptedTempSlugFields }] };
        }
        if (request.url === "/v1/workflows/capabilities") {
          return { capabilities: [{ id: "weather:forecast", type: "app_skill", title: "Weather forecast", enabled: true }] };
        }
        if (request.url === "/v1/workflows/validate") {
          assert.deepEqual(body, { source: "title: Morning\n" });
          return { validation: { draft_valid: true, enable_ready: false, diagnostics: [{ code: "REQUIRED_RUNTIME_INPUT" }] } };
        }
        if (request.url === "/v1/workflows/yaml") {
          assert.deepEqual(body, { source: "title: Morning\n" });
          return { workflow: { id: "wf-yaml", title: "Morning", status: "disabled", enabled: false, run_content_retention: "last_5", current_version_id: "v1", created_at: 1, updated_at: 1, graph, ...encryptedSlugFields }, validation: { draft_valid: true, enable_ready: true, diagnostics: [] } };
        }
        if (request.url === "/v1/workflows/wf-1/yaml") {
          assert.deepEqual(body, { source: "title: Updated\n" });
          return { workflow: { id: "wf-1", title: "Updated", status: "disabled", enabled: false, run_content_retention: "last_5", current_version_id: "v2", created_at: 1, updated_at: 2, graph, ...encryptedSlugFields }, validation: { draft_valid: true, enable_ready: true, diagnostics: [] } };
        }
        if (request.url === "/v1/workflows/wf-1/runs") {
          return { runs: [{ id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [] }] };
        }
        if (request.url === "/v1/workflows/wf-1/runs/run-1") {
          return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [{ id: "node-run-1", node_id: "weather", node_type: "app_skill_action", status: "completed", output_summary: { forecast: "rain" }, credits_charged: 2 }] } };
        }
        if (request.url === "/v1/workflows/wf-1/steps/math/test") {
          assert.deepEqual(body, { input: { expression: "2 + 2" }, confirmed: true });
          return { run: { id: "run-step-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "step_test", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [{ id: "node-run-step-1", node_id: "math", node_type: "app_skill_action", status: "completed", output_summary: { result: "4" } }] } };
        }
        if (request.url === "/v1/workflows/wf-1/runs/run-1/cancel") {
          return { run_id: "run-1", status: "cancellation_requested" };
        }
        if (request.url === "/v1/workflows/wf-1/runs/run-1/respond") {
          assert.deepEqual(body, { step_id: "ask", input: { answer: "Berlin" } });
          return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed", content_retention_mode: "last_5", content_available: true, content_storage: "durable", node_runs: [] } };
        }
        if (request.url === "/v1/workflows/wf-1/template-projection") {
          assert.equal(request.method, "PUT");
          assert.deepEqual(body, {
            template_id: "tpl-1",
            source_version: 2,
            ciphertext: "opaque-ciphertext",
            ciphertext_checksum: "sha256:abc",
            owner_wrapped_key: "wrapped-key",
            projection_schema_version: 1,
          });
          return { template_id: "tpl-1", source_version: 2, updated_at: 123 };
        }
        if (request.url === "/v1/share/short-url") {
          assert.deepEqual(body, {
            token: "Abc123XY",
            encrypted_url: "opaque-url",
            content_type: "workflow_template",
            content_id: "tpl-1",
            password_protected: false,
            ttl_seconds: 3600,
          });
          return { success: true, expires_at: 999 };
        }
        if (request.url === "/v1/share/short-url/Abc123XY") {
          assert.equal(request.method, "DELETE");
          return { success: true, revoked_at: 1000 };
        }
        if (request.url === "/v1/workflows/template-import") {
          assert.deepEqual(body, templateImportPayload());
          return { workflow: { id: "wf-imported", title: "Morning", status: "disabled", enabled: false, current_version_id: "v1", created_at: 1, updated_at: 1, graph, binding_requirements: [], ...encryptedSlugFields } };
        }
        if (request.url === "/v1/workflows/wf-1/run") {
          assert.deepEqual(body, { mode: "test", input: { dry: true } });
          assert.equal(request.headers["idempotency-key"], "stable-run-1");
          return { run: { id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "test", status: "completed", content_retention_mode: "none", content_available: true, content_storage: "ephemeral", node_runs: [] } };
        }
        if (request.method === "DELETE") return { deleted: true };
        return { workflow: { id: "wf-1", title: (body as any)?.title ?? "Morning", status: "active", enabled: (body as any)?.enabled ?? true, run_content_retention: (body as any)?.run_content_retention ?? "last_5", current_version_id: "v1", created_at: 1, updated_at: 2, graph: (body as any)?.graph ?? graph, ...encryptedSlugFields } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
        const listedWorkflow = (await client.workflows.list())[0];
        const temporaryWorkflow = (await client.workflows.temporary())[0];
        assert.equal(listedWorkflow?.id, "wf-1");
        assert.equal(listedWorkflow?.category, "science");
        assert.equal(listedWorkflow?.icon, "cloud-rain");
        assert.equal(temporaryWorkflow?.id, "wf-temp");
        assertPublicWorkflowSlug(listedWorkflow as Record<string, unknown>, "morning");
        assertPublicWorkflowSlug(temporaryWorkflow as Record<string, unknown>, "temporary");
        assert.equal((await client.workflows.capabilities())[0]?.id, "weather:forecast");
        assert.equal((await client.workflows.validateYaml("title: Morning\n")).draft_valid, true);
        const createdFromYaml = await client.workflows.createFromYaml("title: Morning\n");
        const updatedFromYaml = await client.workflows.updateFromYaml("wf-1", "title: Updated\n");
        const blankWorkflow = await client.workflows.create({ title: "Blank", graph: blankGraph(), enabled: false });
        const createdWorkflow = await client.workflows.create({ title: "Morning", graph, enabled: true, runContentRetention: "none", lifecycle: "temporary", source: "chat", sourceChatId: CHAT_ID, createdByAssistant: true });
        const fetchedWorkflow = await client.workflows.get("wf-1");
        const updatedWorkflow = await client.workflows.update("wf-1", { enabled: false, runContentRetention: "last_5" });
        const enabledWorkflow = await client.workflows.enable("wf-1");
        const disabledWorkflow = await client.workflows.disable("wf-1");
        const keptWorkflow = await client.workflows.keep("wf-1");

        assert.equal(createdFromYaml.workflow.id, "wf-yaml");
        assert.equal(updatedFromYaml.workflow.title, "Updated");
        assert.equal(blankWorkflow.graph.trigger_node_id, null);
        assert.deepEqual(blankWorkflow.graph.nodes, []);
        assert.equal(createdWorkflow.run_content_retention, "none");
        assert.equal(fetchedWorkflow.id, "wf-1");
        assert.equal(updatedWorkflow.id, "wf-1");
        assert.equal(enabledWorkflow.enabled, true);
        assert.equal(disabledWorkflow.id, "wf-1");
        assert.equal(keptWorkflow.id, "wf-1");
        for (const workflow of [createdFromYaml.workflow, updatedFromYaml.workflow, blankWorkflow, createdWorkflow, fetchedWorkflow, updatedWorkflow, enabledWorkflow, disabledWorkflow, keptWorkflow]) {
          assertPublicWorkflowSlug(workflow as Record<string, unknown>, "morning");
        }
        assert.equal((await client.workflows.run("wf-1", { idempotencyKey: "stable-run-1", mode: "test", input: { dry: true } })).content_storage, "ephemeral");
        assert.equal((await client.workflows.runs("wf-1"))[0]?.content_storage, "durable");
        assert.equal((await client.workflows.runDetail("wf-1", "run-1")).node_runs?.[0]?.output_summary?.forecast, "rain");
        assert.equal((await client.workflows.stepTest("wf-1", "math", { input: { expression: "2 + 2" }, confirmed: true })).trigger_type, "step_test");
        assert.equal((await client.workflows.cancelRun("wf-1", "run-1")).status, "cancellation_requested");
        assert.equal((await client.workflows.respond("wf-1", "run-1", "ask", { answer: "Berlin" })).status, "completed");
        assert.equal((await client.workflows.upsertTemplateProjection("wf-1", { templateId: "tpl-1", sourceVersion: 2, ciphertext: "opaque-ciphertext", ciphertextChecksum: "sha256:abc", ownerWrappedKey: "wrapped-key", projectionSchemaVersion: 1 })).updated_at, 123);
        assert.equal((await client.workflows.createTemplateShortUrl({ token: "Abc123XY", encryptedUrl: "opaque-url", templateId: "tpl-1", ttlSeconds: 3600 })).expires_at, 999);
        assert.equal((await client.workflows.revokeShortUrl("Abc123XY")).revoked_at, 1000);
        const importedWorkflow = await client.workflows.importTemplate(templateImportPayload());
        assert.equal(importedWorkflow.id, "wf-imported");
        assertPublicWorkflowSlug(importedWorkflow as Record<string, unknown>, "morning");
        assert.equal((await client.workflows.delete("wf-1", { confirmed: true })).deleted, true);

        const endpoints = seen.map((request) => `${request.method} ${request.url}`);
        for (const endpoint of [
          "GET /v1/workflows",
          "GET /v1/workflows/temporary",
          "GET /v1/workflows/capabilities",
          "POST /v1/workflows/validate",
          "POST /v1/workflows/yaml",
          "POST /v1/workflows/wf-1/yaml",
          "POST /v1/sdk/session",
          "POST /v1/workflows",
          "GET /v1/workflows/wf-1",
          "PATCH /v1/workflows/wf-1",
          "POST /v1/workflows/wf-1/enable",
          "POST /v1/workflows/wf-1/disable",
          "POST /v1/workflows/wf-1/keep",
          "POST /v1/workflows/wf-1/run",
          "GET /v1/workflows/wf-1/runs",
          "GET /v1/workflows/wf-1/runs/run-1",
          "POST /v1/workflows/wf-1/steps/math/test",
          "POST /v1/workflows/wf-1/runs/run-1/cancel",
          "POST /v1/workflows/wf-1/runs/run-1/respond",
          "PUT /v1/workflows/wf-1/template-projection",
          "POST /v1/share/short-url",
          "DELETE /v1/share/short-url/Abc123XY",
          "POST /v1/workflows/template-import",
          "DELETE /v1/workflows/wf-1",
        ]) {
          assert.ok(endpoints.includes(endpoint), `missing endpoint ${endpoint}`);
        }
        const createBody = seen.find((request) => request.method === "POST" && request.url === "/v1/workflows" && (request.body as Record<string, unknown>)?.title === "Morning")?.body as Record<string, unknown>;
        const blankCreateBody = seen.find((request) => request.method === "POST" && request.url === "/v1/workflows" && (request.body as Record<string, unknown>)?.title === "Blank")?.body as Record<string, unknown>;
        assert.equal(createBody.title, "Morning");
        assert.equal(createBody.source_chat_id, CHAT_ID);
        assert.equal(typeof createBody.encrypted_slug, "string");
        assert.equal(typeof createBody.slug_lookup_hash, "string");
        assert.equal("slug" in createBody, false);
        assert.deepEqual(blankCreateBody.graph, blankGraph());
        assert.equal(blankCreateBody.enabled, false);
      },
      `Bearer ${material.apiKey}`,
    );
  });

  // contract-test: supporting surface=sdks.npm assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
  it("exposes workflow app-skill child embeds and server-side search results", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/apps/workflows/skills/create-or-modify") {
          assert.deepEqual(body, {
            title: "Morning weather",
          });
          return {
            success: true,
            data: {
              success: true,
              app_id: "workflows",
              skill_id: "create-or-modify",
              parent_embed_id: "app-skill-use-1",
              result_count: 1,
              results: [
                {
                  type: "workflow",
                  parent_app_skill_type: "app_skill_use",
                  child_embed_id: "workflow-embed-1",
                  workflow_id: "workflow-1",
                  title: "Morning weather",
                  status: "draft",
                },
              ],
            },
          };
        }
        if (request.url === "/v1/apps/workflows/skills/search") {
          assert.deepEqual(body, {
            query: "weather",
            include_temporary: true,
          });
          return {
            success: true,
            data: {
              success: true,
              app_id: "workflows",
              skill_id: "search",
              status: "finished",
              requires_connected_client: false,
              result_count: 2,
              results: [
                {
                  type: "workflow",
                  parent_app_skill_type: "app_skill_use",
                  child_embed_id: "workflow-embed-1",
                  workflow_id: "workflow-1",
                  title: "Morning weather",
                  status: "enabled",
                },
                {
                  type: "workflow",
                  parent_app_skill_type: "app_skill_use",
                  child_embed_id: "workflow-embed-2",
                  workflow_id: "workflow-2",
                  title: "Weather digest",
                  status: "draft",
                },
              ],
            },
          };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        const created = await client.apps.workflows.createOrModify<Record<string, any>>({
          title: "Morning weather",
        });
        const search = await client.apps.workflows.search<Record<string, any>>({
          query: "weather",
          include_temporary: true,
        });

        assert.equal(created.data.app_id, "workflows");
        assert.equal(created.data.parent_embed_id, "app-skill-use-1");
        assert.equal(created.data.results[0].child_embed_id, "workflow-embed-1");
        assert.equal(created.data.results[0].workflow_id, "workflow-1");
        assert.equal(search.data.status, "finished");
        assert.equal(search.data.requires_connected_client, false);
        assert.equal(search.data.result_count, 2);
        assert.deepEqual(search.data.results.map((result: Record<string, unknown>) => result.child_embed_id), [
          "workflow-embed-1",
          "workflow-embed-2",
        ]);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/apps/workflows/skills/create-or-modify"],
          ["POST", "/v1/apps/workflows/skills/search"],
        ]);
      },
    );
  });

  // contract-test: direct surface=sdks.npm assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
  it("manages workflow template sharing transport through the shared API contract", async () => {
    const material = await createApiKeyCryptoMaterial("sdk workflow template", Buffer.alloc(32, 12).toString("base64"));
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.url === "/v1/workflows" && request.method === "GET") {
          return { workflows: [{ id: "wf-1", title: "Morning", status: "disabled", enabled: false, current_version_id: "v1", created_at: 1, updated_at: 1 }] };
        }
        if (request.url === "/v1/workflows/template-projections/tpl-1" && request.method === "GET") {
          return {
            template_id: "tpl-1",
            ciphertext: "opaque-ciphertext",
            ciphertext_checksum: "sha256:abc",
            projection_schema_version: 1,
          };
        }
        if (request.url === "/v1/workflows/wf-1/template-projection/revoke" && request.method === "POST") {
          assert.deepEqual(body, {});
          return { template_id: "tpl-1", revoked_at: 1000 };
        }
        if (request.url === "/v1/workflows/wf-1/template-projection/unrevoke" && request.method === "POST") {
          assert.deepEqual(body, {});
          return { template_id: "tpl-1", revoked_at: null };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
        assert.equal((await client.workflows.getPublicTemplateProjection("tpl-1")).ciphertext, "opaque-ciphertext");
        assert.equal((await client.workflows.revokeTemplateProjection("wf-1")).revoked_at, 1000);
        assert.equal((await client.workflows.unrevokeTemplateProjection("wf-1")).revoked_at, null);

        const endpoints = seen.map((request) => `${request.method} ${request.url}`);
        assert.ok(endpoints.includes("GET /v1/workflows/template-projections/tpl-1"));
        assert.ok(endpoints.includes("POST /v1/sdk/session"));
        assert.ok(endpoints.includes("GET /v1/workflows"));
        assert.ok(endpoints.includes("POST /v1/workflows/wf-1/template-projection/revoke"));
        assert.ok(endpoints.includes("POST /v1/workflows/wf-1/template-projection/unrevoke"));
      },
      `Bearer ${material.apiKey}`,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
  it("manages durable workflow input sessions", async () => {
    const material = await createApiKeyCryptoMaterial("sdk workflow input", Buffer.alloc(32, 13).toString("base64"));
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.url === "/v1/workflows" && request.method === "GET") {
          return { workflows: [{ id: "wf-1", title: "Morning", status: "disabled", enabled: false, current_version_id: "v1", created_at: 1, updated_at: 1 }] };
        }
        if (request.url === "/v1/workflows/input" && request.method === "POST") {
          assert.deepEqual(body, { text: "alert me if it rains", input_type: "text", selected_workflow_id: "wf-1" });
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
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
        assert.equal((await client.workflows.startInput({ text: "alert me if it rains", selectedWorkflowId: "wf-1" })).session_id, "session-1");
        assert.equal((await client.workflows.inputSession("session-1")).status, "executed");
        assert.equal((await client.workflows.inputEvents("session-1", 2))[0]?.type, "validation_passed");
        assert.equal((await client.workflows.followUpInput("session-1", "weekdays only")).event_cursor, 7);
        assert.equal((await client.workflows.stopInput("session-1")).status, "stopped");
        assert.equal((await client.workflows.undoInput("session-1")).status, "undone");

        const endpoints = seen.map((request) => `${request.method} ${request.url}`);
        for (const endpoint of [
          "POST /v1/sdk/session",
          "GET /v1/workflows",
          "POST /v1/workflows/input",
          "GET /v1/workflows/input/session-1",
          "GET /v1/workflows/input/session-1/events?after_event_id=2",
          "POST /v1/workflows/input/session-1/follow-up",
          "POST /v1/workflows/input/session-1/stop",
          "POST /v1/workflows/input/session-1/undo",
        ]) {
          assert.ok(endpoints.includes(endpoint), `missing endpoint ${endpoint}`);
        }
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
