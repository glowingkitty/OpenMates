/**
 * Shared immutable vectors for browser chat completion recovery crypto.
 *
 * Vitest executes the browser-compatible implementation under Node WebCrypto,
 * while consuming the same language-neutral fixture as backend, CLI, pip, and
 * Apple tests.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  buildRecoveryAssociatedData,
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  sealChatCompletionRecoveryPayload,
} from "./chatCompletionRecovery";

const vectors = JSON.parse(
  readFileSync(
    new URL("../../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json", import.meta.url),
    "utf8",
  ),
).vectors;

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
  }
});
