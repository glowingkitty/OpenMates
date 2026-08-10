// frontend/packages/ui/src/test-mocks/app-stores.ts
// Standalone Vitest shim for SvelteKit's legacy $app/stores virtual module.
// Some shared UI modules still import store-shaped page and navigation state.
// This keeps import-time behavior deterministic outside the web app runtime.
// Specs that need custom route data can override this module with vi.mock.

import { vi } from "vitest";

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

export const navigating = readable(null);
export const page = readable(testPage);
export const updated = { ...readable(false), check: vi.fn() };
