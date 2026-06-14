#!/usr/bin/env node
/*
 * OpenMates CLI test-account automation.
 *
 * Purpose: bootstrap the local OpenMates CLI from existing E2E test account
 * credentials and optionally create/share real CLI chats for example-chat data.
 * Security: reads secrets from .env/process.env, never prints credentials, and
 * writes only the normal ~/.openmates/session.json consumed by the CLI.
 */

import { spawnSync } from "node:child_process";
import { createHash, createHmac, randomUUID, webcrypto } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync, chmodSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_API_URL = "https://api.dev.openmates.org";
const DEFAULT_WEB_ORIGIN = "https://app.dev.openmates.org";
const PBKDF2_ITERATIONS = 100_000;
const AES_GCM_IV_LENGTH = 12;

function usage() {
  process.stderr.write(`Usage:
  node scripts/openmates_cli_test_account.mjs login [--slot <n>] [--api-url <url>]
  node scripts/openmates_cli_test_account.mjs chat "<prompt>" [--slot <n>] [--api-url <url>] [--expires <seconds>] [--auto-approve-memories]

Environment:
  OPENMATES_TEST_ACCOUNT_EMAIL / PASSWORD / OTP_KEY
  OPENMATES_TEST_ACCOUNT_<slot>_EMAIL / PASSWORD / OTP_KEY
  OPENMATES_TEST_ACCOUNT_SOURCE_SLOT
`);
}

