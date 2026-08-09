// frontend/packages/ui/src/test-mocks/app-forms.ts
// Standalone Vitest shim for SvelteKit's $app/forms virtual module.
// UI package unit tests only need callable exports during import analysis.
// Specs that exercise form behavior can replace these defaults with vi.mock.
// This file intentionally carries no product behavior.

import { vi } from "vitest";

export const applyAction = vi.fn();
export const deserialize = vi.fn();
export const enhance = vi.fn();
