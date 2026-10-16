/** Packaging gate only; installation never compiles or downloads automatically. */
import { createHash } from 'node:crypto';
import { readFileSync, lstatSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
const directory = fileURLToPath(new URL('../fixtures/privacy-runtime/linux-arm64/', import.meta.url));
const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
if (manifest.revision !== '735a6c28607ee82afc3a670383f41b55266a3b9a' || manifest.protocol !== 1
    || !manifest.files?.some((file) => file.name === 'openmates-pii-worker')) throw new Error('Missing pinned native privacy runtime');
for (const file of manifest.files) {
  if (!/^[A-Za-z0-9._-]+$/.test(file.name)) throw new Error('Invalid native asset name');
  const path = join(directory, file.name), info = lstatSync(path);
  if (!info.isFile() || info.isSymbolicLink() || info.size !== file.bytes
      || createHash('sha256').update(readFileSync(path)).digest('hex') !== file.sha256) throw new Error('Native privacy asset integrity failure');
}
console.log('Pinned offline privacy runtime is ready for packaging (no weights included).');
