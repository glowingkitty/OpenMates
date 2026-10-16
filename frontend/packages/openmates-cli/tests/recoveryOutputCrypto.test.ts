import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { openRecoveryOutputEnvelope, type RecoveryOutputIdentity } from "../src/crypto.ts";

const vector = JSON.parse(readFileSync(
  new URL("../../../../backend/tests/fixtures/chat_recovery_output_v2.json", import.meta.url), "utf8",
)) as {
  recovery_private_key: string;
  identity: Record<string, string | number>;
  plaintext: string;
  envelope: { v: 2; epk: string; nonce: string; ciphertext: string };
};

const identity: RecoveryOutputIdentity & { recoveryPrivateKey: string } = {
  recoveryPrivateKey: vector.recovery_private_key,
  ownerId: String(vector.identity.owner_id),
  rootChatId: String(vector.identity.root_chat_id),
  targetChatId: String(vector.identity.target_chat_id),
  turnId: String(vector.identity.turn_id),
  recordId: String(vector.identity.record_id),
  subjectId: String(vector.identity.subject_id),
  outputKind: "message",
  outputVersion: Number(vector.identity.output_version),
  keyVersion: Number(vector.identity.key_version),
};

describe("typed recovery output authenticated encryption", () => {
  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
  it("opens the shared v2 envelope using the root chat recovery key", async () => {
    const plaintext = await openRecoveryOutputEnvelope(vector.envelope, identity);
    assert.equal(new TextDecoder().decode(plaintext), vector.plaintext);
  });

  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
  it("rejects changed target, subject, output kind, and version", async () => {
    for (const changed of [
      { targetChatId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
      { subjectId: "another-output" },
      { outputKind: "summary" as const },
      { outputVersion: identity.outputVersion + 1 },
    ]) {
      await assert.rejects(openRecoveryOutputEnvelope(vector.envelope, { ...identity, ...changed }));
    }
  });
});
