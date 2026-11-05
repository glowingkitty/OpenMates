/** Worker-only key bridge. Never import into the page's active authentication flow. */
declare const DedicatedWorkerGlobalScope: { new (): object };

export function validateMasterKey(key: CryptoKey): void {
  const algorithm = key.algorithm as AesKeyAlgorithm;
  if (key.type !== "secret" || algorithm.name !== "AES-GCM" || algorithm.length !== 256
    || !key.extractable || key.usages.length !== 2 || !key.usages.includes("encrypt") || !key.usages.includes("decrypt")) {
    throw new Error("reauthentication_required");
  }
}

/** The consumer must synchronously copy into Rust Zeroizing storage before resolving. */
export async function consumeWorkerMasterKey<T>(key: CryptoKey, consume: (bytes: Uint8Array) => T): Promise<T> {
  // A dedicated page-bound worker is required. Shared/service workers outlive page secrets.
  if (typeof DedicatedWorkerGlobalScope === "undefined" || !(globalThis instanceof DedicatedWorkerGlobalScope)) {
    throw new Error("unavailable");
  }
  validateMasterKey(key);
  const raw = await crypto.subtle.exportKey("raw", key);
  const bytes = new Uint8Array(raw);
  try {
    if (bytes.byteLength !== 32) throw new Error("reauthentication_required");
    return consume(bytes);
  } finally {
    bytes.fill(0);
  }
}
