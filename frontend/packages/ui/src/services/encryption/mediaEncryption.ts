/**
 * Shared media encryption reader boundary.
 *
 * R1 readers dispatch legacy external-nonce and explicit nonce-prefixed v2
 * payloads here so unknown formats fail closed consistently across embeds.
 */

export const MEDIA_ENCRYPTION_V2 = "aes-gcm-nonce-prefixed-v1";

export interface MediaEncryptionVariant {
  [key: string]: unknown;
  aes_nonce?: string | null;
  encryption?: string | null;
}

export interface DecryptMediaPayloadInput {
  encryptedData: ArrayBuffer;
  aesKeyBase64: string;
  variant: MediaEncryptionVariant;
  legacyNonceBase64: string | null;
}

export async function decryptMediaPayload(
  _input: DecryptMediaPayloadInput,
): Promise<ArrayBuffer> {
  throw new Error("Media encryption reader is not implemented");
}
