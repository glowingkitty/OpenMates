import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { OpenMates, OpenMatesUnavailableError } from "../src/sdk.ts";
import { bytesToBase64, createApiKeyCryptoMaterial, unwrapApiKeyMasterKey } from "../src/crypto.ts";

describe("SDK separated credential", () => {
  // contract-test: direct surface=sdks.npm assertions=sdk.auth.credential-separation
  it("sends only the bearer and cannot unwrap the account key with that bearer", async () => {
    const material = await createApiKeyCryptoMaterial("test", bytesToBase64(randomBytes(32)));
    const [bearer, secret] = material.apiKey.split(".");
    assert.ok(secret);
    assert.equal(material.apiKeyHash, createHash("sha256").update(bearer).digest("hex"));
    assert.equal(await unwrapApiKeyMasterKey({
      apiKey: `${bearer}.${"x".repeat(secret.length)}`,
      encryptedMasterKeyB64: material.encryptedMasterKey,
      saltB64: material.saltB64,
      keyIvB64: material.keyIv,
    }), null);

    const server = createServer((request, response) => {
      assert.equal(request.headers.authorization, `Bearer ${bearer}`);
      assert.equal(JSON.stringify(request.headers).includes(secret), false);
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      assert.ok(address && typeof address === "object");
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl: `http://127.0.0.1:${address.port}`, deviceId: "test-device" });
      await client.get("/v1/sdk/test");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: direct surface=sdks.npm assertions=sdk.surface.semantic-parity,sdk.auth.legacy-key-migration
  it("returns a typed first-party verification exclusion for key management", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", deviceId: "test-device" });
    await assert.rejects(client.apiKeys.create({ name: "new" }), (error: unknown) =>
      error instanceof OpenMatesUnavailableError && error.code === "unavailable_requires_first_party_verification");
    await assert.rejects(client.apiKeys.revoke("old"), (error: unknown) =>
      error instanceof OpenMatesUnavailableError && error.code === "unavailable_requires_first_party_verification");
  });
});
