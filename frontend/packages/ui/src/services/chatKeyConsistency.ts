// frontend/packages/ui/src/services/chatKeyConsistency.ts
// Small key-consistency helpers shared by sync and send paths.
// These helpers prevent a normal encrypted payload from pairing content
// encrypted with one raw chat key with an encrypted_chat_key for another.
// Candidate-key fallback remains a recovery layer, not normal control flow.

export function chatKeysEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  return a.every((byte, index) => byte === b[index]);
}

export async function encryptedChatKeyMatchesRawKey(
  encryptedChatKey: string,
  rawChatKey: Uint8Array,
  decryptEncryptedChatKey: (encryptedChatKey: string) => Promise<Uint8Array | null>,
): Promise<boolean | null> {
  const decryptedKey = await decryptEncryptedChatKey(encryptedChatKey);
  if (!decryptedKey) return null;
  return chatKeysEqual(rawChatKey, decryptedKey);
}
