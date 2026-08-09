// frontend/packages/ui/src/test-mocks/app-state.ts
// Standalone Vitest shim for SvelteKit's $app/state virtual module.
// SvelteKit 2 exposes plain state objects instead of stores here.
// Keep the shape minimal and stable for import-time consumers in shared UI.
// Tests that need route-specific state can override this module explicitly.

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

export const navigating = { current: null };
export const page = { current: testPage };
export const updated = { check: vi.fn(), current: false };
