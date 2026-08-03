/**
 * Shared media encryption reader boundary.
 *
 * R1 readers dispatch legacy external-nonce and explicit nonce-prefixed v2
 * payloads here so unknown formats fail closed consistently across embeds.
 */

export const MEDIA_ENCRYPTION_V2 = "aes-gcm-nonce-prefixed-v1";

const AES_KEY_BYTES = 32;
const AES_GCM_NONCE_BYTES = 12;
const AES_GCM_TAG_BYTES = 16;

interface MediaEncryptionMetadata {
  aes_nonce?: string | null;
  encryption?: string | null;
}

export interface DecryptMediaPayloadInput {
  encryptedData: ArrayBuffer;
  aesKeyBase64: string;
  variant: unknown;
  legacyNonceBase64: string | null;
}

export class MediaEncryptionError extends Error {
  constructor(
    message: string,
    readonly stage: "importKey" | "decrypt" | "metadata",
    readonly originalCause?: unknown,
  ) {
    super(message);
    this.name = "MediaEncryptionError";
  }
}

export function hasMediaEncryptionMetadata(
  variant: unknown,
  legacyNonceBase64: string | null | undefined,
): boolean {
  const metadata = readMediaEncryptionMetadata(variant);
  return (
    metadata.encryption === MEDIA_ENCRYPTION_V2 ||
    Boolean(metadata.aes_nonce) ||
    legacyNonceBase64 !== undefined && legacyNonceBase64 !== null
  );
}

export async function decryptMediaPayload(
  input: DecryptMediaPayloadInput,
): Promise<ArrayBuffer> {
  const keyBytes = decodeBase64(input.aesKeyBase64, "media AES key");
  if (keyBytes.byteLength !== AES_KEY_BYTES) {
    throw new MediaEncryptionError("Media AES key must be 32 bytes", "metadata");
  }

  const metadata = readMediaEncryptionMetadata(input.variant);
  const marker = metadata.encryption;
  let nonce: ArrayBuffer;
  let ciphertext: ArrayBuffer;
  if (marker === MEDIA_ENCRYPTION_V2) {
    if (input.encryptedData.byteLength < AES_GCM_NONCE_BYTES + AES_GCM_TAG_BYTES) {
      throw new MediaEncryptionError("Nonce-prefixed media ciphertext is too short", "metadata");
    }
    nonce = input.encryptedData.slice(0, AES_GCM_NONCE_BYTES);
    ciphertext = input.encryptedData.slice(AES_GCM_NONCE_BYTES);
  } else if (marker === undefined || marker === null || marker === "") {
    const externalNonce = metadata.aes_nonce || input.legacyNonceBase64;
    if (externalNonce) {
      nonce = decodeBase64(externalNonce, "legacy media nonce");
      ciphertext = input.encryptedData;
    } else if (input.legacyNonceBase64 === "") {
      // Existing PDF and screenshot artifacts predate the explicit media marker.
      if (input.encryptedData.byteLength < AES_GCM_NONCE_BYTES + AES_GCM_TAG_BYTES) {
        throw new MediaEncryptionError("Legacy nonce-prefixed ciphertext is too short", "metadata");
      }
      nonce = input.encryptedData.slice(0, AES_GCM_NONCE_BYTES);
      ciphertext = input.encryptedData.slice(AES_GCM_NONCE_BYTES);
    } else {
      throw new MediaEncryptionError("Legacy media nonce is missing", "metadata");
    }
  } else {
    throw new MediaEncryptionError(
      `Unsupported media encryption marker: ${marker}`,
      "metadata",
    );
  }
  if (nonce.byteLength !== AES_GCM_NONCE_BYTES) {
    throw new MediaEncryptionError("Media nonce must be 12 bytes", "metadata");
  }

  let cryptoKey: CryptoKey;
  try {
    cryptoKey = await crypto.subtle.importKey(
      "raw",
      keyBytes,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
  } catch (error) {
    throw new MediaEncryptionError("AES-GCM key import failed", "importKey", error);
  }
  try {
    return await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, cryptoKey, ciphertext);
  } catch (error) {
    throw new MediaEncryptionError("AES-GCM media decryption failed", "decrypt", error);
  }
}

function readMediaEncryptionMetadata(variant: unknown): MediaEncryptionMetadata {
  return typeof variant === "object" && variant !== null
    ? variant as MediaEncryptionMetadata
    : {};
}

function decodeBase64(value: string, label: string): ArrayBuffer {
  try {
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(normalized), (character) => character.charCodeAt(0));
    const buffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buffer).set(bytes);
    return buffer;
  } catch (error) {
    throw new MediaEncryptionError(`${label} is invalid base64`, "metadata", error);
  }
}
