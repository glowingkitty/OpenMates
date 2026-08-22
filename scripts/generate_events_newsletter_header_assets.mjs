#!/usr/bin/env node
/*
 * Generate localized OpenMates Events newsletter header PNGs.
 *
 * The source of truth is the Svelte component at
 * frontend/packages/ui/src/components/newsletter/EventsNewsletterHeader.svelte.
 * This script renders it in a temporary Vite page and screenshots the component
 * with Playwright so email assets stay reproducible and localizable.
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..');
const APP_ROOT = process.env.OPENMATES_EVENTS_HEADER_TMP || '/tmp/opencode/openmates-events-newsletter-header';
const COMPONENT_PATH = path.join(
  REPO_ROOT,
  'frontend/packages/ui/src/components/newsletter/EventsNewsletterHeader.svelte',
);
const UI_STATIC_DIR = path.join(REPO_ROOT, 'frontend/packages/ui/static');
const OUTPUT_DIR = path.join(REPO_ROOT, 'shared/events/assets/newsletter');
const CANVASES = {
  desktop: { width: 1155, height: 322, filenameSuffix: '' },
  mobile: { width: 780, height: 258, filenameSuffix: '-mobile' },
};
const DEFAULT_LANGUAGES = ['en', 'de'];
const DEFAULT_VARIANTS = ['desktop', 'mobile'];

const TEMP_DEPENDENCIES = [
  '@fontsource-variable/lexend-deca@5.2.9',
  '@sveltejs/vite-plugin-svelte@6.2.4',
  'playwright-core@1.60.0',
  'svelte@5.55.7',
  'vite@7.3.6',
];

function parseArgs(argv) {
  const languages = [];
  const variants = [];
  let outDir = OUTPUT_DIR;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--lang') {
      const value = argv[index + 1];
      if (!value || !DEFAULT_LANGUAGES.includes(value)) {
        throw new Error('--lang must be en or de');
      }
      languages.push(value);
      index += 1;
    } else if (arg === '--out-dir') {
      const value = argv[index + 1];
      if (!value) throw new Error('--out-dir requires a path');
      outDir = path.resolve(value);
      index += 1;
    } else if (arg === '--variant') {
      const value = argv[index + 1];
      if (!value || !DEFAULT_VARIANTS.includes(value)) {
        throw new Error('--variant must be desktop or mobile');
      }
      variants.push(value);
      index += 1;
    } else if (arg === '--help' || arg === '-h') {
      console.log('Usage: node scripts/generate_events_newsletter_header_assets.mjs [--lang en|de] [--variant desktop|mobile] [--out-dir <path>]');
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return {
    languages: languages.length ? languages : DEFAULT_LANGUAGES,
    variants: variants.length ? variants : DEFAULT_VARIANTS,
    outDir,
  };
}

function requireFrom(basePath) {
  return createRequire(path.join(basePath, 'package.json'));
}

function canResolve(basePath, packageName) {
  try {
    requireFrom(basePath).resolve(packageName);
    return true;
  } catch {
    return false;
  }
}

function ensureTempDependencies() {
  const requiredPackages = ['vite', '@sveltejs/vite-plugin-svelte', 'svelte', '@fontsource-variable/lexend-deca', 'playwright-core'];
  const rootHasAll = requiredPackages.every((packageName) => canResolve(REPO_ROOT, packageName));
  if (rootHasAll) return REPO_ROOT;

  const tempHasAll = requiredPackages.every((packageName) => canResolve(APP_ROOT, packageName));
  if (tempHasAll) return APP_ROOT;

  if (process.env.OPENMATES_ALLOW_TEMP_NPM_INSTALL !== '1') {
    throw new Error(
      'Missing local Svelte/Vite render dependencies. Install frontend dependencies, or rerun with OPENMATES_ALLOW_TEMP_NPM_INSTALL=1 to install temporary deps under /tmp/opencode.',
    );
  }

  mkdirSync(APP_ROOT, { recursive: true });
  writeFileSync(path.join(APP_ROOT, 'package.json'), '{"type":"module","private":true}\n');
  const install = spawnSync('npm', ['install', '--prefix', APP_ROOT, '--no-audit', '--no-fund', '--silent', ...TEMP_DEPENDENCIES], {
    stdio: 'inherit',
    env: { ...process.env, PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: '1' },
  });
  if (install.status !== 0) {
    throw new Error(`Temporary dependency install failed with exit code ${install.status}`);
  }
  return APP_ROOT;
}

async function importFrom(basePath, packageName) {
  const resolved = requireFrom(basePath).resolve(packageName);
  const imported = await import(pathToFileURL(resolved).href);
  return imported.default ?? imported;
}

function chromiumCandidates() {
  const candidates = [];
  const configured = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (configured) candidates.push(path.resolve(configured));
  const cacheRoot = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(process.env.HOME || '', '.cache/ms-playwright');
  try {
    for (const entry of readdirSync(cacheRoot)) {
      if (!entry.startsWith('chromium-')) continue;
      const chromePath = path.join(cacheRoot, entry, 'chrome-linux', 'chrome');
      const marker = path.join(cacheRoot, entry, 'INSTALLATION_COMPLETE');
      if (existsSync(chromePath) && existsSync(marker)) candidates.push(chromePath);
    }
  } catch {
    // Let Playwright try its default browser lookup below.
  }
  return candidates
    .filter((candidate) => existsSync(candidate))
    .sort((left, right) => statSync(right).mtimeMs - statSync(left).mtimeMs);
}

function writeTemporaryApp() {
  const srcDir = path.join(APP_ROOT, 'src');
  mkdirSync(srcDir, { recursive: true });
  writeFileSync(
    path.join(APP_ROOT, 'index.html'),
    '<!doctype html><html><head><meta charset="utf-8"><title>Events Newsletter Header</title></head><body><div id="app"></div><script type="module" src="/src/main.ts"></script></body></html>\n',
  );
  const componentImport = `/@fs/${COMPONENT_PATH.replace(/\\/g, '/')}`;
  writeFileSync(
    path.join(srcDir, 'main.ts'),
    `import '@fontsource-variable/lexend-deca/index.css';\nimport { mount } from 'svelte';\nimport EventsNewsletterHeader from '${componentImport}';\nimport './page.css';\n\nconst params = new URLSearchParams(window.location.search);\nconst language = params.get('lang') === 'de' ? 'de' : 'en';\nconst variant = params.get('variant') === 'mobile' ? 'mobile' : 'desktop';\nconst target = document.getElementById('app');\nif (!target) throw new Error('Missing #app target');\nmount(EventsNewsletterHeader, { target, props: { language, variant } });\n`,
  );
  writeFileSync(
    path.join(srcDir, 'page.css'),
    "html, body, #app { margin: 0; overflow: hidden; background: transparent; }\nbody { font-family: 'Lexend Deca Variable', 'Lexend Deca', Arial, Helvetica, sans-serif; }\n",
  );
}

async function main() {
  const { languages, variants, outDir } = parseArgs(process.argv.slice(2));
  if (!existsSync(COMPONENT_PATH)) throw new Error(`Missing Svelte component: ${COMPONENT_PATH}`);
  const depsRoot = ensureTempDependencies();
  const [{ createServer }, { svelte }, { chromium }] = await Promise.all([
    importFrom(depsRoot, 'vite'),
    importFrom(depsRoot, '@sveltejs/vite-plugin-svelte'),
    importFrom(depsRoot, 'playwright-core'),
  ]);

  writeTemporaryApp();
  mkdirSync(outDir, { recursive: true });

  const server = await createServer({
    root: APP_ROOT,
    configFile: false,
    publicDir: UI_STATIC_DIR,
    plugins: [svelte()],
    server: {
      host: '127.0.0.1',
      port: 0,
      fs: { allow: [REPO_ROOT, APP_ROOT] },
    },
    logLevel: 'warn',
  });

  await server.listen();
  const address = server.httpServer?.address();
  const port = typeof address === 'object' && address ? address.port : 0;
  if (!port) throw new Error('Vite server did not expose a port');

  const candidates = chromiumCandidates();
  const launchOptions = { headless: true };
  if (candidates[0]) launchOptions.executablePath = candidates[0];
  const browser = await chromium.launch(launchOptions);

  try {
    const page = await browser.newPage({ viewport: { width: CANVASES.desktop.width, height: CANVASES.desktop.height }, deviceScaleFactor: 1 });
    for (const language of languages) {
      for (const variant of variants) {
        const canvas = CANVASES[variant];
        await page.setViewportSize({ width: canvas.width, height: canvas.height });
        const outputPath = path.join(outDir, `events-newsletter-header${canvas.filenameSuffix}_${language}.png`);
        await page.goto(`http://127.0.0.1:${port}/?lang=${language}&variant=${variant}`, { waitUntil: 'networkidle' });
        const header = page.locator('[data-testid="events-newsletter-header"]');
        await header.waitFor({ state: 'visible', timeout: 15_000 });
        const box = await header.boundingBox();
        if (!box || Math.round(box.width) !== canvas.width || Math.round(box.height) !== canvas.height) {
          throw new Error(`Unexpected header bounds for ${language}/${variant}: ${JSON.stringify(box)}`);
        }
        await header.screenshot({ path: outputPath, omitBackground: false });
        console.log(`${path.relative(REPO_ROOT, outputPath)} (${canvas.width}x${canvas.height})`);
      }
    }
  } finally {
    await browser.close();
    await server.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
