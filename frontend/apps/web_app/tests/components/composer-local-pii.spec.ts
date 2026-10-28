// playwright-account: not_required reason=isolated_component_preview
import type { BrowserContext, Locator, Page, Request, TestInfo } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { focusComposer } from '../helpers/composer-focus';

const MODEL_URL = '**/pii-runtime/redact-4.1.0-litert-2.6.0/model/redact.tflite';
const MODEL_TIMEOUT = 90_000;
const PREVIEW = '/dev/preview/enter_message/MessageInputPIIPreview?chrome=0&theme=light&background=%23dbeafe&width=680';
const CUSTOMER_DRAFT = 'Our customer Amina Okafor needs help. Her address is 42 Maple Avenue, Bristol BS1 4QA.';
const FALLBACK_NOTICE = 'Enhanced detection is unavailable. Basic checks still detect emails, phone numbers, API keys and other recognized patterns.';
const FIXTURE_IBAN = ['GB82', 'WEST', '123456', '98765432'].join('');

function auditOutboundRequests(context: BrowserContext) {
  const markers = ['amina', 'okafor', 'eleanor', 'whitmore', 'nadia', 'rahman',
    'obsolete.reference@example.net', 'current.reference@example.net', 'case.reference@example.net', FIXTURE_IBAN.toLowerCase()];
  const pending: Promise<void>[] = [];
  const violations: string[] = [];
  const inventory: { host: string; path: string; method: string; bodyKeys: string[] }[] = [];
  let licenseRequests = 0;
  const hasKeys = (value: unknown, keys: string[]) => value !== null && typeof value === 'object'
    && !Array.isArray(value) && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
  const observeRequest = (request: Request) => {
    const index = pending.length;
    pending.push((async () => {
      const url = new URL(request.url());
      const body = request.postData() ?? '';
      const headerValues = Object.values(await request.allHeaders()).join('\n');
      let inspected = `${request.url()}\n${body}\n${headerValues}`;
      try { inspected = decodeURIComponent(inspected); } catch { /* Inspect undecodable requests verbatim. */ }
      if (markers.some(marker => inspected.toLowerCase().includes(marker))) violations.push(`private-marker-in-request-${index}`);
      let payload: unknown;
      try { payload = body ? JSON.parse(body) : undefined; } catch { /* Non-JSON asset requests have no body schema. */ }
      if (url.hostname === 'events.desertant.com') {
        const record = payload as Record<string, unknown> | undefined;
        if (request.method() === 'OPTIONS') {
          if (!['/api/v1/license', '/api/v1/activate'].includes(url.pathname) || body !== '') {
            violations.push('unexpected-sdk-license-preflight');
          }
        } else if (url.pathname === '/api/v1/license') {
          if (request.method() === 'POST') licenseRequests += 1;
          const sdk = record?.sdk as Record<string, unknown> | undefined;
          const app = record?.app as Record<string, unknown> | undefined;
          if (request.method() !== 'POST' || !hasKeys(payload, ['installId', 'model', 'modelVersion', 'sdk', 'platform', 'app'])
            || !hasKeys(record?.sdk, ['name', 'version']) || !hasKeys(record?.app, ['id'])
            || typeof sdk?.name !== 'string' || typeof sdk?.version !== 'string' || typeof app?.id !== 'string'
            || !['installId', 'model', 'modelVersion', 'platform'].every(key => typeof record?.[key] === 'string')
            || record?.platform !== 'web' || record?.model !== 'redact' || record?.modelVersion !== 'v0.4.0') violations.push('unexpected-license-metadata-schema');
        } else if (url.pathname === '/api/v1/activate') {
          if (request.method() !== 'POST' || !hasKeys(payload, ['license']) || typeof record?.license !== 'string') {
            violations.push('unexpected-license-activation-schema');
          }
        } else {
          violations.push('unexpected-sdk-events-endpoint');
        }
      }
      // Queries can hold signed URLs/tokens; opaque path IDs and all body/header
      // values remain private. Only external request shapes enter the receipt.
      if (url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') {
        inventory.push({ host: url.hostname,
          path: url.pathname.split('/').map(segment => segment.length > 48 || /^[a-f0-9-]{24,}$/i.test(segment) ? ':opaque' : segment).join('/'),
          method: request.method(), bodyKeys: payload && typeof payload === 'object' ? Object.keys(payload).sort() : [] });
      }
    })().catch(() => { violations.push(`request-audit-unavailable-${index}`); }));
  };
  context.on('request', observeRequest);
  return async (page: Page, testInfo: TestInfo) => {
    // Keep observing through browser network settling, then drain header reads.
    // This bounds the capture window rather than silently racing late requests.
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    for (let round = 0; round < 3; round += 1) {
      const captured = pending.length;
      await Promise.all(pending.slice());
      if (captured === pending.length) break;
      if (round === 2) violations.push('outbound-audit-did-not-settle');
    }
    context.off('request', observeRequest);
    await testInfo.attach('sanitized-outbound-request-inventory', {
      body: JSON.stringify([...new Map(inventory.map(entry => [JSON.stringify(entry), entry])).values()], null, 2),
      contentType: 'application/json'
    });
    expect(licenseRequests, 'The real worker must exercise SDK licensing for the outbound audit').toBeGreaterThan(0);
    expect(violations, 'Outbound URL, body, and header values must exclude composer PII; licensing must contain only documented metadata').toEqual([]);
  };
}

