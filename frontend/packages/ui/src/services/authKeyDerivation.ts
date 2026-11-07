/**
 * Passkey/PRF, recovery-key and password key-derivation helpers.
 * Pure move out of cryptoService.ts (behavior unchanged); cryptoService
 * re-exports every symbol for existing callers.
 */

const PBKDF2_ITERATIONS = 100000;
const UNSUPPORTED_CLIENT_CRYPTO_CODE = "unsupported_client_crypto";

export class UnsupportedClientCryptoError extends Error {
  readonly code = UNSUPPORTED_CLIENT_CRYPTO_CODE;

  constructor(operation: string) {
    super(`${operation} requires the Web Crypto API`);
    this.name = "UnsupportedClientCryptoError";
  }
}

export function requireSubtleCrypto(operation: string): SubtleCrypto {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new UnsupportedClientCryptoError(operation);
  }
  return subtle;
}

/**
 * Derives a key from a password using PBKDF2
 * @param password - The password string
 * @param salt - Salt bytes
 * @returns Promise<Uint8Array> - Derived key bytes
 */
export async function deriveKeyFromPassword(
  password: string,
  salt: Uint8Array,
): Promise<Uint8Array> {
  const subtle = requireSubtleCrypto("Password key derivation");
  const encoder = new TextEncoder();
  const keyMaterial = await subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveKey", "deriveBits"],
  );

  const saltBuffer = new Uint8Array(salt);
  const derivedBits = await subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: saltBuffer,
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    256,
  );

  return new Uint8Array(derivedBits);
}

/**
 * Derives a key from an API key using PBKDF2 (same as password derivation)
 * Used for encrypting the master key with the API key for CLI/npm/pip access
 * @param apiKey - The API key string
 * @param salt - Random salt (should be generated per API key)
 * @returns Promise<Uint8Array> - 256-bit derived key
 */
export async function deriveKeyFromApiKey(
  apiKey: string,
  salt: Uint8Array,
): Promise<Uint8Array> {
  // Use the same derivation as passwords for consistency
  return deriveKeyFromPassword(apiKey, salt);
}

// ============================================================================
// RECOVERY KEY MANAGEMENT
// ============================================================================

/**
 * Generates a secure recovery key with good entropy and readability
 * @param length - The length of the recovery key
 * @returns string - The generated recovery key
 */
export function generateSecureRecoveryKey(length = 24): string {
  // Define character sets for the recovery key
  const uppercaseChars = "ABCDEFGHJKLMNPQRSTUVWXYZ"; // Removed confusing I and O
  const lowercaseChars = "abcdefghijkmnopqrstuvwxyz"; // Removed confusing l
  const numberChars = "23456789"; // Removed confusing 0 and 1
  const specialChars = "#-=+_&%$";

  // Combine all character sets
  const allChars = uppercaseChars + lowercaseChars + numberChars + specialChars;

  // Generate random bytes using cryptographically secure RNG
  // Ensure we have at least one character from each set by reserving positions
  const result: string[] = new Array(length);

  // Reserve first 4 positions for mandatory character types
  const charSets = [
    { chars: uppercaseChars, index: 0 },
    { chars: lowercaseChars, index: 1 },
    { chars: numberChars, index: 2 },
    { chars: specialChars, index: 3 },
  ];

  // Fill mandatory positions with secure randomness
  for (const charSet of charSets) {
    result[charSet.index] = charSet.chars.charAt(secureRandomIndex(charSet.chars.length));
  }

  // Fill remaining positions with secure random characters from all sets
  for (let i = 4; i < length; i++) {
    result[i] = allChars.charAt(secureRandomIndex(allChars.length));
  }

  // Shuffle using Fisher-Yates with cryptographically secure randomness
  for (let i = result.length - 1; i > 0; i--) {
    const j = secureRandomIndex(i + 1);
    [result[i], result[j]] = [result[j], result[i]];
  }

  return result.join("");
}

function secureRandomIndex(upperBound: number): number {
  if (!Number.isInteger(upperBound) || upperBound <= 0 || upperBound > 256) {
    throw new RangeError("secure random upper bound must be between 1 and 256");
  }
  const maxUnbiasedValue = Math.floor(256 / upperBound) * upperBound;
  while (true) {
    const value = crypto.getRandomValues(new Uint8Array(1))[0];
    if (value < maxUnbiasedValue) return value % upperBound;
  }
}

/**
 * Creates a SHA-256 hash of any key (password, recovery key, passkey PRF) for lookup purposes
 * Optionally includes a salt for additional security
 *
 * @param key - The key to hash (password, recovery key, etc.)
 * @param salt - Optional salt to include in the hash
 * @returns Promise<string> - Base64 encoded hash
 */
