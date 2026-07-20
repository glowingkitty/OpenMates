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

describe("OpenMates SDK user plans", () => {
  it("manages encrypted plans through the shared API contract", async () => {
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
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.plans.list({ status: "draft", chatId: "chat-1" }))[0]?.plan_id, "plan-1");
        assert.equal((await client.plans.create(plan)).encrypted_title, "cipher-title");
        assert.equal((await client.plans.update("plan-1", { status: "active", version: 1 })).status, "active");
        assert.equal((await client.plans.activate("plan-1", { chat_id: "chat-1", version: 2 })).primary_chat_id, "chat-1");
        assert.equal((await client.plans.complete("plan-1", { version: 3 })).plan_id, "plan-1");
        assert.equal((await client.plans.createCriterion("plan-1", { criterion_id: "AC-1", encrypted_text: "cipher-ac", created_at: 100 })).criterion_id, "AC-1");
        assert.equal((await client.plans.listCriteria("plan-1")).length, 0);
        assert.equal((await client.plans.createVerification("plan-1", { verification_id: "V-1", kind: "manual_check", created_at: 100 })).verification_id, "V-1");
        assert.equal((await client.plans.listVerifications("plan-1")).length, 0);
        assert.equal((await client.plans.createAssumption("plan-1", { assumption_id: "A-1", encrypted_text: "cipher-assumption", created_at: 100 })).assumption_id, "A-1");
        assert.equal((await client.plans.listAssumptions("plan-1")).length, 0);
        assert.equal((await client.plans.updateAssumption("plan-1", "A-1", { status: "confirmed" })).status, "confirmed");
        assert.equal((await client.plans.createReferencePattern("plan-1", { pattern_id: "RP-1", encrypted_title: "cipher-pattern", created_at: 100 })).pattern_id, "RP-1");
        assert.equal((await client.plans.listReferencePatterns("plan-1")).length, 0);
        assert.equal((await client.plans.addVerificationEvidence("plan-1", "V-1", { status: "passed" })).status, "passed");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-plans?status=draft&chat_id=chat-1"],
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
