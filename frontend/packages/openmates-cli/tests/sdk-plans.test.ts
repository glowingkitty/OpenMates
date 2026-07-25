/**
 * OpenMates npm SDK user plan contract tests.
 *
 * Purpose: verify API-key SDK plan CRUD/verification parity with CLI and pip.
 * Security: uses a local HTTP server and synthetic API key only; no plan data or
 * API keys leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-plans.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";
import { createApiKeyCryptoMaterial, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../src/crypto.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const plan = {
  plan_id: "plan-1",
  encrypted_plan_key: "cipher-key",
  encrypted_title: "cipher-title",
  status: "draft" as const,
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

describe("OpenMates SDK user plans", () => {
  it("scopes plan task updates and deletes to the selected plan", async () => {
    const client = new OpenMates({ apiKey: "x", apiUrl: "http://127.0.0.1:9" });
    const calls: unknown[][] = [];
    const tasks = client.tasks as unknown as {
      update: (...args: unknown[]) => Promise<Record<string, unknown>>;
      create: (...args: unknown[]) => Promise<Record<string, unknown>>;
      delete: (...args: unknown[]) => Promise<Record<string, unknown>>;
    };
    tasks.create = async (...args) => {
      calls.push(args);
      return { taskId: "task-1" };
    };
    tasks.update = async (...args) => {
      calls.push(args);
      return { taskId: "task-1" };
    };
    tasks.delete = async (...args) => {
      calls.push(args);
      return { deleted: true };
    };

    await client.plans.tasks.add("plan-1", { title: "Do it" });
    await client.plans.tasks.update("plan-1", "task-1", { status: "done" });
    await client.plans.tasks.remove("plan-1", "task-1");

    assert.deepEqual(calls, [
      [{ title: "Do it", planId: "plan-1" }],
      ["task-1", { status: "done" }, { planId: "plan-1" }],
      ["task-1", { confirmed: true, filters: { planId: "plan-1" } }],
    ]);
  });

  it("manages encrypted plans through the shared API contract", async () => {
    const masterKey = Buffer.alloc(32, 3);
    const planKey = Buffer.alloc(32, 4);
    const chatKey = Buffer.alloc(32, 5);
    const material = await createApiKeyCryptoMaterial("sdk plan parity", masterKey.toString("base64"));
    const encryptedPlanKey = await encryptBytesWithAesGcm(planKey, masterKey);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedChatTitle = await encryptWithAesGcmCombined("Chat", chatKey);
    const validPlan = {
      ...plan,
      encrypted_plan_key: encryptedPlanKey,
      encrypted_title: await encryptWithAesGcmCombined("Plan", planKey),
      version: 1,
    };
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === "/v1/sdk/chats/chat-1") {
          return { chat: { id: "chat-1", encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedChatTitle, updated_at: 200 }, messages: [] };
        }
        if (request.method === "DELETE") return { deleted: true };
        if (request.url?.includes("/runs/run-1")) return { run: { run_id: "run-1" }, artifacts: [] };
        if (request.url?.includes("/learnings/create-tasks")) return { tasks: [], skipped: [] };
        if (request.url?.includes("/learnings") && request.method === "GET") return { learnings: [] };
        if (request.url?.includes("/learnings")) return { learning: body };
        if (request.method === "GET") return { plans: [validPlan] };
        if (request.url?.includes("/criteria")) return { criterion: body };
        if (request.url?.includes("/assumptions")) return { assumption: body };
        if (request.url?.includes("/reference-patterns")) return { reference_pattern: body };
        if (request.url?.includes("/verification") && request.url?.includes("/evidence")) return { verification: body };
        if (request.url?.includes("/verification")) return { verification: body };
        return { plan: { ...validPlan, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        assert.equal((await client.plans.list({ status: "draft", chatId: "chat-1" }))[0]?.planId, "plan-1");
        assert.equal((await client.plans.show("plan-1")).planId, "plan-1");
        assert.equal((await client.plans.create({ title: "Created plan" })).title, "Created plan");
        assert.equal((await client.plans.update("plan-1", { status: "active" })).status, "active");
        assert.equal((await client.plans.attach("plan-1", { chatId: "chat-1" })).primaryChatId, "chat-1");
        assert.equal((await client.plans.start("plan-1")).status, "executing");
        assert.equal((await client.plans.resume("plan-1")).status, "active");
        assert.equal((await client.plans.goal.set("plan-1", "Updated goal")).goal, "Updated goal");
        assert.equal((await client.plans.currentFocus.clear("plan-1")).currentFocus, "");
        assert.equal((await client.plans.scopeIn.add("plan-1", "Scope")).scopeIn, "Scope");
        assert.equal((await client.plans.openQuestions.answer("plan-1", "Answered")).openQuestions, "Answered");
        assert.equal((await client.plans.complete("plan-1")).planId, "plan-1");
        assert.equal((await client.plans.successCriteria.add("plan-1", { criterion_id: "AC-1", encrypted_text: "cipher-ac", created_at: 100 })).criterion_id, "AC-1");
        assert.equal((await client.plans.successCriteria.update("plan-1", "AC-1", { status: "satisfied" })).status, "satisfied");
        assert.deepEqual(await client.plans.successCriteria.remove("plan-1", "AC-1"), { deleted: true });
        assert.equal((await client.plans.listCriteria("plan-1")).length, 0);
        assert.equal((await client.plans.checks.add("plan-1", { verification_id: "V-1", kind: "manual_check", created_at: 100 })).verification_id, "V-1");
        assert.equal((await client.plans.checks.update("plan-1", "V-1", { status: "passed" })).status, "passed");
        assert.equal(((await client.plans.checks.getRun("plan-1", "V-1", "run-1")).run as Record<string, unknown>).run_id, "run-1");
        assert.deepEqual(await client.plans.checks.remove("plan-1", "V-1"), { deleted: true });
        assert.equal((await client.plans.listVerifications("plan-1")).length, 0);
        assert.equal((await client.plans.assumptions.add("plan-1", { assumption_id: "A-1", encrypted_text: "cipher-assumption", created_at: 100 })).assumption_id, "A-1");
        assert.equal((await client.plans.listAssumptions("plan-1")).length, 0);
        assert.equal((await client.plans.assumptions.check("plan-1", "A-1")).status, "checking");
        assert.equal((await client.plans.assumptions.waive("plan-1", "A-1", { encrypted_waiver_reason: "cipher-reason" })).status, "waived");
        assert.deepEqual(await client.plans.assumptions.remove("plan-1", "A-1"), { deleted: true });
        assert.equal((await client.plans.referencePatterns.add("plan-1", { pattern_id: "RP-1", encrypted_title: "cipher-pattern", created_at: 100 })).pattern_id, "RP-1");
        assert.equal((await client.plans.listReferencePatterns("plan-1")).length, 0);
        assert.equal((await client.plans.referencePatterns.inspect("plan-1", "RP-1")).status, "inspected");
        assert.deepEqual(await client.plans.referencePatterns.remove("plan-1", "RP-1"), { deleted: true });
        assert.equal((await client.plans.learnings.create("plan-1", { learning_id: "LRN-1", type: "workflow_improvement", target_kind: "workflow", encrypted_title: "cipher-learning", created_at: 100 })).learning_id, "LRN-1");
        assert.equal((await client.plans.learnings.list("plan-1")).length, 0);
        assert.equal((await client.plans.learnings.update("plan-1", "LRN-1", { status: "accepted" })).status, "accepted");
        assert.deepEqual(await client.plans.learnings.remove("plan-1", "LRN-1"), { deleted: true });
        assert.deepEqual(await client.plans.learnings.createTasks("plan-1", { learning_ids: ["LRN-1"] }), { tasks: [], skipped: [] });
        assert.equal((await client.plans.checks.addEvidence("plan-1", "V-1", { status: "passed" })).status, "passed");

        const urls = seen.map((request) => request.url);
        assert.ok(urls.includes("/v1/sdk/session"));
        assert.ok(urls.includes("/v1/user-plans"));
        assert.ok(urls.includes("/v1/user-plans/plan-1/activate"));
        assert.ok(urls.includes("/v1/user-plans/plan-1/verification/V-1/evidence"));
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
