import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

const testMocksDir = resolve(import.meta.dirname, 'src/test-mocks');

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    conditions: ['browser'],
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}'],
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test-setup.ts'],
    alias: {
      '$app/environment': resolve(testMocksDir, 'app-runtime.ts'),
      '$app/forms': resolve(testMocksDir, 'app-forms.ts'),
      '$app/navigation': resolve(testMocksDir, 'app-navigation.ts'),
      '$app/paths': resolve(testMocksDir, 'app-paths.ts'),
      '$app/state': resolve(testMocksDir, 'app-state.ts'),
      '$app/stores': resolve(testMocksDir, 'app-stores.ts'),
    },
  },
});
