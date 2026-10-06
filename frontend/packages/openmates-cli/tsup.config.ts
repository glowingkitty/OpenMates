import { defineConfig } from 'tsup';

// Bundle the private workspace source into the published CLI, while keeping
// @serenity-kit/opaque as a pinned runtime dependency.
export default defineConfig({ noExternal: ['@repo/pairing-crypto', '@repo/upload-privacy'] });
