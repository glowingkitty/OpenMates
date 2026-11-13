// Flag-ON facades: the original TS crypto modules delegate here only when
// `rustWebCrypto()` returns a client (VITE_OPENMATES_RUST_CORE builds). Each
// function keeps the exact return/throw/logging contract of the TS function it
// replaces, so callers cannot tell which implementation ran. The formats
// themselves (chat OM/legacy, master Formats C/D, share/embed-share blobs,
// short URLs, media layouts, chat-key write guard) live in shared Rust and are
// vector-checked against the TS implementation (packages/openmates-rust/tests/
// web_crypto_corpus.rs).
import type { ChatContentResult, ShareKeyResult, WebCryptoClient } from "./webCryptoClient";

const CHAT_KEY_BYTES = 32;

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** True when the Rust chat-content path accepts this key (AES-256 chat keys). */
export function rustHandlesChatKey(chatKey: Uint8Array): boolean {
  return chatKey.length === CHAT_KEY_BYTES;
}

export function rustEncryptWithChatKey(client: WebCryptoClient, data: string, chatKey: Uint8Array): Promise<string> {
  return client.call<string>("encryptChatContent", new Uint8Array(chatKey), data);
}

/**
 * `decryptWithChatKey` contract: text, or null with the TS diagnostics. `start`
 * carries a first attempt already made by a list decrypt; without one the crypto
 * unit decrypts.
 */
export async function rustDecryptWithChatKey(
  client: WebCryptoClient,
  encrypted: string,
  chatKey: Uint8Array,
  context?: { chatId?: string; fieldName?: string },
  start?: { first: ChatContentResult },
): Promise<string | null> {
  const chatId = context?.chatId ?? "unknown";
  const fieldName = context?.fieldName ?? "unknown";
  let result: ChatContentResult;
  if (start !== undefined) {
    result = start.first;
  } else {
    try {
      result = await client.call<ChatContentResult>("decryptChatContent", new Uint8Array(chatKey), encrypted);
    } catch (error) {
      console.error(`[CryptoService] Chat decryption failed: ${describe(error)}. chat_id=${chatId} field=${fieldName}.`);
      return null;
    }
  }
  if (typeof result === "string") return result;
  if (result === null) {
    client.recordFailure("decryptChatContent");
    console.error(
      `[CryptoService] Chat decryption failed: OperationError. chat_id=${chatId} field=${fieldName}. ` +
        `Encrypted data length: ${encrypted.length} chars. Chat key length: ${chatKey.length} bytes. ` +
        `This usually indicates: wrong chat key, malformed encrypted content, or content encrypted with different key.`,
    );
    return null;
  }
  client.stats.fingerprintMismatches += 1;
  const storedHex = result.fingerprintMismatch;
  if (context?.chatId) {
    const { chatKeyManager } = await import("../../encryption/ChatKeyManager");
    const candidate = await chatKeyManager.findCandidateKeyByFingerprint(context.chatId, storedHex);
    if (candidate) {
      console.warn(
        `[CryptoService] Recovering chat key from candidate after fingerprint mismatch: ` +
          `data fp=${storedHex}, chat_id=${chatId} field=${fieldName}`,
      );
      let recovered: ChatContentResult;
      try {
        recovered = await client.call<ChatContentResult>("decryptChatContent", new Uint8Array(candidate.key), encrypted);
      } catch (error) {
        console.error(`[CryptoService] Chat decryption failed: ${describe(error)}. chat_id=${chatId} field=${fieldName}.`);
        return null;
      }
      if (typeof recovered === "string") {
        chatKeyManager.promoteCandidateKey(context.chatId, candidate, "fingerprint_mismatch_recovery");
        return recovered;
      }
      client.recordFailure("decryptChatContent");
      console.error(`[CryptoService] Chat decryption failed with recovered candidate key. chat_id=${chatId} field=${fieldName}.`);
      return null;
    }
  }
  client.recordFailure("decryptChatContent");
  console.error(
    `[CryptoService] Key fingerprint mismatch: data encrypted with key fp=${storedHex}. ` +
      `chat_id=${chatId} field=${fieldName}. ` +
      `This means the data was encrypted with a DIFFERENT key than the one currently loaded.`,
  );
  return null;
}

// ── Master key (Formats C/D); the CryptoKey stays non-extractable ──

export async function rustEncryptWithMasterKey(
  client: WebCryptoClient,
  masterKey: CryptoKey,
  plaintext: Uint8Array,
  failureLog: string,
): Promise<string | null> {
  try {
    return await client.call<string>("masterEncrypt", masterKey, plaintext);
  } catch (error) {
    console.error(failureLog, error);
    return null;
  }
}

export async function rustDecryptWithMasterKey(
  client: WebCryptoClient,
  masterKey: CryptoKey,
  encrypted: string,
  failureLog: string,
): Promise<Uint8Array | null> {
  try {
    return await client.call<Uint8Array>("masterDecrypt", masterKey, encrypted);
  } catch (error) {
    // call() counts its own failures. Same debug level as TS: expected for stale/hidden-chat data.
    console.debug(failureLog, error);
    return null;
  }
}

// ── Share links (chat and embed) ──

export function rustGenerateShareKeyBlob(
  client: WebCryptoClient,
  kind: "chat" | "embed",
  id: string,
  keyValue: Uint8Array,
  durationSeconds: number,
  password: string | undefined,
): Promise<string> {
  const generatedAt = Math.floor(Date.now() / 1000);
  return client.call<string>("generateShareKeyBlob", kind, id, keyValue, durationSeconds, password ?? null, generatedAt);
}

