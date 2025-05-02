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
 * Attempts to get a Canvas fingerprint hash.
 * NOTE: This can be blocked by privacy extensions or browser settings.
 * @returns A promise that resolves with the SHA-256 hash of the canvas data URL, or null if unavailable/error.
 */
async function getCanvasFingerprint(): Promise<string | null> {
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    // Simple drawing known to produce variations
    ctx.textBaseline = 'top';
    ctx.font = "14px 'Arial'";
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#f60';
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText("Browser Canvas Fingerprint", 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText("Browser Canvas Fingerprint", 4, 17);

    const dataUrl = canvas.toDataURL();
    return await sha256(dataUrl);
  } catch (error) {
    console.warn('Error getting canvas fingerprint:', error);
    return null;
  }
}

/**
 * Attempts to get WebGL vendor and renderer info hash.
 * NOTE: Can be blocked or spoofed.
 * @returns A promise that resolves with the SHA-256 hash of WebGL info, or null if unavailable/error.
 */
async function getWebglFingerprint(): Promise<string | null> {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl || !(gl instanceof WebGLRenderingContext)) return null;

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const vendor = gl.getParameter(debugInfo?.UNMASKED_VENDOR_WEBGL ?? gl.VENDOR);
    const renderer = gl.getParameter(debugInfo?.UNMASKED_RENDERER_WEBGL ?? gl.RENDERER);

    const webglInfo = `Vendor: ${vendor}, Renderer: ${renderer}`;
    return await sha256(webglInfo);
  } catch (error) {
    console.warn('Error getting WebGL fingerprint:', error);
    return null;
  }
}


/**
 * Collects various client-side device signals and returns their SHA-256 hashes.
 * Includes basic signals (screen, timezone, language) and advanced signals (Canvas, WebGL).
 * TODO: Consider gating advanced signals based on user consent for privacy.
 * @returns A promise that resolves with an object containing hashed signals.
 */
export async function collectDeviceSignals(): Promise<Record<string, string | null>> {
  const signals: Record<string, string | null> = {};

  // Basic Signals
  const screenResolution = `${window.screen.width}x${window.screen.height}x${window.screen.colorDepth}`;
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const language = navigator.language || (navigator as any).userLanguage; // Include fallback

  signals.screenHash = await sha256(screenResolution);
  signals.timeZoneHash = await sha256(timezone);
  signals.languageHash = await sha256(language);

  // Advanced Signals (Potentially gate these based on consent)
  signals.canvasHash = await getCanvasFingerprint();
  signals.webGLHash = await getWebglFingerprint();
  // signals.fontsHash = await getFontsFingerprint(); // Example if implemented

  // Filter out null values before returning? For now, return all.
  // const filteredSignals = Object.entries(signals)
  //   .filter(([_, value]) => value !== null)
  //   .reduce((obj, [key, value]) => {
  //     obj[key] = value;
  //     return obj;
  //   }, {} as Record<string, string>);

  console.debug("Collected device signal hashes:", signals);
  return signals;
}