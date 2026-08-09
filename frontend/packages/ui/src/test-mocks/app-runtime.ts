// frontend/packages/ui/src/test-mocks/app-runtime.ts
// Standalone Vitest shim for SvelteKit's $app/environment virtual module.
// The shared UI package runs outside the generated web app .svelte-kit tree.
// Keep values browser-like by default; individual tests may still override
// this module with vi.mock when they need a server or build-specific branch.

export const browser = true;
export const building = false;
export const dev = true;
export const version = "test";