async function openComposer(page: Page, variant = '') {
  // Isolate anonymous availability from the account-free component behavior.
  const availability = { active: true, can_send_text: true, reason: null };
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
    is_self_hosted: false, payment_enabled: true, server_edition: 'development',
    ai_models_configured: true, anonymous_free_usage: availability
  } }));
  await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability }));
  await page.goto(PREVIEW + (variant ? `&variant=${encodeURIComponent(variant)}` : ''), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  // The canvas mounts before draft restoration finishes. Reuse the production
  // draft fixture's context boundary so its initial restore cannot erase input.
  await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
  await focusComposer(page);
  await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
  return page.getByTestId('message-editor').getByRole('textbox');
}

async function fillDraft(editor: Locator, text: string) {
  await editor.fill(text);
  await expect(editor, 'the initialized composer must retain the complete draft').toHaveText(text);
}

async function expectSemanticHighlight(page: Page, highlight: Locator, type: string) {
  // Stop on a terminal detector failure instead of spending another 90 seconds
  // waiting for a semantic result that this worker can no longer produce.
  let failed = false;
  await expect.poll(async () => {
    failed = await page.evaluate(() => {
      const states = (window as typeof window & { __piiDetectorDiagnostics?: { status: string }[] }).__piiDetectorDiagnostics;
      return states?.at(-1)?.status === 'error';
    });
    if (failed) return true;
    return await highlight.count() === 1 && await highlight.getAttribute('data-pii-type') === type;
  }, { timeout: MODEL_TIMEOUT }).toBe(true);
  if (failed) throw new Error('Enhanced detector entered a terminal failure; see sanitized lifecycle attachment');
  await expect(highlight).toHaveAttribute('data-pii-type', type);
}

