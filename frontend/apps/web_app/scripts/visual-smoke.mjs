#!/usr/bin/env node
// Playwright visual smoke helper for deployed OpenMates routes.
// Captures laptop and mobile screenshots without spending Firecrawl credits.
// Automated checks catch hard failures; screenshot review is still required for a pass.
// Use scripts/tests.py for acceptance tests and sessions.py visual-smoke for evidence.

import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const VIEWPORTS = {
  laptop: { width: 1440, height: 1000 },
  mobile: { width: 390, height: 844 },
};
const DEFAULT_KEEP_RUNS = 20;
const DEFAULT_WAIT_MS = 1000;
const MAX_URLS = 10;
const MAX_REPORTED_PROBLEMS = 5;
const MAX_REPORTED_CONSOLE_ERRORS = 3;
const MAX_REPORTED_NETWORK_ERRORS = 5;

const ERROR_PATTERNS = [
  /application error/i,
  /internal server error/i,
  /implementation error/i,
  /cannot read properties of/i,
  /traceback \(most recent call last\)/i,
];

let activeBrowser = null;
let shuttingDown = false;

function usage() {
  console.log(`Usage: node frontend/apps/web_app/scripts/visual-smoke.mjs --url <url> [--url <url>] [--session <id>] [--out <dir>] [--wait-ms <ms>] [--keep-runs <count>] [--assert-visible <selector>] [--reviewed-summary <summary>]`);
}

function parseArgs(argv) {
  const result = {
    urls: [],
    session: '',
    out: '',
    waitMs: DEFAULT_WAIT_MS,
    keepRuns: DEFAULT_KEEP_RUNS,
    assertVisible: [],
    reviewedSummary: '',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === '--help' || arg === '-h') {
      usage();
      process.exit(0);
    }
    if (arg === '--url' && next) {
      result.urls.push(next);
      index += 1;
      continue;
    }
    if (arg === '--session' && next) {
      result.session = next;
      index += 1;
      continue;
    }
    if (arg === '--out' && next) {
      result.out = next;
      index += 1;
      continue;
    }
    if (arg === '--wait-ms' && next) {
      result.waitMs = Number.parseInt(next, 10);
      index += 1;
      continue;
    }
    if (arg === '--keep-runs' && next) {
      result.keepRuns = Number.parseInt(next, 10);
      index += 1;
      continue;
    }
    if (arg === '--assert-visible' && next) {
      result.assertVisible.push(next);
      index += 1;
      continue;
    }
    if (arg === '--reviewed-summary' && next) {
      result.reviewedSummary = next;
      index += 1;
      continue;
    }
    throw new Error(`Unknown or incomplete argument: ${arg}`);
  }
  if (!result.urls.length) {
    throw new Error('At least one --url is required.');
  }
  if (result.urls.length > MAX_URLS) {
    throw new Error(`Refusing to smoke ${result.urls.length} URLs in one run; maximum is ${MAX_URLS}.`);
  }
  if (!Number.isFinite(result.waitMs) || result.waitMs < 0) {
    throw new Error('--wait-ms must be a non-negative integer.');
  }
  if (!Number.isFinite(result.keepRuns) || result.keepRuns < 1) {
    throw new Error('--keep-runs must be a positive integer.');
  }
  return result;
}

async function closeActiveBrowser() {
  const browser = activeBrowser;
  activeBrowser = null;
  if (browser?.isConnected()) {
    await browser.close().catch(() => {});
  }
}

function installShutdownHandlers() {
  const shutdown = (signal) => {
    if (shuttingDown) {
      process.exit(signal === 'SIGINT' ? 130 : 143);
    }
    shuttingDown = true;
    closeActiveBrowser().finally(() => {
      process.exit(signal === 'SIGINT' ? 130 : 143);
    });
  };
  process.once('SIGINT', () => shutdown('SIGINT'));
  process.once('SIGTERM', () => shutdown('SIGTERM'));
}

async function cleanupOldRuns(visualSmokeRoot, keepRuns) {
  const entries = await fs.readdir(visualSmokeRoot, { withFileTypes: true }).catch((error) => {
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  });
  const runs = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    const runDir = path.join(visualSmokeRoot, entry.name);
    const summaryPath = path.join(runDir, 'summary.json');
    const stat = await fs.stat(summaryPath).catch(() => null);
    if (stat) {
      runs.push({ runDir, mtimeMs: stat.mtimeMs });
    }
  }
  runs.sort((left, right) => right.mtimeMs - left.mtimeMs);
  const staleRuns = runs.slice(keepRuns);
  for (const run of staleRuns) {
    await fs.rm(run.runDir, { recursive: true, force: true });
  }
  return staleRuns.map((run) => run.runDir);
}