export async function hashKey(
  key: string,
  salt: Uint8Array | null = null,
): Promise<string> {
  const encoder = new TextEncoder();
  const keyBytes = encoder.encode(key);

  let dataToHash: Uint8Array;

  // If salt is provided, combine it with the key
  if (salt) {
    dataToHash = new Uint8Array(keyBytes.length + salt.length);
    dataToHash.set(keyBytes);
    dataToHash.set(salt, keyBytes.length);
  } else {
    dataToHash = keyBytes;
  }

  // Hash the data
  // Ensure dataToHash is a proper BufferSource
  const dataToHashBuffer = new Uint8Array(dataToHash);
  const hashBuffer = await crypto.subtle.digest("SHA-256", dataToHashBuffer);
  const hashArray = new Uint8Array(hashBuffer);

  // Convert to base64 string
  let hashBinary = "";
  for (let i = 0; i < hashArray.length; i++) {
    hashBinary += String.fromCharCode(hashArray[i]);
  }
  return window.btoa(hashBinary);
}

// ============================================================================
// PASSKEY PRF AND HKDF FUNCTIONS
// ============================================================================

type PRFSignatureBuffer = ArrayBuffer | ArrayBufferView | string;

interface PRFExtensionResults {
  enabled?: boolean;
  results?: { first?: PRFSignatureBuffer };
}

interface PasskeyPRFFallbackOptions {
  credential: PublicKeyCredential;
  challenge: ArrayBuffer;
  rpId: string;
  timeout?: number;
  userVerification?: UserVerificationRequirement;
  prfEvalFirst: ArrayBuffer;
}

function prfSignatureToUint8Array(signature: PRFSignatureBuffer): Uint8Array {
  if (typeof signature === "string") {
    const bytes = signature.match(/.{1,2}/g)?.map((byte) => parseInt(byte, 16));
    if (!bytes || bytes.some((byte) => Number.isNaN(byte))) {
      throw new Error("PRF signature hex string is invalid");
    }
    return new Uint8Array(bytes);
  }

  if (signature instanceof ArrayBuffer) {
    return new Uint8Array(signature);
  }

  if (ArrayBuffer.isView(signature)) {
    return new Uint8Array(signature.buffer, signature.byteOffset, signature.byteLength);
  }

  throw new Error("PRF signature is in an unknown format");
}

function getPRFSignatureFromCredential(credential: PublicKeyCredential, context: string): Uint8Array | null {
  const clientExtensionResults = credential.getClientExtensionResults();
  console.log(`[${context}] Client extension results:`, clientExtensionResults);
  const prfResults = (clientExtensionResults as { prf?: PRFExtensionResults } | undefined)?.prf;
  console.log(`[${context}] PRF results:`, prfResults);

  if (!prfResults) {
    throw new Error("PRF extension not found in client extension results");
  }

  if (prfResults.enabled === false) {
    throw new Error("PRF extension explicitly disabled");
  }

  const signature = prfResults.results?.first;
  if (!signature) {
    return null;
  }

  const prfSignature = prfSignatureToUint8Array(signature);
  if (prfSignature.length < 16 || prfSignature.length > 64) {
    throw new Error(`PRF signature has invalid length: ${prfSignature.length}`);
  }

  console.log(`[${context}] PRF signature extracted successfully`, {
    length: prfSignature.length,
    firstBytes: Array.from(prfSignature.slice(0, 4)),
  });
  return prfSignature;
}

/**
 * Returns PRF output for a newly-created credential.
 *
 * Some authenticators enable PRF during create() but only return evaluated PRF
 * output during get(). The fallback keeps PRF mandatory while accepting those
 * otherwise-compatible authenticators.
 */
export async function getPRFSignatureForPasskeyRegistration(
  options: PasskeyPRFFallbackOptions,
  context: string = "PasskeyRegistration",
): Promise<Uint8Array> {
  const createSignature = getPRFSignatureFromCredential(options.credential, context);
  if (createSignature) {
    return createSignature;
  }

  console.log(`[${context}] PRF output missing from create(); requesting scoped assertion fallback`);
  const assertion = await navigator.credentials.get({
    publicKey: {
      challenge: options.challenge,
      rpId: options.rpId,
      timeout: options.timeout,
      userVerification: options.userVerification ?? "required",
      allowCredentials: [
        {
          type: "public-key",
          id: options.credential.rawId,
        },
      ],
      extensions: {
        prf: {
          eval: {
            first: options.prfEvalFirst,
          },
        },
      } as AuthenticationExtensionsClientInputs,
    },
  }) as PublicKeyCredential | null;

  if (!assertion || !(assertion instanceof PublicKeyCredential)) {
    throw new Error("PRF fallback assertion did not return a valid credential");
  }

  const fallbackSignature = getPRFSignatureFromCredential(assertion, `${context}Fallback`);
  if (!fallbackSignature) {
    throw new Error("PRF signature not found in fallback assertion results");
  }
  return fallbackSignature;
}

