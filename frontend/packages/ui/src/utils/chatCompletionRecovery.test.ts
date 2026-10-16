// contract-test-file: infrastructure
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
  openRecoveryOutputEnvelope,
  sealChatCompletionRecoveryPayload,
  sealChatCompletionRecoveryPayloadForTest,
} from "./chatCompletionRecovery";

const MAX_PAYLOAD_BYTES = 16 * 1024 * 1024;
const mockedCrypto = globalThis.crypto;
const vectors = JSON.parse(
  readFileSync(
    new URL("../../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json", import.meta.url),
    "utf8",
  ),
).vectors;
const outputV2 = JSON.parse(readFileSync(
  new URL("../../../../../backend/tests/fixtures/chat_recovery_output_v2.json", import.meta.url),
  "utf8",
));

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, writable: true });
});

afterAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: mockedCrypto, writable: true });
});

it("opens Python-sealed v2 child output and rejects revision substitution", async () => {
  const identity = {
    recoveryPrivateKey: outputV2.recovery_private_key,
    ownerId: outputV2.identity.owner_id,
    rootChatId: outputV2.identity.root_chat_id,
    targetChatId: outputV2.identity.target_chat_id,
    turnId: outputV2.identity.turn_id,
    recordId: outputV2.identity.record_id,
    subjectId: outputV2.identity.subject_id,
    outputKind: outputV2.identity.output_kind as "message",
    outputVersion: outputV2.identity.output_version,
    keyVersion: outputV2.identity.key_version,
  };
  const opened = await openRecoveryOutputEnvelope(outputV2.envelope, identity);
  expect(new TextDecoder().decode(opened)).toBe(outputV2.plaintext);
  await expect(openRecoveryOutputEnvelope(outputV2.envelope, {
    ...identity, outputVersion: 2,
  })).rejects.toThrow();
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

      const envelope = await sealChatCompletionRecoveryPayloadForTest(
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

    it(`rejects deterministic production sealing inputs for ${vector.name}`, async () => {
      await expect(sealChatCompletionRecoveryPayload(
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
        } as Parameters<typeof sealChatCompletionRecoveryPayload>[1],
      )).rejects.toThrow("deterministic recovery sealing inputs are test-only");
    });

    it(`uses fresh production sealing inputs for ${vector.name}`, async () => {
      const options = {
        recoveryPublicKey: vector.recovery_public_key,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: vector.turn_id,
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      };
      const plaintext = new TextEncoder().encode(vector.plaintext);

      const first = await sealChatCompletionRecoveryPayload(plaintext, options);
      const second = await sealChatCompletionRecoveryPayload(plaintext, options);

      expect(first.epk).not.toBe(second.epk);
      expect(first.nonce).not.toBe(second.nonce);
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
