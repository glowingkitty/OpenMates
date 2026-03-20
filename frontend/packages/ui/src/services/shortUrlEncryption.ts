/**
 * Short URL Encryption Service
 *
 * Client-side encryption/decryption for the ephemeral short URL sharing system.
 * Preserves zero-knowledge architecture: the server stores only an opaque
 * encrypted blob it cannot decrypt. The decryption key (shortKey) lives only
 * in the URL fragment — never sent to the server.
 *
 * URL format: {domain}/s/#{token}-{shortKey}
 *   - token: 8-char base62 lookup ID (sent to server API)
 *   - shortKey: 6-char base62 decryption key (never sent to server)
 *
 * Encryption flow:
 *   1. Generate token (8 chars) + shortKey (6 chars)
 *   2. Derive AES-256 key from shortKey via PBKDF2 (200k iterations, salt="omts-v1-"+token)
 *   3. Encrypt the full share URL (path + #key= fragment) with AES-256-GCM
 *   4. Send token + encrypted blob to server API
 *
 * Architecture reference: /docs/architecture/short_url_sharing.md
 */

// Base62 alphabet for URL-safe token/key generation
const BASE62_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

// PBKDF2 iterations — 2x the existing shareEncryption.ts pattern (100k)
// to compensate for the shorter key length (6 chars vs full encryption keys)
const PBKDF2_ITERATIONS = 200_000;

// Salt prefix for PBKDF2 key derivation
const SALT_PREFIX = "omts-v1-";

/**
 * Generate a random base62 string of the given length.
 * Uses crypto.getRandomValues for cryptographic randomness.
 */
function generateBase62(length: number): string {
  const values = crypto.getRandomValues(new Uint8Array(length));
  let result = "";
  for (let i = 0; i < length; i++) {
    result += BASE62_CHARS[values[i] % BASE62_CHARS.length];
  }
  return result;
}

/**
 * Generate the two components of a short URL:
 * - token: 8-char base62 lookup ID (sent to server)
 * - shortKey: 6-char base62 decryption key (stays in URL fragment)
 */
export function generateShortUrlParts(): { token: string; shortKey: string } {
  return {
    token: generateBase62(8),
    shortKey: generateBase62(6),
  };
}

/**
 * Derive an AES-256-GCM key from the shortKey using PBKDF2.
 *
 * Salt is "omts-v1-" + token, making each short URL's key derivation unique
 * even if the same shortKey were reused (which won't happen in practice since
 * shortKey is randomly generated).
 */
async function deriveKey(shortKey: string, token: string): Promise<CryptoKey> {
  const encoder = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    encoder.encode(shortKey),
    "PBKDF2",
    false,
    ["deriveBits", "deriveKey"],
  );

  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: encoder.encode(SALT_PREFIX + token),
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

/**
 * Base64 URL-safe encoding (matches shareEncryption.ts pattern).
 * Replaces + with -, / with _, removes padding =.
 */
function base64UrlEncode(data: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < data.length; i++) {
    binary += String.fromCharCode(data[i]);
  }
  const base64 = btoa(binary);
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Base64 URL-safe decoding (matches shareEncryption.ts pattern).
 */
function base64UrlDecode(str: string): Uint8Array {
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) {
    base64 += "=";
  }
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Encrypt a full share URL for storage on the server.
 *
 * @param fullUrl - The complete share URL including path and #key= fragment
 * @param token - The lookup token (used in PBKDF2 salt)
 * @param shortKey - The decryption key (used as PBKDF2 input)
 * @returns Base64 URL-safe encoded IV + ciphertext
 */
export async function encryptShareUrl(
  fullUrl: string,
  token: string,
  shortKey: string,
): Promise<string> {
  const key = await deriveKey(shortKey, token);
  const encoder = new TextEncoder();
  const data = encoder.encode(fullUrl);

  // Generate random 12-byte IV for AES-GCM
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    data,
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(ciphertext), iv.length);

  return base64UrlEncode(combined);
}

/**
 * Decrypt a stored encrypted URL.
 *
 * @param encryptedUrl - Base64 URL-safe encoded IV + ciphertext (from server)
 * @param token - The lookup token (used in PBKDF2 salt)
 * @param shortKey - The decryption key (from URL fragment)
 * @returns The decrypted full share URL
 * @throws Error if decryption fails (wrong key, corrupted data, etc.)
 */
export async function decryptShareUrl(
  encryptedUrl: string,
  token: string,
  shortKey: string,
): Promise<string> {
  const key = await deriveKey(shortKey, token);
  const combined = base64UrlDecode(encryptedUrl);

  // Extract IV (first 12 bytes) and ciphertext
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);

  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv },
    key,
    ciphertext,
  );

  return new TextDecoder().decode(decrypted);
}

/**
 * Parse a short URL fragment into token and shortKey.
 *
 * Fragment format: "{token}-{shortKey}" (e.g., "a8f3kLmN-Xk7pQr")
 *
 * @param fragment - The URL hash without the leading '#'
 * @returns Parsed token and shortKey, or null if invalid format
 */
export function parseShortUrlFragment(
  fragment: string,
): { token: string; shortKey: string } | null {
  // Remove leading # if present
  const clean = fragment.startsWith("#") ? fragment.slice(1) : fragment;

  const dashIndex = clean.indexOf("-");
  if (dashIndex === -1) return null;

  const token = clean.slice(0, dashIndex);
  const shortKey = clean.slice(dashIndex + 1);

  // Validate: token 6-12 chars, shortKey 4-12 chars, both base62
  const base62Pattern = /^[A-Za-z0-9]+$/;
  if (
    token.length < 6 || token.length > 12 ||
    shortKey.length < 4 || shortKey.length > 12 ||
    !base62Pattern.test(token) ||
    !base62Pattern.test(shortKey)
  ) {
    return null;
  }

  return { token, shortKey };
}

/**
 * Build the short URL string.
 *
 * If PUBLIC_SHORT_URL_DOMAIN env var is set, uses that domain.
 * Otherwise, falls back to the current app domain + /s/ path.
 *
 * @param token - The lookup token
 * @param shortKey - The decryption key
 * @returns The complete short URL (e.g., "https://omts.io/#token-shortKey")
 */
export function buildShortUrl(token: string, shortKey: string): string {
  const shortDomain = typeof import.meta !== "undefined"
    ? import.meta.env?.VITE_SHORT_URL_DOMAIN
    : undefined;

  if (shortDomain) {
    // Custom short domain: omts.io/#token-shortKey
    return `https://${shortDomain}/#${token}-${shortKey}`;
  }

  // Fallback: current domain + /s/ path
  const origin = typeof window !== "undefined"
    ? window.location.origin
    : "https://openmates.org";
  return `${origin}/s/#${token}-${shortKey}`;
}
