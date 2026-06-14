/**
 * Unit tests for CLI account deletion SDK methods.
 *
 * The CLI deletion command is stricter than the web flow: it always requires a
 * verified email code and additionally sends TOTP when 2FA is configured. These
 * tests verify the backend request contract without network access.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/account-delete.test.ts
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

function testSession() {
  return {
    apiUrl: "https://api.example.test",
    sessionId: "session-1",
    wsToken: "ws-token",
    cookies: { sid: "cookie" },
    masterKeyExportedB64: "AA==",
    emailEncryptionKeyB64: "email-key-b64",
    hashedEmail: "hashed-email",
    userEmailSalt: "email-salt",
    createdAt: Date.now(),
    authorizerDeviceName: null,
    autoLogoutMinutes: null,
  };
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
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  try {
    return await run(calls);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

describe("CLI account deletion SDK", () => {
  it("requests and verifies the delete-account email code", async () => {
    await withMockFetch(() => ({ success: true, message: "ok" }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      await client.requestDeleteAccountEmailCode();
      await client.verifyDeleteAccountEmailCode("123456");

      assert.strictEqual(calls[0].url, "https://api.example.test/v1/settings/request-action-verification");
      assert.deepStrictEqual(calls[0].body, {
        action: "delete_account",
        email_encryption_key: "email-key-b64",
      });
      assert.strictEqual(calls[1].url, "https://api.example.test/v1/settings/verify-action-code");
      assert.deepStrictEqual(calls[1].body, {
        action: "delete_account",
        code: "123456",
      });
    });
  });

  it("sends CLI-only email verification plus TOTP to delete-account", async () => {
    const originalHome = process.env.HOME;
    const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-delete-"));
    process.env.HOME = tempHome;
    try {
      await withMockFetch(() => ({ success: true, message: "deletion queued" }), async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

        const result = await client.deleteAccountWithCliVerification("654321");

        assert.deepStrictEqual(result, { success: true, message: "deletion queued" });
        assert.strictEqual(calls[0].url, "https://api.example.test/v1/settings/delete-account");
        assert.deepStrictEqual(calls[0].body, {
          confirm_data_deletion: true,
          auth_method: "2fa_otp",
          auth_code: "654321",
          email_encryption_key: "email-key-b64",
          require_email_verification: true,
        });
      });
    } finally {
      if (originalHome === undefined) delete process.env.HOME;
      else process.env.HOME = originalHome;
      rmSync(tempHome, { recursive: true, force: true });
    }
  });
});
