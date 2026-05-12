#!/usr/bin/env node
// Apple embed visual QA capture driver.
// Captures deployed Svelte /dev/preview/embeds pages with an ephemeral
// Playwright CLI, then optionally compares them with simulator screenshots.
//
// This intentionally never starts the web app locally. The default baseline is
// app.dev.openmates.org, matching the Apple embed parity workflow.

import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');

function parseArgs(argv) {
  const options = {
    baseUrl: 'https://app.dev.openmates.org',
    out: path.join(repoRoot, 'test-results', 'apple-embed-visual'),
    apps: ['web', 'images', 'travel', 'code'],
    theme: 'dark',
    viewport: '402,874',
    iosScreenshots: {},
    webCrops: {},
    iosCrops: {},
    captureOnly: false
  };

  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index];
    switch (arg) {
      case '--base-url':
        options.baseUrl = next();
        break;
      case '--out':
        options.out = path.resolve(next());
        break;
      case '--apps':
        options.apps = next().split(',').map((app) => app.trim()).filter(Boolean);
        break;
      case '--theme':
        options.theme = next();
        break;
      case '--viewport':
        options.viewport = next().replace('x', ',');
        break;
      case '--ios-web':
        options.iosScreenshots.web = path.resolve(next());
        break;
      case '--ios-images':
        options.iosScreenshots.images = path.resolve(next());
        break;
      case '--ios-travel':
        options.iosScreenshots.travel = path.resolve(next());
        break;
      case '--ios-code':
        options.iosScreenshots.code = path.resolve(next());
        break;
      case '--web-web-crop':
        options.webCrops.web = next();
        break;
      case '--web-images-crop':
        options.webCrops.images = next();
        break;
      case '--web-travel-crop':
        options.webCrops.travel = next();
        break;
      case '--web-code-crop':
        options.webCrops.code = next();
        break;
      case '--ios-web-crop':
        options.iosCrops.web = next();
        break;
      case '--ios-images-crop':
        options.iosCrops.images = next();
        break;
      case '--ios-travel-crop':
        options.iosCrops.travel = next();
        break;
      case '--ios-code-crop':
        options.iosCrops.code = next();
        break;
      case '--capture-only':
        options.captureOnly = true;
        break;
      case '--help':
      case '-h':
        printUsage();
        process.exit(0);
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return options;
}

function printUsage() {
  console.log(`Usage:
  node scripts/apple_embed_visual_qa.mjs [options]

Options:
  --base-url URL             Baseline host (default: https://app.dev.openmates.org)
  --out DIR                  Artifact directory (default: test-results/apple-embed-visual)
  --apps web,images,travel,code
                              Apps to capture
  --theme dark|light         Browser color scheme (default: dark)
  --viewport 402x874         Browser viewport (default: 402x874)
  --ios-web PATH             Simulator screenshot for web comparison
  --ios-images PATH          Simulator screenshot for images comparison
  --ios-travel PATH          Simulator screenshot for travel comparison
  --ios-code PATH            Simulator screenshot for code comparison
  --web-*-crop x,y,w,h       Crop applied to the matching web baseline screenshot
  --ios-*-crop x,y,w,h       Crop applied to the matching iOS screenshot
  --capture-only             Skip comparisons even if iOS screenshots are passed
`);
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: repoRoot, encoding: 'utf8' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stderr || result.stdout}`);
  }
  return result.stdout;
}

function captureWebScreenshot({ app, url, outputPath, options }) {
  run('pnpm', [
    'dlx',
    'playwright@1.49.0',
    'screenshot',
    '--browser',
    'chromium',
    '--viewport-size',
    options.viewport,
    '--color-scheme',
    options.theme,
    '--wait-for-selector',
    '[data-testid="skill-section"]',
    '--wait-for-timeout',
    '3000',
    '--full-page',
    url,
    outputPath
  ]);
}

function runCompare({ app, webScreenshot, iosScreenshot, webCrop, iosCrop, outputDirectory }) {
  const args = [
    path.join(repoRoot, 'scripts', 'apple_embed_visual_compare.swift'),
    '--web',
    webScreenshot,
    '--ios',
    iosScreenshot,
    '--out',
    outputDirectory,
    '--name',
    app
  ];
  if (webCrop) {
    args.push('--web-crop', webCrop);
  }
  if (iosCrop) {
    args.push('--ios-crop', iosCrop);
  }
  return JSON.parse(run('swift', args));
}

function main() {
  const options = parseArgs(process.argv);
  mkdirSync(options.out, { recursive: true });

  const [viewportWidth, viewportHeight] = options.viewport.split(',');
  const report = [
    '# Apple Embed Visual QA',
    '',
    `Baseline: ${options.baseUrl}`,
    `Viewport: ${viewportWidth}x${viewportHeight}`,
    `Theme: ${options.theme}`,
    ''
  ];

  for (const app of options.apps) {
    const appOut = path.join(options.out, app);
    mkdirSync(appOut, { recursive: true });

    const url = new URL(`/dev/preview/embeds/${app}`, options.baseUrl).toString();
    const webScreenshot = path.join(appOut, `${app}-web-full.png`);
    captureWebScreenshot({ app, url, outputPath: webScreenshot, options });

    report.push(`## ${app}`);
    report.push('');
    report.push(`- Web page: ${url}`);
    report.push(`- Web screenshot: ${path.relative(repoRoot, webScreenshot)}`);

    const iosScreenshot = options.iosScreenshots[app];
    if (iosScreenshot && !options.captureOnly) {
      const metrics = runCompare({
        app,
        webScreenshot,
        iosScreenshot,
        webCrop: options.webCrops[app],
        iosCrop: options.iosCrops[app],
        outputDirectory: appOut
      });
      report.push(`- iOS screenshot: ${iosScreenshot}`);
      report.push(`- Mismatch: ${metrics.mismatchPercent.toFixed(4)}%`);
      report.push(`- Average delta: ${metrics.averageDeltaPercent.toFixed(4)}%`);
      report.push(`- Side-by-side: ${path.relative(repoRoot, metrics.sideBySide)}`);
      report.push(`- Diff: ${path.relative(repoRoot, metrics.diff)}`);
    } else {
      report.push('- Comparison: skipped; pass an iOS screenshot path to compare.');
    }
    report.push('');
  }

  const reportPath = path.join(options.out, 'report.md');
  writeFileSync(reportPath, `${report.join('\n')}\n`);
  console.log(`Wrote ${reportPath}`);

  for (const app of options.apps) {
    const metricsPath = path.join(options.out, app, `${app}-metrics.json`);
    try {
      const metrics = JSON.parse(readFileSync(metricsPath, 'utf8'));
      console.log(`${app}: mismatch=${metrics.mismatchPercent.toFixed(4)}%, averageDelta=${metrics.averageDeltaPercent.toFixed(4)}%`);
    } catch {
      // Capture-only runs do not produce metrics.
    }
  }
}

try {
  main();
} catch (error) {
  console.error(error);
  process.exit(1);
}
