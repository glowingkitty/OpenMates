// contract-test-file: infrastructure
import { test } from "node:test";
import assert from "node:assert/strict";
import { assertCompleteEncryptedEmbedBundle, classifyMessageEmbedAvailability, computeSHA256, encryptEmbed } from "../src/embedCreator.ts";

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
test("required prepared embed encryption fails before a bundle can be sent", async () => {
  await assert.rejects(
    encryptEmbed(
      { embedId: "required-embed", type: "code-code", content: "source", textPreview: "preview", status: "finished" },
      new Uint8Array(2), null, "chat-id", "message-id", "user-id",
    ),
    /Failed to encrypt embed required-embed/,
  );
});

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
test("canonical availability reuses ready heads and rejects unusable or mismatched results", () => {
  const selected = ["reused", "new"];
  const result = classifyMessageEmbedAvailability(selected, [
    { embed_id: "reused", state: "ready" }, { embed_id: "new", state: "missing" },
  ]);
  assert.deepEqual([...result.ready], ["reused"]);
  assert.deepEqual([...result.missing], ["new"]);
  assert.throws(() => classifyMessageEmbedAvailability(selected, [
    { embed_id: "new", state: "missing" }, { embed_id: "reused", state: "ready" },
  ]), /changed identity/);
  assert.throws(() => classifyMessageEmbedAvailability(["unusable"], [
    { embed_id: "unusable", state: "unusable" },
  ]), /no usable key/);
});

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
test("caller-provided encrypted embeds need unique IDs and both scoped wrappers", () => {
  const embed = {
    embed_id: "e", encrypted_content: "cipher", encrypted_type: "cipher-type",
    encrypted_text_preview: "", status: "finished", hashed_chat_id: computeSHA256("chat"),
    hashed_message_id: computeSHA256("message"), hashed_user_id: computeSHA256("owner"),
    created_at: 1, updated_at: 1,
    embed_keys: [
      { hashed_embed_id: computeSHA256("e"), key_type: "master" as const,
        hashed_chat_id: null, encrypted_embed_key: "master-cipher", hashed_user_id: computeSHA256("owner"), created_at: 1 },
      { hashed_embed_id: computeSHA256("e"), key_type: "chat" as const,
        hashed_chat_id: computeSHA256("chat"), encrypted_embed_key: "chat-cipher", hashed_user_id: computeSHA256("owner"), created_at: 1 },
    ],
  };
  const scope = { chatId: "chat", messageId: "message", ownerId: "owner" };
  assert.doesNotThrow(() => assertCompleteEncryptedEmbedBundle([embed], scope));
  assert.throws(() => assertCompleteEncryptedEmbedBundle([embed], { ...scope, messageId: "another-message" }), /belongs to another/);
  assert.throws(() => assertCompleteEncryptedEmbedBundle([{
    ...embed, embed_keys: [{ ...embed.embed_keys[0], hashed_embed_id: "wrong" }, embed.embed_keys[1]],
  }], scope), /incomplete key wrappers/);
  assert.throws(() => assertCompleteEncryptedEmbedBundle([embed, embed], scope), /duplicated/);
  assert.throws(() => assertCompleteEncryptedEmbedBundle([{ ...embed, embed_keys: embed.embed_keys.slice(0, 1) }], scope), /incomplete/);
  assert.throws(() => assertCompleteEncryptedEmbedBundle([{ ...embed, embed_keys: [
    embed.embed_keys[0], { ...embed.embed_keys[1], hashed_chat_id: "other-chat" },
  ] }], scope), /incomplete key wrappers/);
});
