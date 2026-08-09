import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

const svelteKitAppMock = resolve(import.meta.dirname, 'src/test-mocks/sveltekit-app.ts');

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
      '$app/environment': svelteKitAppMock,
      '$app/forms': svelteKitAppMock,
      '$app/navigation': svelteKitAppMock,
      '$app/paths': svelteKitAppMock,
      '$app/state': svelteKitAppMock,
      '$app/stores': svelteKitAppMock,
    },
  },
});
