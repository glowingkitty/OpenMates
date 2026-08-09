// frontend/packages/ui/src/test-mocks/sveltekit-app.ts
// Standalone Vitest shim for SvelteKit virtual $app modules used by shared UI.
// The UI package is tested outside the web app's generated .svelte-kit tree, so
// Vite needs concrete files for import analysis before per-test vi.mock calls run.
// Keep this minimal and browser-like; individual specs can override with vi.mock.

import { vi } from "vitest";

export const browser = true;
export const building = false;
export const dev = true;
export const version = "test";
export const base = "";
export const assets = "";

const testPage = {
  data: {},
  error: null,
  form: null,
  params: {},
  route: { id: null },
  status: 200,
  url: new URL("http://localhost/"),
};

function readable<T>(value: T) {
  return {
    subscribe(run: (current: T) => void) {
      run(value);
      return () => undefined;
    },
  };
}

export const afterNavigate = vi.fn();
export const beforeNavigate = vi.fn();
export const disableScrollHandling = vi.fn();
export const goto = vi.fn();
export const invalidate = vi.fn();
export const invalidateAll = vi.fn();
export const onNavigate = vi.fn();
export const preloadCode = vi.fn();
export const preloadData = vi.fn();
export const pushState = vi.fn();
export const replaceState = vi.fn();
export const applyAction = vi.fn();
export const deserialize = vi.fn();
export const enhance = vi.fn();

export const navigating = readable(null);
export const page = readable(testPage);
export const updated = { ...readable(false), check: vi.fn() };