function slugify(value) {
  return value
    .replace(/^https?:\/\//, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'route';
}

async function collectLayoutSignals(page, assertVisibleSelectors) {
  return page.evaluate((selectors) => {
    function isVisible(element) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number.parseFloat(style.opacity || '1') > 0.01
        && rect.width > 1
        && rect.height > 1;
    }

    function label(element) {
      const tag = element.tagName.toLowerCase();
      const id = element.id ? `#${element.id}` : '';
      const testId = element.getAttribute('data-testid') ? `[data-testid="${element.getAttribute('data-testid')}"]` : '';
      return `${tag}${id}${testId}`;
    }

    const doc = document.documentElement;
    const body = document.body;
    const horizontalOverflowPx = Math.max(
      0,
      Math.max(doc.scrollWidth, body?.scrollWidth || 0) - window.innerWidth
    );
    const brokenImages = Array.from(document.images)
      .filter((image) => isVisible(image) && image.complete && image.naturalWidth === 0)
      .slice(0, 5)
      .map((image) => ({ label: label(image), src: image.currentSrc || image.src || '' }));
    const assertions = selectors.map((selector) => {
      const element = document.querySelector(selector);
      if (!element) {
        return { selector, ok: false, problem: 'missing' };
      }
      const rect = element.getBoundingClientRect();
      if (!isVisible(element)) {
        return { selector, ok: false, problem: 'not visible', rect };
      }
      const outsideViewport = rect.left < -1
        || rect.top < -1
        || rect.right > window.innerWidth + 1
        || rect.bottom > window.innerHeight + 1;
      if (outsideViewport) {
        return { selector, ok: false, problem: 'outside viewport', rect };
      }
      return { selector, ok: true, rect };
    });
    return { horizontalOverflowPx, brokenImages, assertions };
  }, assertVisibleSelectors);
}

async function smokeUrl(browser, url, viewportName, viewport, outDir, waitMs, assertVisibleSelectors) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const responseErrors = [];
  const requestFailures = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      responseErrors.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on('requestfailed', (request) => {
    requestFailures.push(`${request.failure()?.errorText || 'request failed'} ${request.url()}`);
  });

  let status = 0;
  try {
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
    status = response?.status() || 0;
    if (waitMs) {
      await page.waitForTimeout(waitMs);
    }
    const title = await page.title();
    const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
    const screenshot = path.join(outDir, `${slugify(url)}-${viewportName}.png`);
    await page.screenshot({ path: screenshot, fullPage: false });
    const layout = await collectLayoutSignals(page, assertVisibleSelectors);
    const matchedPatterns = ERROR_PATTERNS.filter((pattern) => pattern.test(bodyText)).map((pattern) => pattern.source);
    const problems = [];
    if (status >= 400) {
      problems.push(`HTTP ${status}`);
    }
    if (!bodyText.trim()) {
      problems.push('empty body text');
    }
    if (matchedPatterns.length) {
      problems.push(`matched error text: ${matchedPatterns.join(', ')}`);
    }
    if (pageErrors.length) {
      problems.push(`page errors: ${pageErrors.slice(0, MAX_REPORTED_CONSOLE_ERRORS).join(' | ')}`);
    }
    if (consoleErrors.length) {
      problems.push(`console errors: ${consoleErrors.slice(0, MAX_REPORTED_CONSOLE_ERRORS).join(' | ')}`);
    }
    if (responseErrors.length) {
      problems.push(`HTTP subresource errors: ${responseErrors.slice(0, MAX_REPORTED_NETWORK_ERRORS).join(' | ')}`);
    }
    if (requestFailures.length) {
      problems.push(`request failures: ${requestFailures.slice(0, MAX_REPORTED_NETWORK_ERRORS).join(' | ')}`);
    }
    if (layout.horizontalOverflowPx > 2) {
      problems.push(`horizontal overflow: ${layout.horizontalOverflowPx}px`);
    }
    if (layout.brokenImages.length) {
      problems.push(`broken visible images: ${layout.brokenImages.map((image) => image.label).join(', ')}`);
    }
    const failedAssertions = layout.assertions.filter((assertion) => !assertion.ok);
    if (failedAssertions.length) {
      problems.push(`visible selector assertions failed: ${failedAssertions.map((assertion) => `${assertion.selector} (${assertion.problem})`).join(', ')}`);
    }
    return {
      url,
      viewport: viewportName,
      status,
      title,
      screenshot,
      layout,
      consoleErrors: consoleErrors.slice(0, 5),
      pageErrors: pageErrors.slice(0, 5),
      responseErrors: responseErrors.slice(0, 10),
      requestFailures: requestFailures.slice(0, 10),
      problems,
    };
  } finally {
    await page.close({ runBeforeUnload: false }).catch(() => {});
    await context.close().catch(() => {});
  }
}