test.describe('Local PII composer integration', () => {
  // Retain protocol shapes when an assertion fails, without recording tokens,
  // installation IDs, response values or private input/output text.
  const diagnostics = new WeakMap<Page, { pending: Promise<void>[]; events: unknown[] }>();
  test.beforeEach(async ({ page, context }) => {
    const record = { pending: [] as Promise<void>[], events: [] as unknown[] };
    diagnostics.set(page, record);
    const started = Date.now();
    await page.addInitScript(() => {
      const state = window as typeof window & { __piiWorkerDiagnostics: unknown[] };
      state.__piiWorkerDiagnostics = [];
      window.Worker = new Proxy(window.Worker, { construct(target, args, newTarget) {
        const worker = Reflect.construct(target, args, newTarget) as Worker;
        if (!String(args[0]).includes('/pii-runtime/')) return worker;
        const started = Date.now();
        worker.addEventListener('message', ({ data }) => {
          const kinds = ['progress', 'pii-network', 'pii-storage', 'pii-boundary-violation', 'pii-diagnostic'];
          const event: Record<string, unknown> = { at: Date.now() - started,
            kind: kinds.includes(data?.kind) ? data.kind : 'operation-result', error: data?.error === true };
          if (data?.kind === 'pii-network') {
            const allowed = ['sdk.js', 'RedactWeb.wasm', 'litert_wasm_compat_internal.js', 'litert_wasm_compat_internal.wasm',
              'model/redact.tflite', 'model/redact_tokenizer.bin', 'model/labels.json'];
            const path = typeof data.url === 'string' ? data.url.split('/pii-runtime/redact-4.1.0-litert-2.6.0/')[1] : undefined;
            event.destination = allowed.includes(path) ? path
              : data.url === 'https://events.desertant.com/api/v1/license' ? 'license'
              : data.url === 'https://events.desertant.com/api/v1/activate' ? 'activate' : 'unrecognized';
          }
          if (data?.kind === 'pii-diagnostic') {
            const codes = ['fetch-input', 'fetch-options', 'fetch-credentials', 'fetch-body', 'storage-input', 'transport',
              'csp-connect', 'csp-script', 'csp-worker', 'csp-other', 'worker-sdk-asset', 'worker-sdk-import',
              'worker-runtime-asset', 'worker-runtime-load', 'worker-model-load', 'worker-scan', 'worker-message', 'license-network-rejected',
              'function-construction', 'normalization-input'];
            event.code = codes.includes(data.code) ? data.code : 'unrecognized';
          }
          state.__piiWorkerDiagnostics.push(event);
        });
        return worker;
      } });
    });
    page.on('console', message => {
      const content = message.text();
      if (content.includes('Content Security Policy') || content.includes('content-security-policy')) {
        record.events.push({ event: 'browser-policy-message', at: Date.now() - started,
          directive: ['worker-src', 'connect-src', 'script-src', 'wasm-unsafe-eval', 'unsafe-eval'].filter(value => content.includes(value)) });
      }
    });
    page.on('worker', worker => {
      record.events.push({ event: 'worker-created', at: Date.now() - started });
      worker.on('close', () => record.events.push({ event: 'worker-closed', at: Date.now() - started }));
    });
    context.on('response', response => {
      const url = new URL(response.url());
      if (url.hostname !== 'events.desertant.com') return;
      record.pending.push((async () => {
        const body = await response.json() as Record<string, unknown>;
        const shape = (value: unknown) => value && typeof value === 'object'
          ? Object.fromEntries(Object.entries(value).map(([key, field]) => [key, typeof field])) : typeof value;
        const event: Record<string, unknown> = {
          event: 'license-response', at: Date.now() - started, path: url.pathname,
          status: response.status(), shape: shape(body),
        };
        if (typeof body.token === 'string') {
          const parts = body.token.split('.');
          if (parts.length === 3) {
            event.tokenHeaderShape = shape(JSON.parse(Buffer.from(parts[0], 'base64url').toString()));
            event.tokenClaimsShape = shape(JSON.parse(Buffer.from(parts[1], 'base64url').toString()));
          }
        }
        record.events.push(event);
      })().catch(() => record.events.push({ event: 'license-response-unavailable', at: Date.now() - started })));
    });
  });
  test.afterEach(async ({ page }, testInfo) => {
    const record = diagnostics.get(page);
    if (!record) return;
    await Promise.all(record.pending);
    if (!page.isClosed()) record.events.push({ event: 'worker-message-sequence', data: await page.evaluate(() => {
      const fixture = window as typeof window & { __piiWorkerDiagnostics?: unknown[]; __piiDetectorDiagnostics?: unknown[] };
      return { messages: fixture.__piiWorkerDiagnostics ?? [], states: fixture.__piiDetectorDiagnostics ?? [] };
    }) });
    await testInfo.attach('sanitized-license-and-worker-lifecycle', {
      body: JSON.stringify(record.events, null, 2), contentType: 'application/json',
    });
  });
  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  test('finishes background warmup when anonymous auth initializes after the composer mounts', async ({ page, context }, testInfo) => {
    test.setTimeout(150_000);
    const finishOutboundAudit = auditOutboundRequests(context);
    const resetErrors: string[] = [];
    page.on('console', message => {
      if (message.type() === 'error' && message.text().includes('Private data detection was reset')) resetErrors.push('unhandled-reset');
    });
    const editor = await openComposer(page, 'coldStart');
    // Prove the readiness subscriber itself finishes warming. Typing must not
    // be needed to rescue a worker cancelled by a later store subscriber.
    await expect.poll(() => page.evaluate(() => {
      const states = (window as typeof window & { __piiDetectorDiagnostics?: { status: string }[] }).__piiDetectorDiagnostics;
      return states?.at(-1)?.status;
    }), { timeout: MODEL_TIMEOUT }).toBe('ready');
    await page.evaluate(() => {
      window.dispatchEvent(new Event('appSettingsMemoriesSyncReady'));
      window.dispatchEvent(new Event('appSettingsMemoriesEntrySynced'));
    });
    await fillDraft(editor, CUSTOMER_DRAFT);
    await expectSemanticHighlight(page, page.getByTestId('pii-highlight').filter({ hasText: /Amina/ }), 'PERSON_NAME');
    expect(resetErrors).toEqual([]);
    await finishOutboundAudit(page, testInfo);
  });
  // Downloads and runs the real pinned model; no detector or classification mocks.
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  test('uses the latest draft, preserves exclusions, and classifies while offline after warmup', async ({ page, context }, testInfo) => {
    test.setTimeout(150_000);
    const finishOutboundAudit = auditOutboundRequests(context);
    let releaseModel!: () => void;
    const modelGate = new Promise<void>(resolve => { releaseModel = resolve; });
    let modelRequested = false;
    await context.route(MODEL_URL, async route => {
      modelRequested = true;
      await modelGate;
      await route.continue();
    });
    const editor = await openComposer(page);
    const highlights = page.getByTestId('pii-highlight');
    // Assemble an inert fixture key to avoid resembling a committed credential.
    const fixtureKey = ['sk', 'proj', 'LocalOnlySyntheticFixture0123456789'].join('-');
    const currentDraft = `Key: ${fixtureKey}. ${CUSTOMER_DRAFT} Reply to current.reference@example.net.`;
    const secret = highlights.filter({ hasText: fixtureKey });
    try {
      await fillDraft(editor, `Key: ${fixtureKey}. Our former customer Eleanor Whitmore needs help. Email obsolete.reference@example.net.`);
      await expect.poll(() => modelRequested, { timeout: MODEL_TIMEOUT }).toBe(true);
      await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
      // Full basic checks protect deterministic PII during model initialization.
      await expect(secret).toHaveAttribute('data-pii-type', 'OPENAI_KEY');
      await expect(highlights.filter({ hasText: 'obsolete.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
      await expect(highlights).toHaveCount(2);
      await page.getByTestId('undo-all-btn').click();
      await expect(highlights).toHaveCount(0);
      // The old draft has a pending scan while model initialization is gated.
      await fillDraft(editor, currentDraft);
      await expect(highlights.filter({ hasText: 'current.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
      await expect(secret).toHaveCount(0);
      await expect(highlights.filter({ hasText: /Amina|Eleanor|obsolete.reference/ })).toHaveCount(0);
    } finally {
      releaseModel();
    }
    // Redact may return a complete name/address or individual given-name,
    // surname and street spans. Assert semantic types without imposing grouping.
    const name = highlights.filter({ hasText: /Amina/ });
    const address = highlights.filter({ hasText: /Maple/ });
    await expectSemanticHighlight(page, name, 'PERSON_NAME');
    await expect(address).toHaveAttribute('data-pii-type', 'ADDRESS');
    await expect(highlights.filter({ hasText: 'current.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(secret).toHaveCount(0);
    await expect(highlights.filter({ hasText: /Eleanor|Whitmore|obsolete.reference/ })).toHaveCount(0);
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);

    await name.click();
    await expect(name).toHaveCount(0);
    await fillDraft(editor, `${CUSTOMER_DRAFT} Please reply to case.reference@example.net.`);
    await expect(highlights.filter({ hasText: 'case.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(address).toHaveAttribute('data-pii-type', 'ADDRESS');
    await expect(name).toHaveCount(0);
    await expect(editor).toContainText('Amina Okafor');

    // The native SDK fixture classified only the numeric IBAN suffix as PHONE.
    // Preserve the complete validated regex match when merging semantic spans.
    const ibanDraft = `Our customer Nadia Rahman needs help. Please use bank account ${FIXTURE_IBAN} for the transfer.`;
    await fillDraft(editor, ibanDraft);
    // A model-only name proves the asynchronous semantic merge has completed.
    await expect(highlights.filter({ hasText: /Nadia/ })).toHaveAttribute('data-pii-type', 'PERSON_NAME', { timeout: MODEL_TIMEOUT });
    const iban = highlights.filter({ hasText: /123456|98765432/ });
    await expect(iban).toHaveCount(1);
    await expect(iban).toHaveAttribute('data-pii-type', 'BANK_ACCOUNT');
    await expect(iban).toHaveText(FIXTURE_IBAN);
    await iban.click();
    await expect(iban).toHaveCount(0);
    await fillDraft(editor, `${ibanDraft} Please confirm receipt.`);
    await expect(iban).toHaveCount(0);

    // Keep the mounted app/model; this proves inference without a network,
    // rather than claiming the application can cold-start offline.
    await context.setOffline(true);
    try {
      await fillDraft(editor, 'Our customer Amina Okafor needs help.');
      // The unchanged name remains excluded even when the address is removed.
      await expect(name).toHaveCount(0);
      await fillDraft(editor, 'Our customer Nadia Rahman needs help with her appointment.');
      // A new synthetic name requires fresh model classification offline.
      await expect(highlights.filter({ hasText: /Nadia/ })).toHaveAttribute('data-pii-type', 'PERSON_NAME', { timeout: MODEL_TIMEOUT });
      await expect(highlights.filter({ hasText: /Amina|Okafor|Maple|case.reference/ })).toHaveCount(0);
      await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    } finally {
      await context.setOffline(false);
    }
    // Large pastes keep complete basic protection without starting another
    // semantic pass. Returning to a short draft reuses the healthy warm model.
    await fillDraft(editor, `${'Background context for the request. '.repeat(150)} Our customer Nadia Rahman needs help. Reply to case.reference@example.net.`);
    await expect(highlights.filter({ hasText: 'case.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(highlights.filter({ hasText: /Nadia|Rahman/ })).toHaveCount(0);
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    await fillDraft(editor, 'Our customer Nadia Rahman needs help with her appointment.');
    await expect(highlights.filter({ hasText: /Nadia/ })).toHaveAttribute('data-pii-type', 'PERSON_NAME', { timeout: MODEL_TIMEOUT });
    await finishOutboundAudit(page, testInfo);
  });

  // A deliberately nonresponsive worker verifies the latency guard; the case
  // above independently verifies actual model inference and warm recovery.
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  test('falls back within the scan budget when inference stalls, using one normal notification', async ({ page, context }) => {
    await context.route('**/pii-runtime/redact-4.1.0-litert-2.6.0/worker.js', route => route.fulfill({
      contentType: 'application/javascript',
      body: "self.onmessage = ({data}) => { if (data.kind === 'load') self.postMessage({id: data.id, items: []}); };",
    }));
    const editor = await openComposer(page);
    await fillDraft(editor, 'Our customer Nadia Rahman needs help. Reply to protected.reference@example.net.');
    const highlights = page.getByTestId('pii-highlight');
    await expect(highlights.filter({ hasText: 'protected.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
    const notice = page.getByTestId('notification').filter({ hasText: FALLBACK_NOTICE });
    await expect(notice).toBeVisible({ timeout: 4000 });
    await expect(notice).toHaveCount(1);
    await expect(highlights.filter({ hasText: /Nadia|Rahman/ })).toHaveCount(0);
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    await fillDraft(editor, 'Reply to protected.reference@example.net. New draft after fallback.');
    await expect(highlights.filter({ hasText: 'protected.reference@example.net' })).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(notice).toHaveCount(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  test('keeps basic checks and exclusions during model failure and enhanced retry', async ({ page, context }) => {
    test.setTimeout(150_000);
    // Count actual normal toasts, including ones that auto-dismiss, without
    // changing notification duration or the application's session notice flag.
    await page.addInitScript((noticeText) => {
      const observed = new WeakSet<Element>();
      const fixture = window as typeof window & { piiFallbackNoticeCount: number };
      fixture.piiFallbackNoticeCount = 0;
      new MutationObserver(() => {
        for (const notification of document.querySelectorAll('[data-testid="notification"]')) {
          if (!observed.has(notification) && notification.textContent?.includes(noticeText)) {
            observed.add(notification);
            fixture.piiFallbackNoticeCount += 1;
          }
        }
      }).observe(document, { childList: true, subtree: true, characterData: true });
    }, FALLBACK_NOTICE);
    let failModel = true;
    await context.route(MODEL_URL, route => failModel
      ? route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><html><body>Missing model fixture</body></html>' })
      : route.continue());
    const editor = await openComposer(page);
    await fillDraft(editor, `${CUSTOMER_DRAFT} Reply to keep.reference@example.net or protected.reference@example.net.`);
    const notice = page.getByTestId('notification').filter({ hasText: FALLBACK_NOTICE });
    await expect(notice).toBeVisible({ timeout: MODEL_TIMEOUT });
    await expect(notice).toHaveCount(1);
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    const highlights = page.getByTestId('pii-highlight');
    const excludedEmail = highlights.filter({ hasText: 'keep.reference@example.net' });
    const protectedEmail = highlights.filter({ hasText: 'protected.reference@example.net' });
    await expect(excludedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(protectedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(highlights.filter({ hasText: /Amina/ })).toHaveCount(0);
    await excludedEmail.click();
    await expect(excludedEmail).toHaveCount(0);
    await expect(protectedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await fillDraft(editor, `${CUSTOMER_DRAFT} Reply to keep.reference@example.net or protected.reference@example.net. Updated draft.`);
    await expect(excludedEmail).toHaveCount(0);
    await expect(protectedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect(notice).toHaveCount(1);
    failModel = false;
    const retry = notice.getByRole('button', { name: 'Retry enhanced detection', exact: true });
    await retry.focus();
    await retry.press('Enter');
    await expectSemanticHighlight(page, page.getByTestId('pii-highlight').filter({ hasText: /Amina/ }), 'PERSON_NAME');
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    await expect(excludedEmail).toHaveCount(0);
    await expect(protectedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect.poll(() => page.evaluate(() => (window as typeof window & { piiFallbackNoticeCount: number }).piiFallbackNoticeCount)).toBe(1);
  });
});
