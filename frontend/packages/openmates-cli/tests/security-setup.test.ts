/**
 * Unit tests for CLI security setup SDK contracts.
 *
 * Covers TOTP setup, backup-code confirmation, and recovery-key confirmation
 * against mocked network calls.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/security-setup.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

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
    masterKeyExportedB64: Buffer.from(new Uint8Array(32).fill(7)).toString("base64"),
    emailEncryptionKeyB64: "email-key-b64",
    hashedEmail: "hashed-email",
    userEmailSalt: Buffer.from(new Uint8Array(16).fill(3)).toString("base64"),
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

describe("CLI security setup SDK", () => {
  it("runs TOTP setup and backup-code confirmation endpoint contracts", async () => {
    await withMockFetch((call) => {
      if (call.url.endsWith("/initiate")) return { success: true, message: "ok", secret: "OTPSECRET", otpauth_url: "otpauth://totp/OpenMates" };
      if (call.url.endsWith("/request-backup-codes")) return { success: true, message: "ok", backup_codes: ["one", "two"] };
      return { success: true, message: "ok" };
    }, async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      const setup = await client.startTotpSetup();
      await client.verifyTotpSetup("123456");
      await client.setTotpProvider("Aegis");
      const backup = await client.requestBackupCodes();
      await client.confirmBackupCodesStored();

      assert.strictEqual(setup.secret, "OTPSECRET");
      assert.deepStrictEqual(backup.backup_codes, ["one", "two"]);
      assert.deepStrictEqual(calls.map((call) => call.url), [
        "https://api.example.test/v1/auth/2fa/setup/initiate",
        "https://api.example.test/v1/auth/2fa/setup/verify-signup",
        "https://api.example.test/v1/auth/2fa/setup/provider",
        "https://api.example.test/v1/auth/2fa/setup/request-backup-codes",
        "https://api.example.test/v1/auth/2fa/setup/confirm-codes-stored",
      ]);
      assert.deepStrictEqual(calls[0].body, { email_encryption_key: "email-key-b64" });
      assert.deepStrictEqual(calls[1].body, { code: "123456" });
      assert.deepStrictEqual(calls[2].body, { provider: "Aegis" });
      assert.deepStrictEqual(calls[4].body, { confirmed: true });
    });
  });

  it("creates and confirms recovery key material without sending the raw key", async () => {
    await withMockFetch(() => ({ success: true, message: "ok" }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      const recovery = await client.createAndConfirmRecoveryKey();

      assert.match(recovery.recoveryKey, /^.{24}$/);
      assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/recovery-key/confirm-stored");
      assert.strictEqual(calls[0].body?.confirmed, true);
      assert.ok(typeof calls[0].body?.lookup_hash === "string");
      assert.ok(typeof calls[0].body?.wrapped_master_key === "string");
      assert.ok(typeof calls[0].body?.key_iv === "string");
      assert.ok(typeof calls[0].body?.salt === "string");
      assert.ok(!JSON.stringify(calls[0].body).includes(recovery.recoveryKey));
    });
  });
});