export async function rustDecryptShareKeyBlob(
  client: WebCryptoClient,
  kind: "chat" | "embed",
  id: string,
  encryptedBlob: string,
  serverTime: number,
  password: string | undefined,
): Promise<ShareKeyResult> {
  try {
    const result = await client.call<ShareKeyResult>("decryptShareKeyBlob", kind, id, encryptedBlob, serverTime, password ?? null);
    if (!result.success) client.recordFailure("decryptShareKeyBlob");
    return result;
  } catch (error) {
    console.error(`[ShareEncryption] Error decrypting ${kind} share key blob: id=${id}`, error);
    return { success: false, error: "decryption_failed" };
  }
}

export function rustEncryptShareUrl(client: WebCryptoClient, fullUrl: string, token: string, shortKey: string): Promise<string> {
  return client.call<string>("encryptShareUrl", fullUrl, token, shortKey);
}

export function rustDecryptShareUrl(client: WebCryptoClient, encryptedUrl: string, token: string, shortKey: string): Promise<string> {
  return client.call<string>("decryptShareUrl", encryptedUrl, token, shortKey);
}

// ── Media ──

export type MediaStage = "importKey" | "decrypt" | "metadata";

export async function rustDecryptMedia(
  client: WebCryptoClient,
  input: { encryptedData: ArrayBuffer; aesKeyBase64: string; encryption: unknown; aesNonce: unknown; legacyNonceBase64: string | null },
  fail: (message: string, stage: MediaStage) => Error,
): Promise<ArrayBuffer> {
  const marker = input.encryption;
  if (marker !== undefined && marker !== null && typeof marker !== "string") {
    throw fail(`Unsupported media encryption marker: ${String(marker)}`, "metadata");
  }
  const aesNonce = typeof input.aesNonce === "string" && input.aesNonce ? input.aesNonce : null;
  let plain: Uint8Array;
  try {
    plain = await client.call<Uint8Array>(
      "decryptMedia", new Uint8Array(input.encryptedData), input.aesKeyBase64, marker ?? null, aesNonce, input.legacyNonceBase64,
    );
  } catch (error) {
    const stage = describe(error);
    if (stage === "metadata" || stage === "importKey" || stage === "decrypt") {
      throw fail(stage === "decrypt" ? "AES-GCM media decryption failed" : `Media ${stage} failed`, stage);
    }
    throw fail(`Media decryption unavailable: ${stage}`, "decrypt");
  }
  return plain.byteOffset === 0 && plain.byteLength === plain.buffer.byteLength
    ? (plain.buffer as ArrayBuffer)
    : plain.slice().buffer;
}

// ── Chat-key write guard ──

export type GuardReason =
  | "candidate_keys_pending" | "fingerprint_mismatch" | "anonymous_key_unwrap_failed" | "anonymous_key_mismatch"
  | "encrypted_key_missing" | "persisted_key_unwrap_failed" | "persisted_key_mismatch";

type GuardStep =
  | { step: "allow" | "allow_unverified" | "unwrap_anonymous" }
  | { step: "unwrap_persisted"; team: boolean }
  | { step: "refuse"; reason: GuardReason; addCandidate: boolean; notice: "none" | "conflicting_keys" | "key_not_validated" };

export interface GuardSnapshot {
  chatExists: boolean;
  candidateKeyCount: number;
  keyFingerprint: string | null;
  isAnonymous: boolean;
  teamScoped: boolean;
  directVisibility: boolean;
  encryptedChatKey: string | null;
}

export interface GuardEffects {
  unwrapAnonymous(): Promise<Uint8Array | null>;
  unwrapPersisted(team: boolean): Promise<Uint8Array | null>;
  refuse(reason: GuardReason, addCandidate: boolean, notice: "none" | "conflicting_keys" | "key_not_validated", error?: unknown): false;
  allowUnverified(): true;
}

/** `ensureChatKeySafeForWrite` decisions in Rust; IO and notices stay in TS. */
export async function rustEnsureChatKeySafeForWrite(
  client: WebCryptoClient,
  snapshot: GuardSnapshot,
  rawChatKey: Uint8Array,
  allowMissingEncryptedChatKey: boolean,
  effects: GuardEffects,
): Promise<boolean> {
  const raw = new Uint8Array(rawChatKey);
  let step = JSON.parse(await client.call<string>("guardBegin", JSON.stringify(snapshot), raw, allowMissingEncryptedChatKey)) as GuardStep;
  let error: unknown;
  if (step.step === "unwrap_anonymous") {
    const unwrapped = await effects.unwrapAnonymous();
    step = JSON.parse(await client.call<string>("guardAfterAnonymous", raw, unwrapped ? new Uint8Array(unwrapped) : null)) as GuardStep;
  } else if (step.step === "unwrap_persisted") {
    let unwrapped: Uint8Array | null = null;
    let threw = false;
    try {
      unwrapped = await effects.unwrapPersisted(step.team);
    } catch (unwrapError) {
      threw = true;
      error = unwrapError;
    }
    step = JSON.parse(
      await client.call<string>("guardAfterPersisted", raw, unwrapped ? new Uint8Array(unwrapped) : null, threw),
    ) as GuardStep;
  }
  switch (step.step) {
    case "allow":
      return true;
    case "allow_unverified":
      return effects.allowUnverified();
    case "refuse":
      return effects.refuse(step.reason, step.addCandidate, step.notice, error);
    default:
      throw new Error(`rust_chat_key_guard_unexpected_step:${step.step}`);
  }
}
