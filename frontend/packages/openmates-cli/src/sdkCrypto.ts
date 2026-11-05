/** SDK-owned AES boundary. Stateless shared primitives never launch the CLI. */
import {
  encryptBytesWithAesGcm as encryptBytes,
  encryptWithAesGcmCombined as encryptText,
} from "./crypto.js";
import { webcrypto } from "node:crypto";

const cryptoApi = globalThis.crypto ?? webcrypto;
function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.length);
  copy.set(bytes);
  return copy.buffer;
}

export function sdkKeyFingerprint(key: Uint8Array): Uint8Array {
  let hash = 0x811c9dc5;
  for (const byte of key) hash = Math.imul(hash ^ byte, 0x01000193);
  return Uint8Array.of(hash >>> 24, hash >>> 16, hash >>> 8, hash);
}

function withHeader(ciphertext: string, key: Uint8Array): string {
  if (key.length !== 32) throw new Error("Invalid SDK encryption key");
  return Buffer.concat([Buffer.from("OM"), sdkKeyFingerprint(key), Buffer.from(ciphertext, "base64")]).toString("base64");
}

export async function encryptBytesWithAesGcm(data: Uint8Array, key: Uint8Array): Promise<string> {
  return withHeader(await encryptBytes(data, key), key);
}

export async function encryptWithAesGcmCombined(text: string, key: Uint8Array, associatedData?: string): Promise<string> {
  return withHeader(await encryptText(text, key, associatedData), key);
}

async function openCombined(ciphertext: string, key: Uint8Array, associatedData?: string): Promise<Uint8Array | null> {
  try {
    const bytes = Buffer.from(ciphertext, "base64");
    if (key.length !== 32 || bytes.length < 28) return null;
    const rawKey = toArrayBuffer(key);
    let imported: CryptoKey;
    try { imported = await cryptoApi.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, false, ["decrypt"]); }
    finally { new Uint8Array(rawKey).fill(0); }
    const open = async (offset: number): Promise<Uint8Array> => new Uint8Array(await cryptoApi.subtle.decrypt({ name: "AES-GCM", iv: toArrayBuffer(bytes.subarray(offset, offset + 12)), ...(associatedData ? { additionalData: toArrayBuffer(new TextEncoder().encode(associatedData)) } : {}) }, imported, toArrayBuffer(bytes.subarray(offset + 12))));
    const fingerprint = sdkKeyFingerprint(key);
    const marker = bytes[2] === 1 && bytes[3] === 0 && bytes[4] === 0 && bytes[5] === 0;
    if (bytes.length >= 34 && bytes[0] === 0x4f && bytes[1] === 0x4d && (marker || fingerprint.every((byte, index) => bytes[index + 2] === byte))) {
      try { return await open(6); } catch { /* The apparent header may be a legacy IV prefix. */ }
    }
    // Authenticate the complete legacy buffer; OM bytes never prove a format.
    return await open(0);
  } catch { return null; }
}
export async function decryptBytesWithAesGcm(ciphertext: string, key: Uint8Array): Promise<Uint8Array | null> {
  return openCombined(ciphertext, key);
}
export async function decryptWithAesGcmCombined(ciphertext: string, key: Uint8Array, associatedData?: string): Promise<string | null> {
  const plaintext = await openCombined(ciphertext, key, associatedData);
  return plaintext === null ? null : new TextDecoder().decode(plaintext);
}
