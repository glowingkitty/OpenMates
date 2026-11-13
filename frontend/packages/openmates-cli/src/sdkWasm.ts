/**
 * Portable WebAssembly build of the shared OpenMates Rust core for the npm SDK.
 *
 * One artifact (`wasm/openmates_sdk_bg.wasm` + its wasm-bindgen glue) replaces
 * the per-platform Node-API binaries for every operation that has moved to it.
 * Loading is explicit and synchronous: if the packaged module is missing or
 * cannot be instantiated, callers receive their typed `native_binding_unavailable`
 * error. There is no TypeScript fallback and no CLI process.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

/** Stateless exports; each takes and returns the shared JSON contract. */
export interface SdkWasmExports {
  privacy(input: string): string;
  taskOrder(input: string): string;
  reconstructEmbedVersion(input: string): string;
  keyManagement(input: string): string;
  models(input: string): string;
}

interface WasmGlue extends SdkWasmExports {
  initSync(options: { module: BufferSource }): unknown;
}

let loaded: SdkWasmExports | null = null;

/** Returns the initialized module, or null when it is not packaged/instantiable. */
export function loadSdkWasm(): SdkWasmExports | null {
  if (loaded) return loaded;
  try {
    // wasm-bindgen `web` glue is plain ESM without top-level await, so Node's
    // synchronous require(esm) loads it; the bytes are instantiated directly.
    const glue = createRequire(import.meta.url)("../wasm/openmates_sdk.js") as WasmGlue;
    glue.initSync({ module: readFileSync(new URL("../wasm/openmates_sdk_bg.wasm", import.meta.url)) });
    if ([glue.privacy, glue.taskOrder, glue.reconstructEmbedVersion, glue.keyManagement, glue.models].some(fn => typeof fn !== "function")) return null;
    loaded = glue;
  } catch {
    // Missing/incompatible artifact: the caller raises its typed refusal.
    return null;
  }
  return loaded;
}
