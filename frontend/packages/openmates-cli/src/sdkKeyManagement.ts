/**
 * API-key SDK key-management primitives over the shared Rust core (portable WASM).
 *
 * Mirrors Rust `openmates_sdk::crypto` and Python `openmates.key_management`:
 * 32-byte keys, canonical `OM` + FNV-1a32 writes, authenticated legacy reads.
 * Pure functions: no network, CLI state or environment. Errors are
 * `SessionClientError` (`invalid_argument`, `crypto`, `native_binding_unavailable`)
 * and never carry key material. Vectors: tests/sdk-conformance/fixtures/sdk-key-management.json.
 */
import { callSdkWasm } from "./sdkWasmCall.js";

const bytes = (value: Uint8Array): number[] => Array.from(value);

/** Stateless key helpers; every operation runs in the shared Rust core. */
export const keyManagement = Object.freeze({
  /** 32 fresh random bytes from the platform CSPRNG. */
  randomKey(): Uint8Array {
    return Uint8Array.from(callSdkWasm<{ key: number[] }>("keyManagement", { operation: "random_key" }).key);
  },
  /** Standard base64 of a 32-byte key. */
  encodeKey(key: Uint8Array): string {
    return callSdkWasm<{ value: string }>("keyManagement", { operation: "encode_key", key: bytes(key) }).value;
  },
  /** Standard or unpadded URL-safe base64 of exactly 32 bytes. */
  decodeKey(value: string): Uint8Array {
    return Uint8Array.from(callSdkWasm<{ key: number[] }>("keyManagement", { operation: "decode_key", value }).key);
  },
  /** Browser `OM` header fingerprint (FNV-1a32, big-endian). */
  keyFingerprint(key: Uint8Array): Uint8Array {
    return Uint8Array.from(callSdkWasm<{ fingerprint: number[] }>("keyManagement", { operation: "key_fingerprint", key: bytes(key) }).fingerprint);
  },
  /** Base64 SHA-256 of the email address. */
  hashEmail(email: string): string {
    return callSdkWasm<{ hash: string }>("keyManagement", { operation: "hash_email", email }).hash;
  },
  /** Base64 SHA-256 of password bytes followed by the salt. */
  hashKey(password: string, salt: Uint8Array): string {
    return callSdkWasm<{ hash: string }>("keyManagement", { operation: "hash_key", password, salt: bytes(salt) }).hash;
  },
  /** AES-256-GCM `OM`-framed combined ciphertext (standard base64). */
  encryptCombined(text: string, key: Uint8Array): string {
    return callSdkWasm<{ ciphertext: string }>("keyManagement", { operation: "encrypt_combined", text, key: bytes(key) }).ciphertext;
  },
  /** Decrypt `OM`-framed or legacy IV-prefixed combined ciphertext; `crypto` on failure. */
  decryptCombined(ciphertext: string, key: Uint8Array): string {
    return callSdkWasm<{ text: string }>("keyManagement", { operation: "decrypt_combined", ciphertext, key: bytes(key) }).text;
  },
});
