/*
 * OpenMates CLI secure master key storage.
 *
 * Purpose: protect the master encryption key using OS-native credential stores
 * instead of storing it as plaintext in session.json.
 * Architecture: three-tier fallback — OS keychain → encrypted file → plaintext.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: macOS Keychain / Linux secret-tool for tier 1, AES-256-GCM with
 *           machine-derived key for tier 2.
 * Tests: frontend/packages/openmates-cli/tests/keychain.test.ts
 */

import { execFileSync } from "node:child_process";
import {
  webcrypto,
  createHash,
  pbkdf2Sync,
  createCipheriv,
  createDecipheriv,
} from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { homedir, platform, userInfo } from "node:os";
import { join } from "node:path";

const cryptoApi = globalThis.crypto ?? webcrypto;

const KEYCHAIN_SERVICE = "OpenMates";
const AES_GCM_IV_LENGTH = 12;
const PBKDF2_ITERATIONS = 100_000;
const KEYCHAIN_TIMEOUT_MS = 5_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MasterKeyStorageType = "keychain" | "encrypted" | "plaintext";

export interface MasterKeyStorageResult {
  type: MasterKeyStorageType;
  /** Base64-encoded encrypted data (only for type "encrypted") */
  encryptedData?: string;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Store the master key using the best available mechanism.
 * Tries OS keychain first, then encrypted file key, then plaintext fallback.
 */
export function storeMasterKey(
  key: string,
  hashedEmail: string,
): MasterKeyStorageResult {
  // Tier 1: OS keychain
  try {
    keychainStore(key, hashedEmail);
    return { type: "keychain" };
  } catch {
    // Fall through to tier 2
  }

  // Tier 2: Machine-key encryption
  try {
    const encryptedData = encryptWithMachineKey(key);
    return { type: "encrypted", encryptedData };
  } catch {
    // Fall through to tier 3
  }

  // Tier 3: Plaintext (current behavior)
  return { type: "plaintext" };
}

/**
 * Retrieve the master key from the storage tier it was saved to.
 */
export function retrieveMasterKey(
  type: MasterKeyStorageType,
  hashedEmail: string,
  encryptedData?: string,
): string | null {
  switch (type) {
    case "keychain":
      try {
        return keychainRetrieve(hashedEmail);
      } catch {
        return null;
      }

    case "encrypted":
      if (!encryptedData) return null;
      try {
        return decryptWithMachineKey(encryptedData);
      } catch {
        return null;
      }

    case "plaintext":
      // Plaintext key is stored directly in session JSON — caller handles it
      return null;

    default:
      return null;
  }
}

/**
 * Delete the master key from whatever storage tier it was saved to.
 */
export function deleteMasterKey(
  type: MasterKeyStorageType,
  hashedEmail: string,
): void {
  switch (type) {
    case "keychain":
      try {
        keychainDelete(hashedEmail);
      } catch {
        // Best effort — keychain entry may already be gone
      }
      break;
    case "encrypted":
    case "plaintext":
      // No external cleanup needed — caller removes the session file
      break;
  }
}

// ---------------------------------------------------------------------------
// Tier 1: OS Keychain (macOS security / Linux secret-tool)
// ---------------------------------------------------------------------------

function keychainStore(key: string, account: string): void {
  const os = platform();

  if (os === "darwin") {
    // Delete existing entry first (ignore errors if not found)
    try {
      execFileSync("security", [
        "delete-generic-password",
        "-s", KEYCHAIN_SERVICE,
        "-a", account,
      ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe" });
    } catch {
      // Entry didn't exist — that's fine
    }

    execFileSync("security", [
      "add-generic-password",
      "-s", KEYCHAIN_SERVICE,
      "-a", account,
      "-w", key,
      "-U",
    ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe" });
    return;
  }

  if (os === "linux") {
    execFileSync("secret-tool", [
      "store",
      "--label", KEYCHAIN_SERVICE,
      "service", KEYCHAIN_SERVICE,
      "account", account,
    ], {
      timeout: KEYCHAIN_TIMEOUT_MS,
      stdio: ["pipe", "pipe", "pipe"],
      input: key,
    });
    return;
  }

  throw new Error(`Keychain not supported on ${os}`);
}

function keychainRetrieve(account: string): string | null {
  const os = platform();

  if (os === "darwin") {
    const result = execFileSync("security", [
      "find-generic-password",
      "-s", KEYCHAIN_SERVICE,
      "-a", account,
      "-w",
    ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe", encoding: "utf-8" });
    const value = result.trim();
    return value || null;
  }

  if (os === "linux") {
    const result = execFileSync("secret-tool", [
      "lookup",
      "service", KEYCHAIN_SERVICE,
      "account", account,
    ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe", encoding: "utf-8" });
    const value = result.trim();
    return value || null;
  }

  throw new Error(`Keychain not supported on ${os}`);
}

function keychainDelete(account: string): void {
  const os = platform();

  if (os === "darwin") {
    execFileSync("security", [
      "delete-generic-password",
      "-s", KEYCHAIN_SERVICE,
      "-a", account,
    ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe" });
    return;
  }

  if (os === "linux") {
    execFileSync("secret-tool", [
      "clear",
      "service", KEYCHAIN_SERVICE,
      "account", account,
    ], { timeout: KEYCHAIN_TIMEOUT_MS, stdio: "pipe" });
    return;
  }

  throw new Error(`Keychain not supported on ${os}`);
}

// ---------------------------------------------------------------------------
// Tier 2: Machine-key encrypted file storage
// ---------------------------------------------------------------------------

/**
 * Derive a deterministic encryption key from machine-specific entropy.
 * Uses PBKDF2(machine-id + username) to produce an AES-256 key.
 */
function deriveMachineKey(): Buffer {
  const entropy = getMachineEntropy();
  const username = userInfo().username;
  const salt = `OpenMates-machine-key-${username}`;

  return pbkdf2Sync(entropy, salt, PBKDF2_ITERATIONS, 32, "sha256");
}

/**
 * Get machine-specific entropy.
 * macOS: IOPlatformUUID via ioreg
 * Linux: /etc/machine-id
 * Fallback: hostname + homedir hash (weak but better than nothing)
 */
function getMachineEntropy(): string {
  const os = platform();

  if (os === "darwin") {
    try {
      const output = execFileSync("ioreg", [
        "-rd1", "-c", "IOPlatformExpertDevice",
      ], { timeout: KEYCHAIN_TIMEOUT_MS, encoding: "utf-8", stdio: "pipe" });
      const match = output.match(/"IOPlatformUUID"\s*=\s*"([^"]+)"/);
      if (match?.[1]) return match[1];
    } catch {
      // Fall through to fallback
    }
  }

  if (os === "linux") {
    try {
      const machineIdPath = "/etc/machine-id";
      if (existsSync(machineIdPath)) {
        const id = readFileSync(machineIdPath, "utf-8").trim();
        if (id) return id;
      }
    } catch {
      // Fall through to fallback
    }
  }

  // Fallback: hash of hostname + homedir (weak but deterministic)
  return createHash("sha256")
    .update(`${homedir()}-${userInfo().username}-${os}`)
    .digest("hex");
}

/**
 * Encrypt the master key with machine-derived key using AES-256-GCM.
 * Returns base64-encoded (IV + ciphertext + authTag).
 */
function encryptWithMachineKey(plaintext: string): string {
  const key = deriveMachineKey();
  const iv = Buffer.from(cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH)));

  const cipher = createCipheriv("aes-256-gcm", key, iv);

  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf-8"),
    cipher.final(),
  ]);
  const authTag = cipher.getAuthTag();

  // Format: IV (12 bytes) + ciphertext + authTag (16 bytes)
  const combined = Buffer.concat([iv, encrypted, authTag]);
  return combined.toString("base64");
}

/**
 * Decrypt machine-key encrypted data.
 * Expects base64-encoded (IV + ciphertext + authTag).
 */
function decryptWithMachineKey(encryptedB64: string): string {
  const key = deriveMachineKey();
  const combined = Buffer.from(encryptedB64, "base64");

  if (combined.length <= AES_GCM_IV_LENGTH + 16) {
    throw new Error("Encrypted data too short");
  }

  const iv = combined.subarray(0, AES_GCM_IV_LENGTH);
  const authTag = combined.subarray(combined.length - 16);
  const ciphertext = combined.subarray(AES_GCM_IV_LENGTH, combined.length - 16);

  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(authTag);

  const decrypted = Buffer.concat([
    decipher.update(ciphertext),
    decipher.final(),
  ]);
  return decrypted.toString("utf-8");
}
