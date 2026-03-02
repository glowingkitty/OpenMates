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

// ---------------------------------------------------------------------------

/** In-memory cache: maps S3 key → { blobUrl, refCount, revokeTimer } */
const audioCache = new Map<
  string,
  {
    blobUrl: string;
    refCount: number;
    revokeTimer: ReturnType<typeof setTimeout> | null;
  }
>();

/** Grace period before revoking an unreferenced blob URL (ms). */
const REVOKE_GRACE_MS = 60_000;

/**
 * Increment reference count for a cached audio blob URL.
 * Call on component mount to prevent premature revocation.
 */
export function retainCachedAudio(s3Key: string): void {
  const entry = audioCache.get(s3Key);
  if (!entry) return;
  entry.refCount++;
  if (entry.revokeTimer) {
    clearTimeout(entry.revokeTimer);
    entry.revokeTimer = null;
  }
}

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
        URL.revokeObjectURL(current.blobUrl);
        audioCache.delete(s3Key);
      }
    }, REVOKE_GRACE_MS);
  }
}

/**
 * Get a cached blob URL without fetching.
 */
export function getCachedAudioUrl(s3Key: string): string | undefined {
  return audioCache.get(s3Key)?.blobUrl;
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
): Promise<string> {
  // Return cached blob URL if available
  const cached = audioCache.get(s3Key);
  if (cached) {
    cached.refCount++;
    // Cancel pending revocation
    if (cached.revokeTimer) {
      clearTimeout(cached.revokeTimer);
      cached.revokeTimer = null;
    }
    return cached.blobUrl;
  }

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

  // Decode base64 key and nonce
  const aesKeyBytes = base64ToArrayBuffer(aesKeyBase64);
  const nonceBytes = base64ToArrayBuffer(nonceBase64);

  // Import AES key — throws DOMException("DataError") if key bytes are invalid
  let cryptoKey: CryptoKey;
  try {
    cryptoKey = await crypto.subtle.importKey(
      "raw",
      aesKeyBytes,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
  } catch (importErr) {
    throw new AudioDecryptError("importKey", importErr);
  }

  // Decrypt using AES-256-GCM.
  // Throws DOMException("OperationError") if the key/nonce doesn't match the ciphertext.
  let decryptedData: ArrayBuffer;
  try {
    decryptedData = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: nonceBytes },
      cryptoKey,
      encryptedData,
    );
  } catch (decryptErr) {
    throw new AudioDecryptError("decrypt", decryptErr);
  }

  // Create blob URL and cache it
  const blob = new Blob([decryptedData], { type: mimeType });
  const blobUrl = URL.createObjectURL(blob);
  audioCache.set(s3Key, { blobUrl, refCount: 1, revokeTimer: null });

  return blobUrl;
}

/**
 * Convert a base64 string to an ArrayBuffer.
 * Handles both standard and URL-safe base64.
 */
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const normalized = base64.replace(/-/g, "+").replace(/_/g, "/");
  const binaryString = atob(normalized);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
