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
import { createCipheriv, randomBytes } from "node:crypto";

import { OpenMatesClient } from "../dist/index.js";
import { createSignupCryptoMaterial, deriveKeyFromPassword, hashKey } from "../src/crypto.ts";

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
    const result = handler(call);
    const status = typeof result === "object" && result !== null &&
      typeof (result as { httpStatus?: unknown }).httpStatus === "number"
      ? (result as { httpStatus: number }).httpStatus : 200;
    const body = status === 200 ? result : (result as { body: unknown }).body;
    const successfulLogin = call.url.endsWith("/login") &&
      typeof result === "object" && result !== null &&
      (result as { success?: boolean; tfa_required?: boolean }).success === true &&
      (result as { tfa_required?: boolean }).tfa_required !== true;
    return new Response(JSON.stringify(body), {
      status,
      headers: {
        "content-type": "application/json",
        ...(call.url.endsWith("/setup_password") || successfulLogin
          ? { "set-cookie": "auth_refresh_token=test-cookie; Path=/" }
          : {}),
      },
    });
  }) as typeof fetch;
  try {
    return await run(calls);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

describe("CLI signup SDK", () => {
  // contract-test: direct surface=cli assertions=auth.signup.current-flow,auth.signup.transaction-bound
  it("requests and verifies email code using signup endpoints", async () => {
    await withMockFetch(() => ({ success: true, message: "ok", signup_transaction_token: "one-use-proof" }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });

      await client.requestSignupEmailCode({ email: "USER@example.com", inviteCode: "INVITE", language: "en" });
      const verification = await client.verifySignupEmailCode({ email: "USER@example.com", username: "alice", inviteCode: "INVITE", code: "123456" });
      assert.strictEqual(verification.signup_transaction_token, "one-use-proof");

      assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/request_confirm_email_code");
      assert.strictEqual(calls[0].body?.email, "user@example.com");
      assert.strictEqual(calls[0].body?.invite_code, "INVITE");
      assert.strictEqual(calls[1].url, "https://api.example.test/v1/auth/check_confirm_email_code");
      assert.strictEqual(calls[1].body?.code, "123456");
    });
  });

  // contract-test: supporting surface=cli assertions=auth.signup.access-gates,auth.lookup.anti-enumeration
  it("accepts generic success when signup email already belongs to an account", async () => {
    await withMockFetch(() => ({
      success: true,
      message: "If this email can create an account, a verification code will be sent.",
    }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });

      const result = await client.requestSignupEmailCode({ email: "USER@example.com", language: "de", darkmode: true });

      assert.deepStrictEqual(result, {
        success: true,
        message: "If this email can create an account, a verification code will be sent.",
      });
      assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/request_confirm_email_code");
      assert.strictEqual(calls[0].body?.email, "user@example.com");
      assert.strictEqual(calls[0].body?.language, "de");
      assert.strictEqual(calls[0].body?.darkmode, true);
    });
  });

  // contract-test: direct surface=cli assertions=auth.signup.current-flow,auth.signup.transaction-bound,auth.keys.client-wrapped
  it("posts setup_password payload and stores an immediately usable session", async () => {
    await withTempHome(async () => {
      await withMockFetch(() => ({ success: true, message: "created", user: { id: "user-1", username: "alice" } }), async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });

        const result = await client.setupPasswordAccount({
          email: "alice@example.com",
          username: "alice",
          password: "correct horse battery staple",
          inviteCode: "INVITE",
          signupTransactionToken: "one-use-proof",
        });

        assert.strictEqual(result.success, true);
        assert.strictEqual(client.hasSession(), true);
        assert.strictEqual(calls[0].url, "https://api.example.test/v1/auth/setup_password");
        assert.strictEqual(calls[0].body?.username, "alice");
        assert.strictEqual(calls[0].body?.invite_code, "INVITE");
        assert.strictEqual(calls[0].body?.signup_transaction_token, "one-use-proof");
        assert.ok(typeof calls[0].body?.hashed_email === "string");
        assert.ok(typeof calls[0].body?.encrypted_email === "string");
        assert.ok(typeof calls[0].body?.encrypted_master_key === "string");
        assert.strictEqual(calls[0].body?.credential_version, 2);
        assert.match(String(calls[0].body?.password_auth_key), /^[A-Za-z0-9_-]{43}$/);
        assert.strictEqual(calls[0].body?.lookup_hash, undefined);
        assert.strictEqual(calls[0].body?.salt, calls[0].body?.user_email_salt);
      });
    });
  });
});

