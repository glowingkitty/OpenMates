/**
 * Unit tests for OpenMates user plan CLI client methods.
 *
 * Purpose: lock the shared encrypted /v1/user-plans contract without a real API.
 * Security: uses a local HTTP server and synthetic session only; no account data
 * or plan ciphertext leaves the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/plans.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient, type UserPlanCreateInput } from "../src/client.ts";
import type { OpenMatesSession } from "../src/storage.ts";
import {
  buildCreatePlanCriterionInput,
  buildCreatePlanVerificationInput,
  buildCreateUserPlanInput,
  buildPlanVerificationEvidenceInput,
  buildUpdateUserPlanInput,
  decryptUserPlan,
  renderPlanDetail,
} from "../src/plansCli.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

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

function encryptedPlanInput(): UserPlanCreateInput {
  return {
    plan_id: "plan-1",
    encrypted_plan_key: "cipher-key",
    encrypted_title: "cipher-title",
    encrypted_goal: "cipher-goal",
    status: "draft",
    linked_project_ids: ["project-1"],
    primary_chat_id: "chat-1",
    created_at: 100,
    updated_at: 100,
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

describe("OpenMatesClient user plans", () => {
  it("encrypts, decrypts, and renders local plan payloads", async () => {
    const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: testSession() });
    const masterKey = client.getMasterKeyBytes();
    const encrypted = await buildCreateUserPlanInput(masterKey, {
      title: "Launch website",
      summary: "Coordinate launch work",
      goal: "Ship the public site",
      primaryChatId: "chat-1",
      linkedProjectIds: ["project-1"],
      status: "awaiting_confirmation",
    });

    assert.equal(encrypted.status, "awaiting_confirmation");
    assert.equal(encrypted.primary_chat_id, "chat-1");
    assert.deepEqual(encrypted.linked_project_ids, ["project-1"]);
    assert.notEqual(encrypted.encrypted_title, "Launch website");

    const plan = await decryptUserPlan(encrypted, masterKey);
    assert.equal(plan.title, "Launch website");
    assert.equal(plan.goal, "Ship the public site");
    assert.deepEqual(plan.linkedProjectIds, ["project-1"]);
    assert.match(renderPlanDetail(plan), /Launch website/);

    const patch = await buildUpdateUserPlanInput(plan, masterKey, { goal: "Ship a faster public site", status: "active" });
    assert.equal(patch.status, "active");
    assert.equal(patch.version, 1);
    assert.notEqual(patch.encrypted_goal, "Ship a faster public site");

    const criterion = await buildCreatePlanCriterionInput(plan, masterKey, { text: "Homepage renders", required: true });
    assert.notEqual(criterion.encrypted_text, "Homepage renders");
    assert.equal(criterion.required, true);

    const verification = await buildCreatePlanVerificationInput(plan, masterKey, {
      kind: "command",
      command: "npm test",
      expectedResult: "tests pass",
      requiredForDone: true,
    });
    assert.equal(verification.kind, "command");
    assert.notEqual(verification.encrypted_command, "npm test");

    const evidence = await buildPlanVerificationEvidenceInput(plan, masterKey, {
      status: "passed",
      resultSummary: "All checks passed",
    });
    assert.equal(evidence.status, "passed");
    assert.notEqual(evidence.encrypted_result_summary, "All checks passed");
  });

  it("manages encrypted user plans and verification evidence", async () => {
    const plan = encryptedPlanInput();
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { plans: [plan] };
        if (request.url?.includes("/criteria")) return { criterion: body };
        if (request.url?.includes("/assumptions")) return { assumption: body };
        if (request.url?.includes("/reference-patterns")) return { reference_pattern: body };
        if (request.url?.includes("/verification") && request.url?.includes("/evidence")) return { verification: body };
        if (request.url?.includes("/verification")) return { verification: body };
        return { plan: { ...plan, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.listUserPlans({ status: "draft", chatId: "chat-1", projectId: "project-1" }))[0]?.plan_id, "plan-1");
        assert.equal((await client.createUserPlan(plan)).encrypted_title, "cipher-title");
        assert.equal((await client.updateUserPlan("plan-1", { status: "active", version: 1 })).status, "active");
        assert.equal((await client.activateUserPlan("plan-1", { chat_id: "chat-1", version: 2 })).primary_chat_id, "chat-1");
        assert.equal((await client.completeUserPlan("plan-1", { version: 3 })).plan_id, "plan-1");
        assert.equal((await client.createPlanCriterion("plan-1", { criterion_id: "AC-1", encrypted_text: "cipher-ac", created_at: 100 })).criterion_id, "AC-1");
        assert.equal((await client.listPlanCriteria("plan-1")).length, 0);
        assert.equal((await client.createPlanVerification("plan-1", { verification_id: "V-1", kind: "manual_check", created_at: 100 })).verification_id, "V-1");
        assert.equal((await client.listPlanVerifications("plan-1")).length, 0);
        assert.equal((await client.createPlanAssumption("plan-1", { assumption_id: "A-1", encrypted_text: "cipher-assumption", created_at: 100 })).assumption_id, "A-1");
        assert.equal((await client.listPlanAssumptions("plan-1")).length, 0);
        assert.equal((await client.updatePlanAssumption("plan-1", "A-1", { status: "confirmed" })).status, "confirmed");
        assert.equal((await client.createPlanReferencePattern("plan-1", { pattern_id: "RP-1", encrypted_title: "cipher-pattern", created_at: 100 })).pattern_id, "RP-1");
        assert.equal((await client.listPlanReferencePatterns("plan-1")).length, 0);
        assert.equal((await client.addPlanVerificationEvidence("plan-1", "V-1", { status: "passed" })).status, "passed");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-plans?status=draft&chat_id=chat-1&project_id=project-1"],
          ["POST", "/v1/user-plans"],
          ["PATCH", "/v1/user-plans/plan-1"],
          ["POST", "/v1/user-plans/plan-1/activate"],
          ["POST", "/v1/user-plans/plan-1/complete"],
          ["POST", "/v1/user-plans/plan-1/criteria"],
          ["GET", "/v1/user-plans/plan-1/criteria"],
          ["POST", "/v1/user-plans/plan-1/verification"],
          ["GET", "/v1/user-plans/plan-1/verification"],
          ["POST", "/v1/user-plans/plan-1/assumptions"],
          ["GET", "/v1/user-plans/plan-1/assumptions"],
          ["PATCH", "/v1/user-plans/plan-1/assumptions/A-1"],
          ["POST", "/v1/user-plans/plan-1/reference-patterns"],
          ["GET", "/v1/user-plans/plan-1/reference-patterns"],
          ["POST", "/v1/user-plans/plan-1/verification/V-1/evidence"],
        ]);
      },
    );
  });
});
