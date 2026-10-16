import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

const testMocksDir = resolve(import.meta.dirname, 'src/test-mocks');

export default defineConfig({
  plugins: [{
    name: 'ui-test-shared-config-root',
    enforce: 'pre',
    transform(code, id) {
      if (id.split('?')[0] !== resolve(import.meta.dirname, 'src/config/links.ts')) return;
      // The app-root glob becomes a file-relative glob in standalone UI tests.
      // It still reads the same exact source-owned shared URL fixture.
      return { code: code.replace('"/../../../../../../shared/config/urls.yml"',
        '"../../../../../shared/config/urls.yml"'), map: null };
    },
  }, svelte()],
  resolve: {
    conditions: ['browser'],
    // Frozen source runs must resolve the local package and its one shared raw
    // fixture inside this source tree, not through workspace node_modules links.
    alias: [
      { find: /^@repo\/ui$/, replacement: resolve(import.meta.dirname, 'index.ts') },
    ],
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
