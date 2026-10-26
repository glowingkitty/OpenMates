/** Self-host the pinned browser SDK. No model/text/telemetry fetch runs at build. */
import { createRequire } from 'node:module';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, copyFile, writeFile, readFile, rm } from 'node:fs/promises';
import { build } from 'esbuild';

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const uiRequire = createRequire(resolve(appRoot, '../../packages/ui/package.json'));
export const piiRuntimeOutput = resolve(appRoot, 'static/pii-runtime/redact-4.1.0-litert-2.6.0');
let preparing;

export async function preparePIIRuntime() {
  if (preparing) return preparing;
  preparing = (async () => {
    const sdkRoot = dirname(uiRequire.resolve('@desert-ant-labs/redact'));
    const liteRoot = resolve(dirname(uiRequire.resolve('@litertjs/core')), '..');
    for (const [root, version] of [[sdkRoot, '4.1.0'], [liteRoot, '2.6.0']]) {
      const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
      if (pkg.version !== version) throw new Error('PII runtime dependency version mismatch');
    }
    await mkdir(piiRuntimeOutput, { recursive: true });
    await build({
      stdin: {
        contents: 'export { Redact } from "@desert-ant-labs/redact"; export * as openmatesLiteRT from "@litertjs/core";',
        resolveDir: resolve(appRoot, '../../packages/ui'), sourcefile: 'openmates-pii-sdk.js',
      },
      outfile: join(piiRuntimeOutput, 'sdk.js'), bundle: true, format: 'esm', platform: 'browser',
      conditions: ['browser'], target: 'es2022', minify: true, sourcemap: false,
      // Blob imports keep the original self-hosted WASM URL via the worker.
      define: { 'import.meta.url': 'globalThis.__openmatesPIISdkURL' },
    });
    await copyFile(join(sdkRoot, 'dist/RedactWeb.wasm'), join(piiRuntimeOutput, 'RedactWeb.wasm'));
    // A single-threaded compat WASM works without cross-origin isolation and
    // avoids pulling the three unused LiteRT variants into every deployment.
    for (const ext of ['js', 'wasm']) await copyFile(join(liteRoot, `wasm/litert_wasm_compat_internal.${ext}`), join(piiRuntimeOutput, `litert_wasm_compat_internal.${ext}`));
    await copyFile(resolve(appRoot, '../../packages/ui/src/components/enter_message/services/webPIIDetector.worker.js'), join(piiRuntimeOutput, 'worker.js'));
    await writeFile(join(piiRuntimeOutput, 'version.json'), JSON.stringify({ sdk: '4.1.0', litert: '2.6.0', model: 'v0.4.0' }));
  })();
  try { return await preparing; } catch (error) { preparing = undefined; throw error; }
}

/** Runs for direct Vite dev/preview tests as well as normal application builds. */
export function piiRuntimePlugin() {
  let production = true;
  return {
    name: 'openmates-dev-pii-runtime',
    configResolved(config) { production = config.env.VITE_ENV === 'production'; },
    async buildStart() {
      if (production) await rm(resolve(appRoot, 'static/pii-runtime'), { recursive: true, force: true });
      else await preparePIIRuntime();
    },
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await preparePIIRuntime();
