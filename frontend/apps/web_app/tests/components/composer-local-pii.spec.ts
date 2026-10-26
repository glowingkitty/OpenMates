// playwright-account: not_required reason=isolated_component_preview
import type { BrowserContext, Locator, Page, Request, TestInfo } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { focusComposer } from '../helpers/composer-focus';

const MODEL_URL = 'https://huggingface.co/desert-ant-labs/redact/resolve/v0.4.0/redact.tflite';
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

async function openComposer(page: Page) {
  // Isolate anonymous availability from the account-free component behavior.
  const availability = { active: true, can_send_text: true, reason: null };
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
    is_self_hosted: false, payment_enabled: true, server_edition: 'development',
    ai_models_configured: true, anonymous_free_usage: availability
  } }));
  await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability }));
  await page.goto(PREVIEW, { waitUntil: 'domcontentloaded' });
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

test.describe('Local PII composer integration', () => {
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
    await expect(name).toHaveAttribute('data-pii-type', 'PERSON_NAME', { timeout: MODEL_TIMEOUT });
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
    await finishOutboundAudit(page, testInfo);
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
    await context.route(MODEL_URL, route => failModel ? route.abort('failed') : route.continue());
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
    await expect(page.getByTestId('pii-highlight').filter({ hasText: /Amina/ }))
      .toHaveAttribute('data-pii-type', 'PERSON_NAME', { timeout: MODEL_TIMEOUT });
    await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
    await expect(excludedEmail).toHaveCount(0);
    await expect(protectedEmail).toHaveAttribute('data-pii-type', 'EMAIL');
    await expect.poll(() => page.evaluate(() => (window as typeof window & { piiFallbackNoticeCount: number }).piiFallbackNoticeCount)).toBe(1);
  });
});