function loadDotenv() {
  const envPath = join(REPO_ROOT, ".env");
  if (!existsSync(envPath)) return;

  const content = readFileSync(envPath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const index = line.indexOf("=");
    const key = line.slice(0, index).trim();
    if (process.env[key] !== undefined) continue;
    let value = line.slice(index + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

function parseArgs(argv) {
  const options = {
    apiUrl: process.env.OPENMATES_API_URL || DEFAULT_API_URL,
    autoApproveMemories: false,
    expires: "604800",
    slot: process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || "2",
  };
  const positional = [];

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") {
      options.apiUrl = argv[++index];
    } else if (arg === "--expires") {
      options.expires = argv[++index];
    } else if (arg === "--slot") {
      options.slot = argv[++index];
    } else if (arg === "--auto-approve-memories") {
      options.autoApproveMemories = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      positional.push(arg);
    }
  }

  return { command: positional[0], args: positional.slice(1), options };
}

function getTestAccount(slot) {
  const suffix = slot ? `_${slot}` : "";
  const email = process.env[`OPENMATES_TEST_ACCOUNT${suffix}_EMAIL`] || process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
  const password = process.env[`OPENMATES_TEST_ACCOUNT${suffix}_PASSWORD`] || process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
  const otpKey = process.env[`OPENMATES_TEST_ACCOUNT${suffix}_OTP_KEY`] || process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

  if (!email || !password) {
    throw new Error(`Missing OPENMATES_TEST_ACCOUNT${suffix}_EMAIL/PASSWORD credentials`);
  }

  return { email, password, otpKey };
}

function bytesToBase64(bytes) {
  return Buffer.from(bytes).toString("base64");
}

function base64ToBytes(value) {
  return new Uint8Array(Buffer.from(value, "base64"));
}

function toArrayBuffer(bytes) {
  const output = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(output).set(bytes);
  return output;
}

async function sha256Base64(input) {
  const bytes = typeof input === "string" ? new TextEncoder().encode(input) : input;
  const hash = await webcrypto.subtle.digest("SHA-256", toArrayBuffer(bytes));
  return bytesToBase64(new Uint8Array(hash));
}

async function hashKey(key, saltBytes) {
  const keyBytes = new TextEncoder().encode(key);
  const combined = new Uint8Array(keyBytes.length + saltBytes.length);
  combined.set(keyBytes);
  combined.set(saltBytes, keyBytes.length);
  return sha256Base64(combined);
}

async function deriveEmailEncryptionKeyB64(email, userEmailSaltB64) {
  const emailBytes = new TextEncoder().encode(email);
  const saltBytes = base64ToBytes(userEmailSaltB64);
  const combined = new Uint8Array(emailBytes.length + saltBytes.length);
  combined.set(emailBytes);
  combined.set(saltBytes, emailBytes.length);
  return sha256Base64(combined);
}

async function derivePasswordWrappingKey(password, saltB64) {
  const passwordBytes = new TextEncoder().encode(password);
  const keyMaterial = await webcrypto.subtle.importKey(
    "raw",
    toArrayBuffer(passwordBytes),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return webcrypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: toArrayBuffer(base64ToBytes(saltB64)),
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
}

async function decryptWrappedMasterKeyB64({ encryptedKeyB64, keyIvB64, password, saltB64 }) {
  if (!encryptedKeyB64 || !keyIvB64 || !saltB64) {
    throw new Error("Login response did not include password-encrypted master key fields");
  }

  const wrappingKey = await derivePasswordWrappingKey(password, saltB64);
  const decrypted = await webcrypto.subtle.decrypt(
    { name: "AES-GCM", iv: toArrayBuffer(base64ToBytes(keyIvB64)) },
    wrappingKey,
    toArrayBuffer(base64ToBytes(encryptedKeyB64)),
  );
  return bytesToBase64(new Uint8Array(decrypted));
}

function decodeBase32(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = secret.replace(/\s+/g, "").replace(/=+$/, "").toUpperCase();
  let bits = "";
  for (const char of clean) {
    const value = alphabet.indexOf(char);
    if (value === -1) continue;
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

function generateTotp(secret, windowOffset = 0) {
  const key = decodeBase32(secret);
  const counter = Math.floor(Date.now() / 1000 / 30) + windowOffset;
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", key).update(counterBuffer).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

function splitSetCookieHeader(header) {
  if (!header) return [];
  return header.split(/,(?=\s*[^;,\s]+=)/g).map((value) => value.trim()).filter(Boolean);
}

function captureCookies(headers) {
  const cookies = {};
  const getSetCookie = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [];
  const setCookieHeaders = getSetCookie.length > 0 ? getSetCookie : splitSetCookieHeader(headers.get("set-cookie"));
  for (const header of setCookieHeaders) {
    const [pair] = header.split(";");
    const index = pair.indexOf("=");
    if (index <= 0) continue;
    cookies[pair.slice(0, index)] = pair.slice(index + 1);
  }
  return cookies;
}

async function apiPost(apiUrl, path, body, cookies = {}) {
  const cookieHeader = Object.entries(cookies).map(([key, value]) => `${key}=${value}`).join("; ");
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "Origin": DEFAULT_WEB_ORIGIN,
      ...(cookieHeader ? { Cookie: cookieHeader } : {}),
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  return { response, data, cookies: captureCookies(response.headers) };
}

function writeCliSession(session) {
  const dir = join(homedir(), ".openmates");
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  chmodSync(dir, 0o700);
  const filePath = join(dir, "session.json");
  const onDisk = {
    apiUrl: session.apiUrl,
    sessionId: session.sessionId,
    wsToken: session.wsToken,
    cookies: session.cookies,
    masterKeyExportedB64: session.masterKeyExportedB64,
    masterKeyStorage: "plaintext",
    emailEncryptionKeyB64: session.emailEncryptionKeyB64,
    emailEncryptionKeyStorage: "plaintext",
    hashedEmail: session.hashedEmail,
    userEmailSalt: session.userEmailSalt,
    createdAt: session.createdAt,
    authorizerDeviceName: "test-account-script",
    autoLogoutMinutes: null,
  };
  writeFileSync(filePath, `${JSON.stringify(onDisk, null, 2)}\n`, { mode: 0o600 });
  chmodSync(filePath, 0o600);
}

async function login(options) {
  const account = getTestAccount(options.slot);
  const hashedEmail = await sha256Base64(account.email);

  const lookup = await apiPost(options.apiUrl, "/v1/auth/lookup", {
    hashed_email: hashedEmail,
    stay_logged_in: true,
  });
  if (!lookup.response.ok || !lookup.data.user_email_salt) {
    throw new Error(`Lookup failed with HTTP ${lookup.response.status}`);
  }

  const userEmailSalt = lookup.data.user_email_salt;
  const lookupHash = await hashKey(account.password, base64ToBytes(userEmailSalt));
  const emailEncryptionKeyB64 = await deriveEmailEncryptionKeyB64(account.email, userEmailSalt);
  const sessionId = randomUUID();
  const loginBody = {
    hashed_email: hashedEmail,
    lookup_hash: lookupHash,
    email_encryption_key: emailEncryptionKeyB64,
    session_id: sessionId,
    stay_logged_in: true,
  };

  let loginResult;
  const otpOffsets = account.otpKey ? [0, -1, 1] : [null];
  for (const offset of otpOffsets) {
    const attemptBody = { ...loginBody };
    if (typeof offset === "number" && account.otpKey) {
      attemptBody.tfa_code = generateTotp(account.otpKey, offset);
      attemptBody.code_type = "otp";
    }
    loginResult = await apiPost(options.apiUrl, "/v1/auth/login", attemptBody);
    if (loginResult.response.ok && loginResult.data?.success && !loginResult.data?.tfa_required) {
      break;
    }
    if (!account.otpKey || loginResult.data?.message !== "login.code_wrong") {
      break;
    }
  }

  if (!loginResult.response.ok || !loginResult.data?.success || loginResult.data?.tfa_required) {
    throw new Error(`Login failed with HTTP ${loginResult.response.status}: ${loginResult.data?.message || "unknown error"}`);
  }

  const user = loginResult.data.user || {};
  const masterKeyExportedB64 = await decryptWrappedMasterKeyB64({
    encryptedKeyB64: user.encrypted_key,
    keyIvB64: user.key_iv,
    password: account.password,
    saltB64: user.salt,
  });

  writeCliSession({
    apiUrl: options.apiUrl,
    sessionId,
    wsToken: loginResult.data.ws_token || null,
    cookies: loginResult.cookies,
    masterKeyExportedB64,
    emailEncryptionKeyB64,
    hashedEmail,
    userEmailSalt,
    createdAt: Date.now(),
  });

  return {
    success: true,
    apiUrl: options.apiUrl,
    username: user.username || null,
    userIdHash: user.id ? createHash("sha256").update(user.id).digest("hex").slice(0, 12) : null,
    cookies: Object.keys(loginResult.cookies).sort(),
  };
}

function runCli(args, apiUrl) {
  const cliPath = join(REPO_ROOT, "frontend/packages/openmates-cli/dist/cli.js");
  const result = spawnSync(process.execPath, [cliPath, "--api-url", apiUrl, ...args], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `CLI exited with ${result.status}`);
  }
  return result.stdout.trim();
}

function parseCliJson(output) {
  const start = output.indexOf("{");
  if (start === -1) throw new Error(`CLI did not return JSON: ${output.slice(0, 120)}`);
  return JSON.parse(output.slice(start));
}

async function createChat(prompt, options) {
  await login(options);
  const chatArgs = ["chats", "new", prompt, "--json"];
  if (options.autoApproveMemories) chatArgs.push("--auto-approve-memories");
  const chatOutput = runCli(chatArgs, options.apiUrl);
  const chat = parseCliJson(chatOutput);
  const chatId = chat.chat_id || chat.chatId || chat.id;
  if (!chatId) {
    throw new Error("CLI chat creation did not return a chat id");
  }
  const shareOutput = runCli(["chats", "share", chatId, "--expires", options.expires, "--json"], options.apiUrl);
  const share = parseCliJson(shareOutput);
  return {
    success: true,
    chatId,
    title: chat.title || null,
    shareUrl: share.url || share.share_url || share.shareUrl || null,
  };
}

async function main() {
  loadDotenv();
  const { command, args, options } = parseArgs(process.argv.slice(2));
  if (options.help || !command) {
    usage();
    process.exit(options.help ? 0 : 1);
  }

  if (command === "login") {
    const result = await login(options);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  if (command === "chat") {
    const prompt = args.join(" ").trim();
    if (!prompt) throw new Error("Missing chat prompt");
    const result = await createChat(prompt, options);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  usage();
  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