describe("CLI programmatic password login", () => {
  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.login.verified-method
  it("sends a one-use v2 proof and opens the returned v2 wrapper", async () => {
    await withTempHome(async () => {
      const email = "alice@example.com";
      const password = "Correct Horse Battery Staple!";
      const material = await createSignupCryptoMaterial(email, password);
      const nonce = Buffer.from(Uint8Array.from({ length: 32 }, (_, index) => index + 32)).toString("base64url");
      await withMockFetch((call) => {
        if (call.url.endsWith("/lookup")) return { user_email_salt: material.userEmailSaltB64 };
        if (call.url.endsWith("/challenge")) return { challenge_id: "challenge-1", nonce };
        if (call.url.endsWith("/login")) return {
          success: true, ws_token: "short-lived-ws", user: {
            id: "user-1", credential_version: 2,
            encrypted_key: material.encryptedMasterKey, key_iv: material.keyIv,
            salt: material.saltB64, user_email_salt: material.userEmailSaltB64,
          },
        };
        throw new Error(`Unexpected route ${call.url}`);
      }, async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        assert.deepEqual(await client.loginWithPassword({ email, password }), {
          status: "authenticated", credentialVersion: 2,
        });
        assert.equal(client.hasSession(), true);
        assert.equal(calls[2].body?.credential_version, 2);
        assert.equal(calls[2].body?.challenge_id, "challenge-1");
        assert.match(String(calls[2].body?.password_proof), /^[A-Za-z0-9_-]{43}$/);
        assert.equal(calls[2].body?.lookup_hash, undefined);
        assert.equal(calls[2].body?.password_auth_key, undefined);
      });
    });
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.login.method-convergence
  it("preserves a legacy password login after a uniform v2 challenge", async () => {
    await withTempHome(async () => {
      const email = "legacy@example.com";
      const password = "legacy password";
      const userEmailSalt = randomBytes(16);
      const wrapperSalt = randomBytes(16);
      const iv = randomBytes(12);
      const master = randomBytes(32);
      const cipher = createCipheriv("aes-256-gcm", await deriveKeyFromPassword(password, wrapperSalt), iv);
      const encrypted = Buffer.concat([cipher.update(master), cipher.final(), cipher.getAuthTag()]).toString("base64");
      const nonce = randomBytes(32).toString("base64url");
      let stagedWrapper: Record<string, unknown> | null = null;
      await withMockFetch((call) => {
        if (call.url.endsWith("/lookup")) return { user_email_salt: userEmailSalt.toString("base64") };
        if (call.url.endsWith("/challenge")) return { challenge_id: "challenge-2", nonce };
        if (call.url.endsWith("/login") && call.body?.credential_version === 2) return { success: false, message: "Invalid credentials" };
        if (call.url.endsWith("/login")) return {
          success: true, user: {
            id: "legacy-user", credential_version: 1, encrypted_key: encrypted,
            key_iv: iv.toString("base64"), salt: wrapperSalt.toString("base64"),
            user_email_salt: userEmailSalt.toString("base64"),
          },
        };
        if (call.url.endsWith("/migrate")) {
          stagedWrapper = call.body;
          return { success: true, migration_status: "pending_confirmation", legacy_password_retained: true };
        }
        if (call.url.endsWith("/staged-challenge")) return {
          challenge_id: "0123456789abcdef0123456789abcdef", nonce,
        };
        if (call.url.endsWith("/verify-staged")) return {
          encrypted_key: stagedWrapper?.encrypted_master_key,
          salt: stagedWrapper?.salt,
          key_iv: stagedWrapper?.key_iv,
          credential_version: 2,
        };
        if (call.url.endsWith("/confirm-migration")) return {
          success: true, migration_status: "typed_retired", legacy_password_retained: true,
        };
        throw new Error(`Unexpected route ${call.url}`);
      }, async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        assert.deepEqual(await client.loginWithPassword({ email, password }), {
          status: "authenticated", credentialVersion: 1, migrationStatus: "typed_retired",
        });
        assert.equal(client.hasSession(), true);
        assert.equal(calls[3].body?.lookup_hash, await hashKey(password, userEmailSalt));
        assert.equal(calls[4].body?.old_lookup_hash, await hashKey(password, userEmailSalt));
        assert.match(String(calls[4].body?.password_auth_key), /^[A-Za-z0-9_-]{43}$/);
        assert.equal(calls[4].body?.salt, userEmailSalt.toString("base64"));
        assert.equal(calls[4].body?.lookup_hash, undefined);
        assert.equal(calls[6].body?.challenge_id, "0123456789abcdef0123456789abcdef");
        assert.match(String(calls[6].body?.password_proof), /^[A-Za-z0-9_-]{43}$/);
        assert.equal(calls[7].body && Object.keys(calls[7].body).length, 0);
      });
    });
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
  it("keeps a legacy session decryptable when background migration needs recent verification", async () => {
    await withTempHome(async () => {
      const email = "legacy@example.com";
      const password = "legacy password";
      const userEmailSalt = randomBytes(16);
      const wrapperSalt = randomBytes(16);
      const iv = randomBytes(12);
      const master = randomBytes(32);
      const cipher = createCipheriv("aes-256-gcm", await deriveKeyFromPassword(password, wrapperSalt), iv);
      const encrypted = Buffer.concat([cipher.update(master), cipher.final(), cipher.getAuthTag()]).toString("base64");
      const nonce = randomBytes(32).toString("base64url");
      await withMockFetch((call) => {
        if (call.url.endsWith("/lookup")) return { user_email_salt: userEmailSalt.toString("base64") };
        if (call.url.endsWith("/challenge")) return { challenge_id: "challenge-2", nonce };
        if (call.url.endsWith("/login") && call.body?.credential_version === 2) {
          return { success: false, message: "Invalid credentials" };
        }
        if (call.url.endsWith("/login")) return {
          success: true, user: {
            id: "legacy-user", credential_version: 1, encrypted_key: encrypted,
            key_iv: iv.toString("base64"), salt: wrapperSalt.toString("base64"),
            user_email_salt: userEmailSalt.toString("base64"),
          },
        };
        if (call.url.endsWith("/migrate")) return {
          httpStatus: 428, body: { detail: { error: "recent_verification_required" } },
        };
        throw new Error(`Migration deferral must not request a verification email: ${call.url}`);
      }, async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        assert.deepEqual(await client.loginWithPassword({ email, password }), {
          status: "authenticated", credentialVersion: 1, migrationStatus: "deferred_recent_verification",
        });
        assert.equal(client.hasSession(), true);
        assert.equal(calls.length, 5);
        assert.equal(calls.at(-1)?.url.endsWith("/migrate"), true);
      });
    });
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection
  it("does not send a legacy lookup hash when the v2 login service is unavailable", async () => {
    await withTempHome(async () => {
      const originalFetch = globalThis.fetch;
      const calls: FetchCall[] = [];
      globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
        const call: FetchCall = {
          url: String(input), method: init?.method ?? "GET",
          body: typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : null,
        };
        calls.push(call);
        if (call.url.endsWith("/lookup")) return Response.json({ user_email_salt: randomBytes(16).toString("base64") });
        if (call.url.endsWith("/challenge")) return Response.json({
          challenge_id: "challenge-3", nonce: randomBytes(32).toString("base64url"),
        });
        return Response.json({ message: "Unavailable" }, { status: 503 });
      }) as typeof fetch;
      try {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        await assert.rejects(client.loginWithPassword({ email: "alice@example.com", password: "password" }), /unavailable.*503/i);
        assert.equal(calls.length, 3);
        assert.equal(calls[2].body?.credential_version, 2);
        assert.equal(client.hasSession(), false);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.proofs.single-use
  it("uses a fresh v2 challenge for the OTP follow-up", async () => {
    await withTempHome(async () => {
      const email = "alice@example.com";
      const password = "Correct Horse Battery Staple!";
      const material = await createSignupCryptoMaterial(email, password);
      let challengeCount = 0;
      await withMockFetch((call) => {
        if (call.url.endsWith("/lookup")) return { user_email_salt: material.userEmailSaltB64 };
        if (call.url.endsWith("/challenge")) {
          challengeCount += 1;
          return {
            challenge_id: `challenge-${challengeCount}`,
            nonce: Buffer.alloc(32, challengeCount).toString("base64url"),
          };
        }
        if (call.url.endsWith("/login") && call.body?.credential_version === 1) {
          return { success: true, tfa_required: true };
        }
        if (call.url.endsWith("/login") && !call.body?.tfa_code) {
          return { success: true, tfa_required: true };
        }
        if (call.url.endsWith("/login")) return {
          success: true, user: {
            id: "user-1", credential_version: 2,
            encrypted_key: material.encryptedMasterKey, key_iv: material.keyIv,
            salt: material.saltB64, user_email_salt: material.userEmailSaltB64,
          },
        };
        throw new Error(`Unexpected route ${call.url}`);
      }, async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        assert.deepEqual(await client.loginWithPassword({ email, password }), { status: "tfa_required" });
        assert.equal(client.hasSession(), false);
        assert.deepEqual(await client.loginWithPassword({ email, password, tfaCode: "123456" }), {
          status: "authenticated", credentialVersion: 2,
        });
        assert.equal(challengeCount, 2);
        const v2Requests = calls.filter((call) => call.url.endsWith("/login") && call.body?.credential_version === 2);
        assert.equal(v2Requests.length, 2);
        assert.notEqual(v2Requests[0].body?.challenge_id, v2Requests[1].body?.challenge_id);
        assert.notEqual(v2Requests[0].body?.password_proof, v2Requests[1].body?.password_proof);
      });
    });
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.keys.independent-unlock
  it("never confirms migration when the staged wrapper opens a different master key", async () => {
    await withTempHome(async () => {
      const password = "Correct Horse Battery Staple!";
      const foreign = await createSignupCryptoMaterial("other@example.com", password);
      await withMockFetch((call) => {
        if (call.url.endsWith("/setup_password")) return { success: true, user: { id: "user-1" } };
        if (call.url.endsWith("/migrate")) return {
          success: true, migration_status: "pending_confirmation", legacy_password_retained: false,
        };
        if (call.url.endsWith("/staged-challenge")) return {
          challenge_id: "0123456789abcdef0123456789abcdef", nonce: randomBytes(32).toString("base64url"),
        };
        if (call.url.endsWith("/verify-staged")) return {
          encrypted_key: foreign.encryptedMasterKey, salt: foreign.saltB64,
          key_iv: foreign.keyIv, credential_version: 2,
        };
        throw new Error(`Unexpected route ${call.url}`);
      }, async (calls) => {
        const client = new OpenMatesClient({ apiUrl: "https://api.example.test" });
        await client.setupPasswordAccount({
          email: "alice@example.com", username: "alice", password,
          signupTransactionToken: "one-use-proof",
        });
        await assert.rejects(client.migrateLegacyPasswordCredential(password), /does not match the account key/);
        assert.equal(client.hasSession(), true);
        assert.equal(calls.length, 4);
        assert.ok(calls[3].url.endsWith("/verify-staged"));
      });
    });
  });
});
