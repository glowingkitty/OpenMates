/**
 * OpenMates key-wrapper parity contract tests.
 *
 * Purpose: verify SDK chat decrypt paths prefer canonical wrapper rows while
 * preserving row-level encrypted_chat_key fallback during migration.
 * Security: uses synthetic keys and a local HTTP server; no real account data,
 * chat content, or API keys leave the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/key-wrappers.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates } from "../src/sdk.ts";
import {
  bytesToBase64,
  createApiKeyCryptoMaterial,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
} from "../src/crypto.ts";

async function withServer(
  handler: (request: IncomingMessage) => unknown,
  run: (apiUrl: string) => Promise<void>,
  expectedAuthorization: string,
): Promise<void> {
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    assert.equal(request.headers.authorization, expectedAuthorization);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(handler(request)));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMates SDK key wrappers", () => {
  it("decrypts loaded chats using master wrapper rows before row-level fallback", async () => {
    const masterKey = new Uint8Array(randomBytes(32));
    const wrapperChatKey = new Uint8Array(randomBytes(32));
    const staleRowChatKey = new Uint8Array(randomBytes(32));
    const material = await createApiKeyCryptoMaterial("wrapper parity", bytesToBase64(masterKey));
    const chatId = "11111111-1111-4111-8111-111111111111";
    const hashedChatId = createHash("sha256").update(chatId).digest("hex");
    const encryptedChatKey = await encryptBytesWithAesGcm(wrapperChatKey, masterKey);
    const staleEncryptedChatKey = await encryptBytesWithAesGcm(staleRowChatKey, masterKey);

    await withServer(
      (request) => {
        if (request.url === "/v1/sdk/session") {
          return {
            key_wrapper: {
              encrypted_key: material.encryptedMasterKey,
              salt: material.saltB64,
              key_iv: material.keyIv,
            },
          };
        }
        throw new Error(`unexpected ${request.url}`);
      },
      async (apiUrl) => {
        const sdk = new OpenMates({ apiKey: material.apiKey, apiUrl });
        const decrypted = await sdk.decryptLoadedChatPayload({
          chat: {
            id: chatId,
            encrypted_chat_key: staleEncryptedChatKey,
            encrypted_title: await encryptWithAesGcmCombined("Wrapper Title", wrapperChatKey),
          },
          messages: [
            JSON.stringify({
              id: "message-1",
              encrypted_content: await encryptWithAesGcmCombined("Wrapper message", wrapperChatKey),
            }),
          ],
          chat_key_wrappers: [{
            id: "wrapper-1",
            hashed_chat_id: hashedChatId,
            key_type: "master",
            encrypted_chat_key: encryptedChatKey,
          }],
        });

        assert.equal((decrypted.chat as Record<string, unknown>).title, "Wrapper Title");
        assert.equal((decrypted.messages as Array<Record<string, unknown>>)[0].content, "Wrapper message");
      },
      `Bearer ${material.apiKey}`,
    );
  });
});
