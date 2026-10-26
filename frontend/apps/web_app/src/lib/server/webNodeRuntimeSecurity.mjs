import { constants as zlibConstants } from 'node:zlib';

/**
 * Backported fixes can retain Brotli's old version string; check Node and patch.
 * @param {{ nodeVersion?: string, brotliConstants?: object }} [options]
 */
export function assertWebNodeRuntimeSecurity({ nodeVersion = process.versions.node, brotliConstants = zlibConstants } = {}) {
  const version = /^v?24\.(\d+)\.(\d+)$/.exec(nodeVersion);
  const patchedNode = version && (Number(version[1]) > 22 || (Number(version[1]) === 22 && Number(version[2]) >= 1));
  // Reflect supports runtimes newer than the installed Node type declarations.
  if (!patchedNode || Reflect.get(brotliConstants, 'BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH') !== -17) {
    throw new Error('The web runtime requires Node.js 24.22.1 or newer within 24.x with the Brotli security patch. Update the runtime before retrying.');
  }
}
