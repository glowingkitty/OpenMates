/**
 * Unit tests for CLI signup SDK contracts.
 *
 * These tests mock fetch and use a temporary HOME so password signup can save a
 * local session without network access or touching the real operator account.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/signup.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { OpenMatesClient } from "../dist/index.js";

type FetchCall = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

async function withTempHome<T>(run: () => Promise<T>): Promise<T> {
  const originalHome = process.env.HOME;
  const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-signup-"));
  process.env.HOME = tempHome;
  try {
    return await run();
  } finally {
    if (originalHome === undefined) delete process.env.HOME;
    else process.env.HOME = originalHome;
    rmSync(tempHome, { recursive: true, force: true });
  }
}

async function withMockFetch<T>(handler: (call: FetchCall) => unknown, run: (calls: FetchCall[]) => Promise<T>): Promise<T> {
  const originalFetch = globalThis.fetch;
  const calls: FetchCall[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const call: FetchCall = {
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : null,
    };
    calls.push(call);
    return new Response(JSON.stringify(handler(call)), {
      status: 200,
      headers: { "content-type": "application/json", "set-cookie": "om_refresh=test-cookie; Path=/" },
    });
  }) as typeof fetch;
  try {
    return await run(calls);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

describe("CLI signup SDK", () => {
  it("requests and verifies email code using signup endpoints", async () => {
    await withMockFetch(() => ({ success: true, message: "ok" }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });

      await client.requestSignupEmailCode({ email: "USER@example.com", inviteCode: "INVITE", language: "en" });
      await client.verifySignupEmailCode({ email: "USER@example.com", username: "alice", inviteCode: "INVITE", code: "123456" });

      assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/request_confirm_email_code");
      assert.strictEqual(calls[0].body?.email, "user@example.com");
      assert.strictEqual(calls[0].body?.invite_code, "INVITE");
      assert.strictEqual(calls[1].url, "https://api.example.test/v1/auth/check_confirm_email_code");
      assert.strictEqual(calls[1].body?.code, "123456");
    });
  });

  it("posts setup_password payload and stores an immediately usable session", async () => {
    await withTempHome(async () => {
      await withMockFetch(() => ({ success: true, message: "created", user: { id: "user-1", username: "alice" } }), async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });

        const result = await client.setupPasswordAccount({
          email: "alice@example.com",
          username: "alice",
          password: "correct horse battery staple",
          inviteCode: "INVITE",
        });

        assert.strictEqual(result.success, true);
        assert.strictEqual(client.hasSession(), true);
        assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/setup_password");
        assert.strictEqual(calls[0].body?.username, "alice");
        assert.strictEqual(calls[0].body?.invite_code, "INVITE");
        assert.ok(typeof calls[0].body?.hashed_email === "string");
        assert.ok(typeof calls[0].body?.encrypted_email === "string");
        assert.ok(typeof calls[0].body?.encrypted_master_key === "string");
        assert.ok(typeof calls[0].body?.lookup_hash === "string");
      });
    });
  });
});
