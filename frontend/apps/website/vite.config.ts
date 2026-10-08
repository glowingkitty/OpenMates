import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { gzipSync } from 'node:zlib';
import type { Plugin } from 'vite';

function publicBundleBoundary(): Plugin {
  return {
    name: 'public-bundle-boundary',
    generateBundle(options, bundle) {
      const outputDir = options.dir ?? '';
      if (!outputDir.includes('/client')) return;
      let totalGzipBytes = 0;
      const rows: string[] = [];
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue;
        const forbidden = Object.keys(output.modules).filter((id) =>
          /\/frontend\/(?:apps\/web_app|packages\/ui)\//.test(id) ||
          /\/node_modules\/(?:dexie|@stripe\/stripe-js|svelte-i18n)\//.test(id)
        );
        if (forbidden.length) this.error(`Website client chunk ${output.fileName} imports app runtime modules:\n${forbidden.join('\n')}`);
        const compressed = gzipSync(output.code).byteLength;
        totalGzipBytes += compressed;
        rows.push(`${output.fileName}: ${(compressed / 1024).toFixed(1)} KiB gzip`);
      }
      this.info(`Website client JS: ${(totalGzipBytes / 1024).toFixed(1)} KiB gzip across ${rows.length} chunks\n${rows.join('\n')}`);
    }
  };
}

export default defineConfig({ plugins: [sveltekit(), publicBundleBoundary()] });
