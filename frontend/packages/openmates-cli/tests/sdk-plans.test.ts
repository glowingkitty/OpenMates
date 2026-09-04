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

function assertNoPlaintextMarker(value: unknown, marker: string): void {
  assert.equal(JSON.stringify(value).includes(marker), false);
}

const plan = {
  plan_id: "33333333-3333-4333-8333-333333333333",
  encrypted_title: "cipher-title",
  encrypted_goal: "cipher-goal",
  key_wrappers: [{ key_type: "master", encrypted_plan_key: "cipher-key" }],
  status: "draft" as const,
  created_at: 100,
  updated_at: 100,
};

const CHAT_ID = "11111111-1111-4111-8111-111111111111";
const PLAN_ID = "33333333-3333-4333-8333-333333333333";

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
  // contract-test: direct surface=sdks.npm assertions=plans.surface.semantic-parity
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

  // contract-test: direct surface=sdks.npm assertions=plans.content.client-encrypted,plans.lifecycle.visible,plans.key-wrappers.contextual,plans.execution.gates-evidence,plans.surface.semantic-parity
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
      key_wrappers: [{ key_type: "master", encrypted_plan_key: encryptedPlanKey }],
      encrypted_title: await encryptWithAesGcmCombined("Plan", planKey),
      encrypted_goal: await encryptWithAesGcmCombined("Ship the plan", planKey),
      version: 1,
    };
    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === `/v1/sdk/chats/${CHAT_ID}`) {
          return { chat: { id: CHAT_ID, encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedChatTitle, updated_at: 200 }, messages: [] };
        }
        if (request.method === "DELETE") return { deleted: true };
        if (request.url?.includes("/runs/run-1")) return { run: { run_id: "run-1" }, artifacts: [] };
        if (request.url?.includes("/learnings/create-tasks")) return { tasks: [], skipped: [] };
        if (request.url === `/v1/user-plans/${PLAN_ID}` && request.method === "GET") return { plan: validPlan };
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
        assert.equal((await client.plans.list({ status: "draft", chatId: CHAT_ID }))[0]?.planId, PLAN_ID);
        assert.equal((await client.plans.show(PLAN_ID)).planId, PLAN_ID);
        assert.equal((await client.plans.create({ title: "Created plan", goal: "Ship it" })).title, "Created plan");
        assert.equal((await client.plans.update(PLAN_ID, { status: "active" })).status, "active");
        assert.equal((await client.plans.attach(PLAN_ID, { chatId: CHAT_ID })).primaryChatId, CHAT_ID);
        assert.equal((await client.plans.start(PLAN_ID)).status, "executing");
        assert.equal((await client.plans.resume(PLAN_ID)).status, "active");
        assert.equal((await client.plans.goal.set(PLAN_ID, "Updated goal")).goal, "Updated goal");
        assert.deepEqual((await client.plans.userFlows.clear(PLAN_ID)).userFlows, []);
        assert.equal((await client.plans.scopeIn.add(PLAN_ID, "Scope")).scopeIn, "Scope");
        assert.equal((await client.plans.openQuestions.answer(PLAN_ID, "Answered")).openQuestions, "Answered");
        assert.equal((await client.plans.complete(PLAN_ID)).planId, PLAN_ID);
        const criterion = await client.plans.successCriteria.add(PLAN_ID, { criterionId: "AC-1", text: "Plain AC" });
        assert.equal(criterion.criterionId, "AC-1");
        assert.equal(criterion.text, "Plain AC");
        assert.equal((await client.plans.successCriteria.update(PLAN_ID, "AC-1", { status: "satisfied" })).status, "satisfied");
        assert.deepEqual(await client.plans.successCriteria.remove(PLAN_ID, "AC-1"), { deleted: true });
        assert.equal((await client.plans.listCriteria(PLAN_ID)).length, 0);
        const check = await client.plans.checks.add(PLAN_ID, { verificationId: "V-1", kind: "manual_check", command: "npm test" });
        assert.equal(check.verificationId, "V-1");
        assert.equal(check.command, "npm test");
        assert.equal((await client.plans.checks.update(PLAN_ID, "V-1", { status: "passed" })).status, "passed");
        assert.equal(((await client.plans.checks.getRun(PLAN_ID, "V-1", "run-1")).run as Record<string, unknown>).run_id, "run-1");
        assert.deepEqual(await client.plans.checks.remove(PLAN_ID, "V-1"), { deleted: true });
        assert.equal((await client.plans.listVerifications(PLAN_ID)).length, 0);
        const assumption = await client.plans.assumptions.add(PLAN_ID, { assumptionId: "A-1", text: "Plain assumption" });
        assert.equal(assumption.assumptionId, "A-1");
        assert.equal(assumption.text, "Plain assumption");
        assert.equal((await client.plans.listAssumptions(PLAN_ID)).length, 0);
        assert.equal((await client.plans.assumptions.check(PLAN_ID, "A-1")).status, "checking");
        assert.equal((await client.plans.assumptions.waive(PLAN_ID, "A-1", { waiverReason: "Known limitation" })).status, "waived");
        assert.deepEqual(await client.plans.assumptions.remove(PLAN_ID, "A-1"), { deleted: true });
        const pattern = await client.plans.referencePatterns.add(PLAN_ID, { patternId: "RP-1", title: "Plain pattern" });
        assert.equal(pattern.patternId, "RP-1");
        assert.equal(pattern.title, "Plain pattern");
        assert.equal((await client.plans.listReferencePatterns(PLAN_ID)).length, 0);
        assert.equal((await client.plans.referencePatterns.inspect(PLAN_ID, "RP-1")).status, "inspected");
        assert.deepEqual(await client.plans.referencePatterns.remove(PLAN_ID, "RP-1"), { deleted: true });
        const learning = await client.plans.learnings.create(PLAN_ID, { learningId: "LRN-1", type: "workflow_improvement", targetKind: "workflow", title: "Plain learning" });
        assert.equal(learning.learningId, "LRN-1");
        assert.equal(learning.title, "Plain learning");
        assert.equal((await client.plans.learnings.list(PLAN_ID)).length, 0);
        assert.equal((await client.plans.learnings.update(PLAN_ID, "LRN-1", { status: "accepted" })).status, "accepted");
        assert.deepEqual(await client.plans.learnings.remove(PLAN_ID, "LRN-1"), { deleted: true });
        assert.deepEqual(await client.plans.learnings.createTasks(PLAN_ID, { learning_ids: ["LRN-1"] }), { tasks: [], skipped: [] });
        assert.equal((await client.plans.checks.addEvidence(PLAN_ID, "V-1", { status: "passed", resultSummary: "Passed locally" })).status, "passed");

        const urls = seen.map((request) => request.url);
        assert.ok(urls.includes("/v1/sdk/session"));
        assert.ok(urls.includes("/v1/user-plans"));
        assert.ok(urls.includes(`/v1/user-plans/${PLAN_ID}`));
        assert.ok(urls.includes(`/v1/user-plans/${PLAN_ID}/activate`));
        assert.ok(urls.includes(`/v1/user-plans/${PLAN_ID}/verification/V-1/evidence`));
        for (const marker of ["Plain AC", "Plain assumption", "Plain pattern", "Plain learning", "Passed locally"]) {
          assertNoPlaintextMarker(seen, marker);
        }
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
