// frontend/packages/ui/src/test-mocks/app-navigation.ts
// Standalone Vitest shim for SvelteKit's $app/navigation virtual module.
// Shared UI tests run without a generated SvelteKit runtime, so Vite needs a
// concrete module for import resolution before per-test vi.mock calls execute.
// Navigation behavior remains test-owned through explicit spies and overrides.

import { vi } from "vitest";

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
