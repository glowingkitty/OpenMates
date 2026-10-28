/** Package pinned public assets only: no SDK execution, inference or telemetry. */
import { createRequire } from 'node:module';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, copyFile, writeFile, readFile, rename, rm } from 'node:fs/promises';
import { build } from 'esbuild';
import { parse } from 'yaml';
import { assertWebNodeRuntimeSecurity } from '../src/lib/server/webNodeRuntimeSecurity.mjs';
import { piiRuntimeVersion, piiRuntimeBase, piiModel, piiPinnedFiles, piiRegistryIntegrities, piiWorkerCSP } from './pii-runtime-manifest.mjs';

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const uiRequire = createRequire(resolve(appRoot, '../../packages/ui/package.json'));
export const piiRuntimeOutput = resolve(appRoot, `static/pii-runtime/${piiRuntimeVersion}`);
export { piiWorkerCSP };
let preparing;

export function verifyPIIAsset(bytes, expected, name) {
  const actual = { bytes: bytes.byteLength, sha256: createHash('sha256').update(bytes).digest('hex') };
  if (actual.bytes !== expected.bytes || actual.sha256 !== expected.sha256) throw new Error(`PII asset integrity mismatch: ${name}`);
  return actual;
}

/** pnpm verifies downloaded tarballs; additionally refuse a changed registry pin. */
export function verifyPIIRegistryPins(lock) {
  for (const [name, integrity] of Object.entries(piiRegistryIntegrities)) {
    if (lock.packages?.[name]?.resolution?.integrity !== integrity) throw new Error(`PII registry integrity mismatch: ${name}`);
  }
}

/** Both existing cache bytes and fresh downloads must match the reviewed pins. */
export async function preparePIICachedAsset({ cached, url, expected, fetchAsset = fetch }) {
  assertWebNodeRuntimeSecurity();
  try {
    const bytes = await readFile(cached);
    verifyPIIAsset(bytes, expected, url);
    return bytes;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error; // A poisoned cache fails closed.
  }
  const response = await fetchAsset(url, { credentials: 'omit', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(120_000) });
  if (!response.ok || /(?:text\/html|application\/xhtml\+xml)/i.test(response.headers.get('content-type') ?? '')) throw new Error(`PII model download failed: ${url}`);
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.byteLength;
    if (size > expected.bytes) throw new Error(`PII asset size exceeded: ${url}`);
    chunks.push(chunk);
  }
  const bytes = Buffer.concat(chunks);
  verifyPIIAsset(bytes, expected, url);
  const temporary = `${cached}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, bytes, { flag: 'wx' });
    await rename(temporary, cached);
  } finally { await rm(temporary, { force: true }); }
  return bytes;
}

export async function preparePIIModel({ output = piiRuntimeOutput, cache = resolve(appRoot, 'node_modules/.cache/openmates-pii', piiModel.revision), fetchAsset = fetch } = {}) {
  await mkdir(join(output, 'model'), { recursive: true });
  await mkdir(cache, { recursive: true });
  for (const [path, expected] of Object.entries(piiPinnedFiles).filter(([name]) => name.startsWith('model/'))) {
    const name = path.slice('model/'.length);
    const bytes = await preparePIICachedAsset({
      cached: join(cache, name), expected, fetchAsset,
      url: `https://huggingface.co/${piiModel.repository}/resolve/${piiModel.revision}/${name}`,
    });
    await writeFile(join(output, path), bytes);
  }
}

export async function preparePIIRuntime() {
  assertWebNodeRuntimeSecurity();
  if (preparing) return preparing;
  preparing = (async () => {
    const sdkRoot = dirname(uiRequire.resolve('@desert-ant-labs/redact'));
    const sdkRequire = createRequire(join(sdkRoot, 'package.json'));
    const coreRoot = dirname(sdkRequire.resolve('@desert-ant-labs/core'));
    const liteRoot = resolve(dirname(uiRequire.resolve('@litertjs/core')), '..');
    for (const [root, version] of [[sdkRoot, '4.1.0'], [coreRoot, '4.1.0'], [liteRoot, '2.6.0']]) {
      const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
      if (pkg.version !== version) throw new Error('PII runtime dependency version mismatch');
    }
    verifyPIIRegistryPins(parse(await readFile(resolve(appRoot, '../../../pnpm-lock.yaml'), 'utf8')));
    // Remove stale assets and any prior successful manifest before rebuilding.
    await rm(piiRuntimeOutput, { recursive: true, force: true });
    await mkdir(piiRuntimeOutput, { recursive: true });
    await build({
      stdin: {
        contents: 'export { Redact } from "@desert-ant-labs/redact"; export * as openmatesLiteRT from "@litertjs/core";',
        resolveDir: resolve(appRoot, '../../packages/ui'), sourcefile: 'openmates-pii-sdk.js',
      },
      outfile: join(piiRuntimeOutput, 'sdk.js'), bundle: true, format: 'esm', platform: 'browser',
      conditions: ['browser'], target: 'es2022', minify: true, sourcemap: false,
      define: { 'import.meta.url': 'globalThis.__openmatesPIISdkURL' },
    });
    await copyFile(join(sdkRoot, 'dist/RedactWeb.wasm'), join(piiRuntimeOutput, 'RedactWeb.wasm'));
    // Single threaded compat avoids subworkers and cross-origin isolation.
    for (const ext of ['js', 'wasm']) await copyFile(join(liteRoot, `wasm/litert_wasm_compat_internal.${ext}`), join(piiRuntimeOutput, `litert_wasm_compat_internal.${ext}`));
    await preparePIIModel();
    const files = {};
    for (const [name, expected] of Object.entries(piiPinnedFiles)) files[name] = verifyPIIAsset(await readFile(join(piiRuntimeOutput, name)), expected, name);
    await copyFile(resolve(appRoot, '../../packages/ui/src/components/enter_message/services/webPIIDetector.worker.js'), join(piiRuntimeOutput, 'worker.js'));
    const worker = await readFile(join(piiRuntimeOutput, 'worker.js'));
    files['worker.js'] = { bytes: worker.byteLength, sha256: createHash('sha256').update(worker).digest('hex') };
    await writeFile(join(piiRuntimeOutput, 'version.json'), JSON.stringify({ sdk: '4.1.0', litert: '2.6.0', model: 'v0.4.0' }));
    await writeFile(join(piiRuntimeOutput, 'integrity.json'), JSON.stringify({ schemaVersion: 1, sdk: '4.1.0', litert: '2.6.0', model: piiModel, files }, null, 2) + '\n');
  })();
  try { return await preparing; } catch (error) { preparing = undefined; throw error; }
}

/** Exact Worker response policy in direct Vite dev and preview, as on Vercel. */
export function piiWorkerHeaders(req, res, next) {
  if (new URL(req.url, 'http://localhost').pathname === `${piiRuntimeBase}worker.js`) {
    res.setHeader('Content-Security-Policy', piiWorkerCSP);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'no-cache, must-revalidate');
  }
  next();
}

export function piiRuntimePlugin() {
  return {
    name: 'openmates-pii-runtime',
    // SvelteKit registers an eager static-file handler in configureServer.
    // Install this policy before that handler can consume worker.js requests.
    enforce: 'pre',
    async buildStart() { await preparePIIRuntime(); },
    configureServer(server) { server.middlewares.use(piiWorkerHeaders); },
    configurePreviewServer(server) { server.middlewares.use(piiWorkerHeaders); },
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await preparePIIRuntime();
