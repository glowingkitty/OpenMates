/**
 * OpenMates npm SDK cleartext boundary tests.
 *
 * Purpose: verify public SDK callers pass/receive cleartext while durable write
 * requests remain encrypted.
 * Security: local HTTP server and synthetic API key only; no data leaves process.
 * Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-cleartext-boundary.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";
import { createApiKeyCryptoMaterial } from "../src/crypto.ts";

const CLEAR_PUBLIC_TASK = "CLEAR_PUBLIC_TASK";
const CLEAR_PUBLIC_PLAN = "CLEAR_PUBLIC_PLAN";
const CLEAR_PUBLIC_PROJECT = "CLEAR_PUBLIC_PROJECT";

type SeenRequest = { method: string | undefined; url: string | undefined; body: any };

function assertNoPlaintextMarker(value: unknown, marker: string): void {
  assert.equal(JSON.stringify(value).includes(marker), false, `${marker} leaked into encrypted storage payload`);
}

async function withServer(
  handler: (request: IncomingMessage, body: any) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
  expectedAuthorization: string,
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

describe("OpenMates npm SDK cleartext boundary", () => {
  it("accepts cleartext asks and sends encrypted durable storage payloads", async () => {
    const masterKey = Buffer.alloc(32, 11);
    const material = await createApiKeyCryptoMaterial("sdk cleartext", masterKey.toString("base64"));

    await withServer(
      (request, body) => {
        if (request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.url === "/v1/user-tasks/ask/plan") {
          return { proposed_tasks: [{ title: CLEAR_PUBLIC_TASK, description: "task body" }] };
        }
        if (request.url === "/v1/user-tasks/ask") {
          assert.equal(Array.isArray(body.encrypted_creates), true);
          assert.equal(typeof body.encrypted_creates[0].encrypted_title, "string");
          assertNoPlaintextMarker(body.encrypted_creates, CLEAR_PUBLIC_TASK);
          return { summary: "Created 1 task.", task: body.encrypted_creates[0], tasks: body.encrypted_creates };
        }
        if (request.url === "/v1/user-plans/ask/plan") {
          return { proposed_plan: { title: CLEAR_PUBLIC_PLAN, goal: "plan goal" } };
        }
        if (request.url === "/v1/user-plans/ask") {
          assert.equal(typeof body.encrypted_create.encrypted_title, "string");
          assertNoPlaintextMarker(body.encrypted_create, CLEAR_PUBLIC_PLAN);
          return { summary: "Created 1 plan.", plan: body.encrypted_create, plans: [body.encrypted_create] };
        }
        if (request.url === "/v1/projects/ask/plan") {
          return { proposed_project: { name: CLEAR_PUBLIC_PROJECT, description: "project body", icon: "folder", color: "blue" } };
        }
        if (request.url === "/v1/projects/ask") {
          assert.equal(typeof body.encrypted_create.encrypted_name, "string");
          assertNoPlaintextMarker(body.encrypted_create, CLEAR_PUBLIC_PROJECT);
          return { summary: "Created 1 project.", project: body.encrypted_create, projects: [body.encrypted_create] };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl, deviceId: "test-device" });
        const task = await client.tasks.ask(`create ${CLEAR_PUBLIC_TASK}`);
        const plan = await client.plans.ask(`create ${CLEAR_PUBLIC_PLAN}`);
        const project = await client.projects.ask(`create ${CLEAR_PUBLIC_PROJECT}`);

        assert.equal((task.tasks as any[])[0].title, CLEAR_PUBLIC_TASK);
        assert.equal((task.tasks as any[])[0].description, "task body");
        assert.equal((plan.plans as any[])[0].title, CLEAR_PUBLIC_PLAN);
        assert.equal((plan.plans as any[])[0].goal, "plan goal");
        assert.equal((project.projects as any[])[0].name, CLEAR_PUBLIC_PROJECT);
        assert.equal((project.projects as any[])[0].description, "project body");
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
