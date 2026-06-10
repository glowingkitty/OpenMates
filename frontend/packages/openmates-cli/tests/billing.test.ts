/**
 * Unit tests for CLI bank-transfer billing SDK methods.
 *
 * These tests run without network access by replacing global fetch. They verify
 * request paths and bodies for credit and gift-card bank-transfer purchases so
 * the CLI does not regress back to browser-only checkout flows.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/billing.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { OpenMatesClient, type BankTransferOrderDetails } from "../dist/index.js";

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

function orderResponse(orderId: string): BankTransferOrderDetails {
  return {
    order_id: orderId,
    reference: "OM-USER-ABC123",
    iban: "DE89370400440532013000",
    bic: "COBADEFFXXX",
    bank_name: "Test Bank",
    account_holder_name: "OpenMates GmbH",
    amount_eur: "100.00",
    credits_amount: 110000,
    expires_at: "2026-06-16T00:00:00+00:00",
  };
}

describe("CLI bank-transfer billing SDK", () => {
  it("creates credit bank-transfer orders with the local email encryption key", async () => {
    await withMockFetch(() => orderResponse("bt_credit"), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      const result = await client.createBankTransferOrder(110000);

      assert.strictEqual(result.order_id, "bt_credit");
      assert.strictEqual(calls[0].url, "https://api.example.test/v1/payments/create-bank-transfer-order");
      assert.strictEqual(calls[0].method, "POST");
      assert.deepStrictEqual(calls[0].body, {
        credits_amount: 110000,
        currency: "eur",
        email_encryption_key: "email-key-b64",
      });
    });
  });

  it("creates gift-card bank-transfer orders through the dedicated endpoint", async () => {
    await withMockFetch(() => orderResponse("bt_gift"), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      const result = await client.createGiftCardBankTransferOrder(21000);

      assert.strictEqual(result.order_id, "bt_gift");
      assert.strictEqual(calls[0].url, "https://api.example.test/v1/payments/create-gift-card-bank-transfer-order");
      assert.deepStrictEqual(calls[0].body, {
        credits_amount: 21000,
        currency: "eur",
        email_encryption_key: "email-key-b64",
      });
    });
  });

  it("reads gift-card purchase status from the dedicated endpoint", async () => {
    await withMockFetch(() => ({
      order_id: "bt_gift",
      status: "completed",
      credits_amount: 21000,
      amount_eur: "20.00",
      reference: "OM-USER-GIFT",
      expires_at: "2026-06-16T00:00:00+00:00",
      created_at: "2026-06-09T00:00:00+00:00",
      gift_card_code: "OM-GIFT-CODE",
    }), async (calls) => {
      const client = new OpenMatesClient({ apiUrl: "https://api.example.test", session: testSession() });

      const status = await client.getGiftCardPurchaseStatus("bt_gift");

      assert.strictEqual(status.gift_card_code, "OM-GIFT-CODE");
      assert.strictEqual(calls[0].url, "https://api.example.test/v1/payments/gift-card-purchase-status/bt_gift");
      assert.strictEqual(calls[0].method, "GET");
    });
  });
});
