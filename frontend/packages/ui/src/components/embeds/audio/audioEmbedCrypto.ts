/**
 * frontend/packages/ui/src/components/embeds/audio/audioEmbedCrypto.ts
 *
 * Utility for fetching AES-256-GCM encrypted audio blobs from Hetzner S3
 * and decrypting them client-side using the Web Crypto API.
 *
 * Architecture:
 * - The chatfiles S3 bucket is private — blobs require a presigned URL.
 * - Audio content is AES-256-GCM encrypted before upload.
 * - The plaintext AES key and nonce are included in the embed node attrs
 *   (which themselves are encrypted with the chat's master key in IndexedDB).
 * - An in-memory cache prevents re-fetching on component re-mounts.
 *
 * Flow:
 * 1. Request a presigned URL from GET /v1/embeds/presigned-url?s3_key=...
 * 2. Fetch encrypted blob from S3 using the presigned URL
 * 3. Decrypt with AES-256-GCM using the key/nonce from embed attrs
 * 4. Cache the decrypted blob URL in memory
 *
 * Usage:
 *   const blobUrl = await fetchAndDecryptAudio(s3BaseUrl, s3Key, aesKey, aesNonce, mimeType);
 *   // pass blobUrl to <audio src={blobUrl}>
 *   // call releaseAudio(s3Key) on component unmount to free memory
 *
 * Error types thrown by fetchAndDecryptAudio:
 *   AudioFetchError    — S3 HTTP 4xx/5xx (url + status in message)
 *   AudioNetworkError  — Network/CORS failure during fetch() (wraps TypeError)
 *   AudioDecryptError  — crypto.subtle.importKey or .decrypt failed (wraps DOMException)
 */

// ---------------------------------------------------------------------------
// Typed error classes — allow callers to distinguish failure modes precisely.
// DOMException and TypeError both serialize as '{}' in console.error, so we
// wrap them here with descriptive messages and preserve the original cause.
// ---------------------------------------------------------------------------

/** Thrown when the S3 HTTP response is not OK (4xx / 5xx). */
export class AudioFetchError extends Error {
  constructor(url: string, status: number, statusText: string) {
    super(`S3 HTTP ${status} ${statusText} — ${url}`);
    this.name = "AudioFetchError";
  }
}

/**
 * Thrown when the fetch() call itself fails (network error, CORS blocked, etc.).
 * Wraps the underlying TypeError so its message is preserved.
 */
export class AudioNetworkError extends Error {
  constructor(url: string, cause: unknown) {
    const causeMsg = cause instanceof Error ? cause.message : String(cause);
    super(`Network error fetching S3 audio — ${url}: ${causeMsg}`);
    this.name = "AudioNetworkError";
    // Keep the original cause for stack trace inspection
    if (cause instanceof Error) {
      this.stack = `${this.stack}\nCaused by: ${cause.stack}`;
    }
  }
}

/**
 * Thrown when AES-GCM key import or decryption fails.
 * A DOMException("OperationError") means the key/nonce doesn't match the ciphertext.
 * A DOMException("DataError") means the raw key bytes were invalid.
 */
export class AudioDecryptError extends Error {
  constructor(stage: "importKey" | "decrypt", cause: unknown) {
    const domEx =
      cause instanceof DOMException
        ? ` [${cause.name}: ${cause.message}]`
        : cause instanceof Error
          ? ` [${cause.message}]`
          : ` [${String(cause)}]`;
    super(`AES-GCM ${stage} failed${domEx}`);
    this.name = "AudioDecryptError";
    if (cause instanceof Error) {
      this.stack = `${this.stack}\nCaused by: ${cause.stack}`;
    }
  }
}

import { fetchWithPresignedUrl } from "../../../services/presignedUrlService";
import {
  decryptMediaPayload,
  MediaEncryptionError,
} from "../../../services/encryption/mediaEncryption";

// ---------------------------------------------------------------------------

/** In-memory cache: maps S3 key → { blobUrl, refCount, revokeTimer } */
const audioCache = new Map<
  string,
  {
    blobUrl: string;
    bytes: number;
    refCount: number;
    revokeTimer: ReturnType<typeof setTimeout> | null;
  }
>();

type AudioCacheEntry = NonNullable<ReturnType<typeof audioCache.get>>;
const pendingAudio = new Map<string, Promise<AudioCacheEntry>>();
const MAX_CACHED_AUDIO_BYTES = 128 * 1024 * 1024;
let cachedAudioBytes = 0;

function evictUnusedAudio(key: string, entry: AudioCacheEntry): void {
  if (audioCache.get(key) !== entry || entry.refCount > 0) return;
  if (entry.revokeTimer) clearTimeout(entry.revokeTimer);
  URL.revokeObjectURL(entry.blobUrl);
  audioCache.delete(key);
  cachedAudioBytes -= entry.bytes;
}

/** Grace period before revoking an unreferenced blob URL (ms). */
const REVOKE_GRACE_MS = 60_000;

/**
 * Decrement reference count for a cached audio blob URL.
 * Schedules revocation after a grace period when count reaches zero.
 * Call on component unmount.
 */
