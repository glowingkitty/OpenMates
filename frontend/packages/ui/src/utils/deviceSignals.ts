// frontend/packages/ui/src/utils/deviceSignals.ts

/**
 * Hashes a string using SHA-256 via the SubtleCrypto API.
 * @param input The string to hash.
 * @returns A promise that resolves with the hex-encoded SHA-256 hash, or null on error.
 */
async function sha256(input: string): Promise<string | null> {
  try {
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return hashHex;
  } catch (error) {
    console.error('Error hashing string:', error);
    return null;
  }
}

/**
 * Collects various client-side device signals and returns their SHA-256 hashes.
 * This has been stripped down to only include stable signals.
 * @returns A promise that resolves with an object containing hashed signals.
 */
export async function collectDeviceSignals(): Promise<Record<string, string | null>> {
  const signals: Record<string, string | null> = {};

  // Basic Signals
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const language = navigator.language || (navigator as any).userLanguage; // Include fallback

  signals.timeZoneHash = await sha256(timezone);
  signals.languageHash = await sha256(language);

  console.debug("Collected device signal hashes:", signals);
  return signals;
}
