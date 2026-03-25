// vitest.config.ts — Unit tests only (NOT Playwright E2E specs).
// Auto-discovered by the daily test runner (run-tests.sh).
// Playwright specs (*.spec.ts) are handled separately by run_playwright().
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.{js,ts}'],
    exclude: ['tests/**', 'node_modules/**', 'src/**/*.spec.ts'],
  },
});
