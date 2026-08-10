// frontend/packages/ui/src/test-mocks/app-paths.ts
// Standalone Vitest shim for SvelteKit's $app/paths virtual module.
// The UI package unit runner has no generated SvelteKit path metadata.
// Empty paths match the default dev app shape used by existing tests.
// Specs may override these exports with vi.mock for path-specific behavior.

export const assets = "";
export const base = "";