/**
 * HMAC-based Key Derivation Function (HKDF) as specified in RFC 5869
 * Used to derive wrapping keys from PRF signatures for passkey authentication
 *
 * @param salt - Salt value (user_email_salt for passkeys)
 * @param ikm - Input key material (PRF signature bytes)
 * @param info - Application-specific information ("masterkey_wrapping")
 * @param length - Desired output length in bytes (32 for AES-256)
 * @returns Promise<Uint8Array> - Derived key bytes
 */
export async function hkdf(
  salt: Uint8Array,
  ikm: Uint8Array,
  info: string,
  length: number = 32,
): Promise<Uint8Array> {
  const subtle = requireSubtleCrypto("Passkey HKDF derivation");
  const encoder = new TextEncoder();
  const infoBytes = encoder.encode(info);

  // Step 1: Extract (HKDF-Extract)
  // PRK = HMAC-Hash(salt, IKM)
  // Ensure salt is a proper BufferSource by creating a new Uint8Array
  const saltBuffer = new Uint8Array(salt);
  const extractKey = await subtle.importKey(
    "raw",
    saltBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  // Ensure ikm is a proper BufferSource
  const ikmBuffer = new Uint8Array(ikm);
  const prk = await subtle.sign("HMAC", extractKey, ikmBuffer);
  const prkArray = new Uint8Array(prk);

  // Step 2: Expand (HKDF-Expand)
  // OKM = HKDF-Expand(PRK, info, L)
  const expandKey = await subtle.importKey(
    "raw",
    prkArray,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const okm: Uint8Array[] = [];
  let counter = 1;
  let remaining = length;

  while (remaining > 0) {
    // T(i) = HMAC-Hash(PRK, T(i-1) | info | i)
    const tInput = new Uint8Array(
      (okm.length > 0 ? okm[okm.length - 1].length : 0) + infoBytes.length + 1,
    );
    let offset = 0;

    if (okm.length > 0) {
      tInput.set(okm[okm.length - 1], offset);
      offset += okm[okm.length - 1].length;
    }

    tInput.set(infoBytes, offset);
    offset += infoBytes.length;
    tInput[offset] = counter;

    const t = await subtle.sign("HMAC", expandKey, tInput);
    const tArray = new Uint8Array(t);

    const toTake = Math.min(remaining, tArray.length);
    okm.push(tArray.slice(0, toTake));
    remaining -= toTake;
    counter++;
  }

  // Concatenate all T(i) values
  const result = new Uint8Array(length);
  let resultOffset = 0;
  for (const chunk of okm) {
    result.set(chunk, resultOffset);
    resultOffset += chunk.length;
  }

  return result;
}

/**
 * Derives a wrapping key from a PRF signature using HKDF
 * This is used for passkey-based master key wrapping (zero-knowledge encryption)
 *
 * @param prfSignature - PRF signature bytes from WebAuthn extension
 * @param emailSalt - User's email salt (user_email_salt)
 * @returns Promise<Uint8Array> - Derived wrapping key (32 bytes for AES-256)
 */
export async function deriveWrappingKeyFromPRF(
  prfSignature: Uint8Array,
  emailSalt: Uint8Array,
): Promise<Uint8Array> {
  const info = "masterkey_wrapping";
  return await hkdf(emailSalt, prfSignature, info, 32);
}

/**
 * Creates a lookup hash from PRF signature for authentication
 * Same pattern as password: SHA256(PRF_signature + user_email_salt)
 *
 * @param prfSignature - PRF signature bytes from WebAuthn extension
 * @param emailSalt - User's email salt (user_email_salt)
 * @returns Promise<string> - Base64-encoded lookup hash
 */
export async function hashKeyFromPRF(
  prfSignature: Uint8Array,
  emailSalt: Uint8Array,
): Promise<string> {
  // Combine PRF signature and salt
  const combined = new Uint8Array(prfSignature.length + emailSalt.length);
  combined.set(prfSignature);
  combined.set(emailSalt, prfSignature.length);

  // Hash with SHA-256
  const hashBuffer = await crypto.subtle.digest("SHA-256", combined);
  const hashArray = new Uint8Array(hashBuffer);

  // Convert to base64
  let hashBinary = "";
  for (let i = 0; i < hashArray.length; i++) {
    hashBinary += String.fromCharCode(hashArray[i]);
  }
  return window.btoa(hashBinary);
}

/**
 * Checks if PRF extension is supported by the browser/device
 * This is a helper function for error messages - actual PRF support
 * can only be verified after attempting to create a passkey
 *
 * @returns boolean - True if WebAuthn and PRF extension might be supported
 */
function _checkPRFSupport(): boolean {
  if (typeof window === "undefined" || !navigator.credentials) {
    return false;
  }

  // Check if WebAuthn is available
  if (!navigator.credentials.create || !navigator.credentials.get) {
    return false;
  }

  // PRF extension support can only be verified by attempting creation
  // This function just checks if WebAuthn API is available
  // Actual PRF support is checked via getClientExtensionResults() after creation
  return true;
}
