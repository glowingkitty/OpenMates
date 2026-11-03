// Tiny registry that lets @openmates/ui services obtain the Rust core Worker without
// importing web_app code (the Worker/WASM assets resolve only in the web_app build).
// The web_app registers its factory once under the VITE_OPENMATES_RUST_CORE guard;
// with the flag OFF nothing registers and every lookup reports "not enabled".
import type { BrowserCoreWorkerHost } from '../workerHost';

export interface RustCoreWorkerInput {
  apiUrl: string;
  sessionId: string;
  expectedPrincipal: string;
  signal: AbortSignal;
}
export interface RustCoreWorker { host: BrowserCoreWorkerHost; close(): void }
export type RustCoreWorkerFactory = (input: RustCoreWorkerInput) => Promise<RustCoreWorker>;

let factory: RustCoreWorkerFactory | null = null;

/** Registers the single factory; returns an unregister function bound to this exact registration. */
export function registerRustCoreWorkerFactory(next: RustCoreWorkerFactory): () => void {
  factory = next;
  return () => { if (factory === next) factory = null; };
}
/** True only when the Rust-core build registered a factory. */
export function isRustCoreRegistered(): boolean { return factory !== null; }
/** Throws the fixed code `rust_core_not_enabled` when no factory is registered. */
export function requireRustCoreWorkerFactory(): RustCoreWorkerFactory {
  if (!factory) throw new Error('rust_core_not_enabled');
  return factory;
}
