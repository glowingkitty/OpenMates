/**
 * Shared immutable vectors for browser chat completion recovery crypto.
 *
 * Vitest executes the browser-compatible implementation under Node WebCrypto,
 * while consuming the same language-neutral fixture as backend, CLI, pip, and
 * Apple tests.
 */

import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  type ChatCompletionRecoveryEnvelope,
  buildRecoveryAssociatedData,
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  sealChatCompletionRecoveryPayload,
} from "./chatCompletionRecovery";

const MAX_PAYLOAD_BYTES = 16 * 1024 * 1024;
const mockedCrypto = globalThis.crypto;
const vectors = JSON.parse(
  readFileSync(
    new URL("../../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json", import.meta.url),
    "utf8",
  ),
).vectors;

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, writable: true });
});

afterAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: mockedCrypto, writable: true });
});

describe("chat completion recovery shared vectors", () => {
  for (const vector of vectors) {
    it(`matches exact bytes for ${vector.name}`, async () => {
      const keypair = await deriveChatCompletionRecoveryKeypair(
        vector.chat_key,
        vector.chat_id,
        vector.key_version,
      );
      expect(keypair.privateKey).toBe(vector.recovery_private_key);
      expect(keypair.publicKey).toBe(vector.recovery_public_key);
      expect(buildRecoveryAssociatedData(vector)).toBe(vector.associated_data);

      const envelope = await sealChatCompletionRecoveryPayload(
        new TextEncoder().encode(vector.plaintext),
        {
          recoveryPublicKey: vector.recovery_public_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
          ephemeralPrivateKey: vector.ephemeral_private_key,
          nonce: vector.nonce,
        },
      );
      expect(envelope).toEqual(vector.envelope);

      const opened = await openChatCompletionRecoveryEnvelope(envelope, {
        recoveryPrivateKey: keypair.privateKey,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: vector.turn_id,
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      });
      expect(new TextDecoder().decode(opened)).toBe(vector.plaintext);
    });

    for (const field of ["ciphertext", "nonce", "epk"] as const) {
      it(`rejects ${field} tampering for ${vector.name}`, async () => {
        const encoded = vector.envelope[field];
        const envelope = {
          ...vector.envelope,
          [field]: `${encoded[0] === "A" ? "B" : "A"}${encoded.slice(1)}`,
        };
        await expect(openChatCompletionRecoveryEnvelope(envelope, {
          recoveryPrivateKey: vector.recovery_private_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
        })).rejects.toThrow();
      });
    }

    it(`rejects associated-data tampering for ${vector.name}`, async () => {
      await expect(openChatCompletionRecoveryEnvelope(vector.envelope, {
        recoveryPrivateKey: vector.recovery_private_key,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      })).rejects.toThrow();
    });

    it(`rejects malformed envelopes for ${vector.name}`, async () => {
      const options = {
        recoveryPrivateKey: vector.recovery_private_key,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: vector.turn_id,
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      };
      const malformed = [
        { ...vector.envelope, v: 2 },
        { ...vector.envelope, unexpected: "field" },
        { v: 1, epk: vector.envelope.epk, nonce: vector.envelope.nonce },
        { ...vector.envelope, nonce: `${vector.envelope.nonce}=` },
        { ...vector.envelope, epk: "A" },
        { ...vector.envelope, ciphertext: "AA" },
      ];

      for (const envelope of malformed) {
        await expect(openChatCompletionRecoveryEnvelope(
          envelope as ChatCompletionRecoveryEnvelope,
          options,
        )).rejects.toThrow();
      }
    });

    it(`rejects an all-zero X25519 shared secret for ${vector.name}`, async () => {
      const zeroPublicKey = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
      await expect(openChatCompletionRecoveryEnvelope(
        { ...vector.envelope, epk: zeroPublicKey },
        {
          recoveryPrivateKey: vector.recovery_private_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
        },
      )).rejects.toThrow();
    });

    it(`rejects payloads larger than 16 MiB for ${vector.name}`, async () => {
      await expect(sealChatCompletionRecoveryPayload(
        new Uint8Array(MAX_PAYLOAD_BYTES + 1),
        {
          recoveryPublicKey: vector.recovery_public_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
        },
      )).rejects.toThrow("plaintext must be no larger than");
    });
  }
});