function buildEvidenceSummary({ failures, needsScreenshotReview, reviewedSummary }) {
  if (failures.length) {
    const problems = failures.flatMap((record) => record.problems).slice(0, MAX_REPORTED_PROBLEMS);
    return `Playwright visual smoke failed before screenshot review: ${problems.join(' | ')}`;
  }
  if (needsScreenshotReview) {
    return 'Playwright screenshots captured in laptop and mobile viewports. Manual screenshot review is required before recording a pass. Defects: pending. Accepted differences: pending.';
  }
  return reviewedSummary.trim();
}

async function main() {
  installShutdownHandlers();
  const args = parseArgs(process.argv.slice(2));
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const repoRoot = path.resolve(scriptDir, '../../../..');
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const visualSmokeRoot = path.resolve(repoRoot, 'test-results/visual-smoke');
  const usingDefaultOut = !args.out;
  const outDir = usingDefaultOut ? path.join(visualSmokeRoot, timestamp) : path.resolve(repoRoot, args.out);
  await fs.mkdir(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  activeBrowser = browser;
  const records = [];
  try {
    for (const url of args.urls) {
      for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
        records.push(await smokeUrl(browser, url, viewportName, viewport, outDir, args.waitMs, args.assertVisible));
      }
    }
  } finally {
    await closeActiveBrowser();
  }

  const summaryPath = path.join(outDir, 'summary.json');
  const failures = records.filter((record) => record.problems.length > 0);
  const summary = {
    method: 'playwright',
    timestamp: new Date().toISOString(),
    urls: args.urls,
    viewports: Object.keys(VIEWPORTS),
    assertVisible: args.assertVisible,
    retention: usingDefaultOut ? { keepRuns: args.keepRuns, removedRuns: [] } : { customOut: true },
    records,
    result: failures.length ? 'failed' : 'passed',
  };
  await fs.writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  if (usingDefaultOut) {
    summary.retention.removedRuns = await cleanupOldRuns(visualSmokeRoot, args.keepRuns);
    await fs.writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  }

  const needsScreenshotReview = !failures.length && args.session && !args.reviewedSummary.trim();
  if (args.session) {
    const result = failures.length ? 'failed' : needsScreenshotReview ? 'blocked' : 'passed';
    const command = [
      'scripts/sessions.py',
      'visual-smoke',
      '--session',
      args.session,
      '--result',
      result,
      '--method',
      'playwright',
      '--run-id',
      path.relative(repoRoot, summaryPath),
      '--summary',
      buildEvidenceSummary({ failures, needsScreenshotReview, reviewedSummary: args.reviewedSummary }),
    ];
    for (const url of args.urls) {
      command.push('--url', url);
    }
    for (const viewportName of Object.keys(VIEWPORTS)) {
      command.push('--viewport', viewportName);
    }
    for (const record of records) {
      command.push('--screenshot', path.relative(repoRoot, record.screenshot));
    }
    const recorded = spawnSync('python3', command, { cwd: repoRoot, encoding: 'utf8' });
    if (recorded.stdout) {
      process.stdout.write(recorded.stdout);
    }
    if (recorded.stderr) {
      process.stderr.write(recorded.stderr);
    }
    if (recorded.status !== 0) {
      process.exit(recorded.status || 1);
    }
  }

  console.log(`Visual smoke ${summary.result}: ${path.relative(repoRoot, summaryPath)}`);
  for (const record of records) {
    console.log(`- ${record.viewport} ${record.status} ${record.url} screenshot=${path.relative(repoRoot, record.screenshot)}`);
    for (const problem of record.problems) {
      console.log(`  problem: ${problem}`);
    }
  }
  if (failures.length) {
    process.exit(1);
  }
  if (needsScreenshotReview) {
    console.error('Visual smoke screenshots captured; review the laptop and mobile PNGs, then record a passed visual-smoke summary with defects and accepted differences.');
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