export function releaseCachedAudio(s3Key: string): void {
  const entry = audioCache.get(s3Key);
  if (!entry) return;
  entry.refCount = Math.max(0, entry.refCount - 1);
  if (entry.refCount === 0 && !entry.revokeTimer) {
    entry.revokeTimer = setTimeout(() => {
      const current = audioCache.get(s3Key);
      if (current && current.refCount === 0) {
        evictUnusedAudio(s3Key, current);
      }
    }, REVOKE_GRACE_MS);
    for (const [key, candidate] of Array.from(audioCache)) {
      if (cachedAudioBytes <= MAX_CACHED_AUDIO_BYTES) break;
      evictUnusedAudio(key, candidate);
    }
  }
}

/**
 * Fetch an AES-256-GCM encrypted audio file from S3 and decrypt it.
 * Results are cached in memory keyed by s3Key.
 *
 * The chatfiles S3 bucket is private — a presigned URL is obtained from the
 * backend API (GET /v1/embeds/presigned-url) before fetching. If the URL
 * expires (HTTP 403), a fresh one is requested and the fetch is retried once.
 *
 * @param s3BaseUrl  - S3 bucket base URL (unused, kept for interface compat — presigned URL is used instead)
 * @param s3Key      - File key in the bucket (e.g. "user_id/timestamp_recording.webm")
 * @param aesKeyBase64 - Base64-encoded plaintext AES-256 key (32 bytes)
 * @param nonceBase64  - Base64-encoded AES-GCM nonce (12 bytes)
 * @param mimeType   - MIME type of the audio (e.g. "audio/webm", "audio/mp4")
 * @returns Decrypted audio blob URL (object URL — caller should not revoke directly)
 */
export async function fetchAndDecryptAudio(
  s3BaseUrl: string,
  s3Key: string,
  aesKeyBase64: string,
  nonceBase64: string,
  mimeType: string = "audio/webm",
  variant: unknown = {},
): Promise<string> {
  // Return cached blob URL if available
  const cached = audioCache.get(s3Key);
  if (cached) {
    audioCache.delete(s3Key);
    audioCache.set(s3Key, cached);
    cached.refCount++;
    // Cancel pending revocation
    if (cached.revokeTimer) {
      clearTimeout(cached.revokeTimer);
      cached.revokeTimer = null;
    }
    return cached.blobUrl;
  }

  let pending = pendingAudio.get(s3Key);
  if (!pending) {
    pending = loadAudioBlob(s3Key, aesKeyBase64, nonceBase64, mimeType, variant);
    pendingAudio.set(s3Key, pending);
  }
  try {
    const entry = await pending;
    entry.refCount++;
    return entry.blobUrl;
  } finally {
    if (pendingAudio.get(s3Key) === pending) pendingAudio.delete(s3Key);
  }
}

async function loadAudioBlob(
  s3Key: string,
  aesKeyBase64: string,
  nonceBase64: string,
  mimeType: string,
  variant: unknown,
): Promise<AudioCacheEntry> {
  // Fetch the encrypted blob via presigned URL (with automatic 403 retry).
  let encryptedData: ArrayBuffer;
  try {
    encryptedData = await fetchWithPresignedUrl(s3Key);
  } catch (fetchErr) {
    if (
      fetchErr instanceof Error &&
      fetchErr.message.includes("S3 fetch failed")
    ) {
      // Extract status from error message for AudioFetchError compat
      const statusMatch = fetchErr.message.match(/(\d{3})/);
      const status = statusMatch ? parseInt(statusMatch[1], 10) : 0;
      throw new AudioFetchError(s3Key, status, fetchErr.message);
    }
    throw new AudioNetworkError(s3Key, fetchErr);
  }

  let decryptedData: ArrayBuffer;
  try {
    decryptedData = await decryptMediaPayload({
      encryptedData,
      aesKeyBase64,
      variant,
      legacyNonceBase64: nonceBase64,
    });
  } catch (decryptErr) {
    const stage = decryptErr instanceof MediaEncryptionError && decryptErr.stage === "importKey"
      ? "importKey"
      : "decrypt";
    throw new AudioDecryptError(stage, decryptErr);
  }

  // Create blob URL and cache it
  const blob = new Blob([decryptedData], { type: mimeType });
  const blobUrl = URL.createObjectURL(blob);
  const entry = { blobUrl, bytes: blob.size, refCount: 0, revokeTimer: null };
  audioCache.set(s3Key, entry);
  cachedAudioBytes += blob.size;
  return entry;
}


/** Own audio/video acquisitions across repeated effects and async unmount races. */
export function createAudioUrlOwner() {
  const owned = new Map<string, string>();
  const pending = new Map<string, Promise<string>>();
  let disposed = false;
  return {
    fetch(...args: Parameters<typeof fetchAndDecryptAudio>): Promise<string> {
      if (disposed) return Promise.resolve("");
      const key = args[1];
      const existing = owned.get(key);
      if (existing) return Promise.resolve(existing);
      const inFlight = pending.get(key);
      if (inFlight) return inFlight;
      const request = fetchAndDecryptAudio(...args).then((url) => {
        if (disposed) {
          releaseCachedAudio(key);
          return "";
        }
        owned.set(key, url);
        return url;
      }).finally(() => pending.delete(key));
      pending.set(key, request);
      return request;
    },
    release(key: string): void {
      if (owned.delete(key)) releaseCachedAudio(key);
    },
    destroy(): void {
      disposed = true;
      for (const key of Array.from(owned.keys())) releaseCachedAudio(key);
      owned.clear();
    },
  };
}
