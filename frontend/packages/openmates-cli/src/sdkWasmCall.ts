/** Shared typed call into the portable WASM core for stateless SDK facades. */
import { loadSdkWasm, type SdkWasmExports } from "./sdkWasm.js";
import { SessionClientError } from "./sdkSession.js";

type JsonExport = "keyManagement" | "models";

/**
 * Invoke one JSON export and decode its result. A missing artifact raises
 * `native_binding_unavailable`; a Rust `BindingError` keeps its fixed code and
 * message. There is no TypeScript fallback.
 */
export function callSdkWasm<T>(name: JsonExport, input: Record<string, unknown>): T {
  const native: SdkWasmExports | null = loadSdkWasm();
  if (!native) throw new SessionClientError("native_binding_unavailable", "Install an OpenMates SDK build containing its WebAssembly module.");
  let encoded: string;
  try {
    encoded = native[name](JSON.stringify(input));
  } catch (error) {
    let value: unknown;
    // Only a structured Rust BindingError message parses; anything else is the fixed generic failure.
    try { value = JSON.parse(error instanceof Error ? error.message : ""); } catch { value = null; }
    const typed = value as { code?: unknown; message?: unknown } | null;
    if (typed && typeof typed.code === "string" && typeof typed.message === "string") throw new SessionClientError(typed.code, typed.message);
    throw new SessionClientError("native_failure", "The native SDK operation failed.");
  }
  return JSON.parse(encoded) as T;
}
