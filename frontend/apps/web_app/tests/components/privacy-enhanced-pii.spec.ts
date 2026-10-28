// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { focusComposer } from '../helpers/composer-focus';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ANONYM_PATHS = [...readFileSync(resolve(__dirname, '../../../../packages/ui/static/icons/anonym.svg'), 'utf8')
  .matchAll(/<path\s[^>]*d="([^"]+)"/g)].map(match => match[1]);

const PRIVACY = '/dev/preview/settings/privacy/SettingsHidePersonalDataPreview?chrome=0&theme=light&background=%23dbeafe&width=680';
const COMPOSER = '/dev/preview/enter_message/MessageInputPIIPreview?chrome=0&theme=light&background=%23dbeafe&width=680';
const WORKER = '/pii-runtime/redact-4.1.0-litert-2.6.0/worker.js';

async function mockLocalAvailability(page: import('@playwright/test').Page) {
  await page.route('**/v1/auth/methods', route => route.fulfill({ json: {
    has_passkey: false, has_password: false, has_2fa: false,
  } }));
  const availability = { active: true, can_send_text: true, reason: null };
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
    is_self_hosted: false, payment_enabled: true, server_edition: 'development',
    ai_models_configured: true, anonymous_free_usage: availability,
  } }));
  await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability }));
}

// contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.provider-disclosure
test('persists enhanced opt-out through reload and keeps basic composer checks without starting the model', async ({ page, context }) => {
  test.setTimeout(90000);
  let workerRequests = 0;
  let vendorRequests = 0;
  context.on('request', request => {
    if (new URL(request.url()).pathname === WORKER) workerRequests += 1;
    if (new URL(request.url()).hostname === 'events.desertant.com') vendorRequests += 1;
  });
  await mockLocalAvailability(page);
  await page.goto(PRIVACY);
  await waitForComponentPreview(page);
  const row = page.getByTestId('enhanced-personal-data-protection');
  const toggle = row.getByTestId('enhanced-personal-data-protection-toggle');
  const input = row.locator('input[type="checkbox"]');
  await expect(row).toContainText('Enhanced personal data protection');
  await expect(input).toBeEnabled();
  await expect(input).toBeChecked();
  for (const id of ['personal-data-master-protection', 'enhanced-personal-data-protection']) {
    const icon = page.getByTestId(id).locator('span').first();
    await expect.poll(() => icon.evaluate(async element => {
      const mask = getComputedStyle(element, '::after').maskImage;
      const url = /^url\(["']?(.*?)["']?\)$/.exec(mask)?.[1];
      if (!url) return [];
      const svg = new DOMParser().parseFromString(await (await fetch(url)).text(), 'image/svg+xml');
      return [...svg.querySelectorAll('path')].map(path => path.getAttribute('d'));
    })).toEqual(ANONYM_PATHS);
    const bounds = await icon.boundingBox();
    expect(bounds && bounds.width > 0 && bounds.height > 0).toBeTruthy();
  }
  await expect(page.getByTestId('pii-model-disclosure')).toContainText('licensing');
  await expect(page.getByTestId('pii-provider-privacy')).toHaveAttribute('href', 'https://desertant.com/privacy/');
  await expect(page.getByTestId('pii-model-attribution')).toHaveAttribute('href', 'https://desertant.com');
  await toggle.hover();
  await toggle.focus();
  await toggle.press('Enter');
  await expect(input).not.toBeChecked();
  await page.reload();
  await waitForComponentPreview(page);
  await expect(input).toBeEnabled();
  await expect(input).not.toBeChecked();
  await expect(page.getByTestId('pii-model-attribution')).toBeVisible();
  const box = await row.boundingBox();
  const disclosureBox = await page.getByTestId('pii-model-disclosure').boundingBox();
  expect(box && box.width > 400 && box.height > 0).toBeTruthy();
  expect(disclosureBox && disclosureBox.width > 400 && disclosureBox.y >= box!.y + box!.height).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('privacy-enhanced-off.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileRow = await row.boundingBox();
  const mobileDisclosure = await page.getByTestId('pii-model-disclosure').boundingBox();
  expect(mobileRow && mobileRow.width > 280).toBeTruthy();
  expect(mobileDisclosure && mobileDisclosure.width > 280 && mobileDisclosure.y >= mobileRow!.y + mobileRow!.height).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('privacy-enhanced-off-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto(COMPOSER);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
  await focusComposer(page);
  const editor = page.getByTestId('message-editor').getByRole('textbox');
  await editor.fill('Our customer Amina Okafor lives at 42 Maple Avenue. Email private.reference@example.net.');
  await expect(page.getByTestId('pii-highlight').filter({ hasText: 'private.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
  await expect(page.getByTestId('pii-highlight').filter({ hasText: /Amina|Maple/ })).toHaveCount(0);
  await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
  expect(workerRequests).toBe(0);
  expect(vendorRequests).toBe(0);
});

// contract-test: direct surface=gui.web assertions=pii.web.licensing-egress-boundary
test('served worker CSP blocks native fetch, XHR, script imports and nested workers before transmission', async ({ page, context }) => {
  const canary = 'pii-worker-network-denial-fixture';
  let forbiddenRequests = 0;
  await context.route(`**/*${canary}*`, route => {
    forbiddenRequests += 1;
    return route.fulfill({ contentType: 'application/javascript', body: '/* must not be fetched */' });
  });
  await context.route(`**${WORKER}`, async route => {
    const response = await route.fetch();
    const headers = response.headers();
    expect(headers['content-security-policy']).toContain("connect-src 'none'");
    expect(headers['content-security-policy']).toContain("script-src blob: 'wasm-unsafe-eval'");
    expect(headers['content-security-policy']).toContain("worker-src 'none'");
    delete headers['content-length'];
    delete headers['content-encoding'];
    // Deliberately replace trusted code to prove the browser policy still
    // prevents direct networking when no JavaScript fetch wrapper is present.
    await route.fulfill({ response, headers, body: `
      self.onmessage = async ({data}) => {
        if (data.kind !== 'probe') { if (data.id) self.postMessage({id:data.id,items:[]}); return; }
        const url = new URL('/${canary}', self.location.origin).href;
        const blocked = {};
        try { await fetch(url); blocked.fetch = false; } catch { blocked.fetch = true; }
        blocked.xhr = await new Promise(resolve => {
          try { const xhr = new XMLHttpRequest(); xhr.open('GET', url); xhr.onload=()=>resolve(false); xhr.onerror=()=>resolve(true); xhr.send(); }
          catch { resolve(true); }
        });
        try { importScripts(url); blocked.importScripts = false; } catch { blocked.importScripts = true; }
        blocked.worker = await new Promise((resolve, reject) => {
          try {
            const nested = new Worker(url);
            const timeout = setTimeout(() => { nested.terminate(); reject(new Error('Nested worker policy result timed out')); }, 3000);
            nested.onerror = event => { event.preventDefault(); clearTimeout(timeout); nested.terminate(); resolve(true); };
            nested.onmessage = () => { clearTimeout(timeout); nested.terminate(); resolve(false); };
          } catch { resolve(true); }
        });
        self.postMessage({kind:'probe-result',blocked});
      };
    ` });
  });
  await mockLocalAvailability(page);
  await page.goto(COMPOSER);
  await waitForComponentPreview(page);
  const result = await page.evaluate((url) => new Promise((resolve, reject) => {
    const worker = new Worker(url);
    const timeout = setTimeout(() => { worker.terminate(); reject(new Error('Worker CSP probe timed out')); }, 5000);
    worker.onmessage = ({ data }) => { if (data.kind === 'probe-result') { clearTimeout(timeout); worker.terminate(); resolve(data.blocked); } };
    worker.onerror = () => { clearTimeout(timeout); worker.terminate(); reject(new Error('Worker CSP probe failed to execute')); };
    worker.postMessage({ kind: 'probe' });
  }), WORKER);
  expect(result).toEqual({ fetch: true, xhr: true, importScripts: true, worker: true });
  expect(forbiddenRequests).toBe(0);
});
