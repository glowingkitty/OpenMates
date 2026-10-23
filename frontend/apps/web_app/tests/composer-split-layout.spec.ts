// playwright-account: required reason=real_chat_embed_split_layout
import { expect, test } from './helpers/cookie-audit';
import { createSignupLogger, getE2EDebugUrl } from './signup-flow-helpers';
import { loginToTestAccount } from './helpers/chat-test-helpers';
import { waitForComponentMotion } from './helpers/component-preview';

const CHAT_ID = 'example-ai-workshops-meetups-berlin';
const EMBED_ID = '7512b6cf-f568-4197-a008-1f0aea7431b6';
const EVENT_TITLE = 'OpenClaw Anonymous Berlin #9';

// contract-test: direct surface=gui.web assertions=message-input.suggestions.contextual,message-input.layout.responsive-parity,message-input.actions.visibility,apps.results.shared-fullscreen
test('keeps the composer and search cards contained beside an open embed', async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.addInitScript(() => localStorage.setItem('theme_mode', 'dark'));
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  await loginToTestAccount(page, createSignupLogger('COMPOSER_SPLIT_LAYOUT'));

  // Open the result in its owning chat. Composer search navigation is covered
  // separately by composer-embed-open.spec.ts.
  await page.goto(getE2EDebugUrl(`/#chat-id=${CHAT_ID}`), { waitUntil: 'domcontentloaded' });
  const chat = page.getByTestId('active-chat-container');
  await expect(chat).toHaveAttribute('data-current-chat-id', CHAT_ID, { timeout: 30000 });
  await page.goto(getE2EDebugUrl(`/#chat-id=${CHAT_ID}&embed-id=${EMBED_ID}`), { waitUntil: 'domcontentloaded' });
  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 30000 });
  await expect(fullscreen).toContainText(EVENT_TITLE);
  await waitForComponentMotion(fullscreen);

  const field = page.getByTestId('message-field');
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  const expand = page.getByTestId('message-expand-button');
  await expect(field).toBeVisible();
  await expect(expand).toHaveCount(0);
  const background = await field.evaluate(element => getComputedStyle(element).backgroundColor);
  await expect(fullscreen.getByTestId('apps-request-composer')).toHaveCSS('background-color', background);

  await editor.fill('s');
  await waitForComponentMotion(field);
  await expect(expand).toHaveCount(0);
  const actions = page.getByTestId('action-buttons');
  const actionWidth = await actions.evaluate(element => element.clientWidth);
  const label = page.getByTestId('composer-model-selector-label');
  if (actionWidth <= 544) await expect(label).toBeHidden();
  else await expect(label).toBeVisible();
  await expect(page.getByTestId('composer-send-button')).toBeInViewport();
  await expect.poll(() => field.evaluate(element => {
    const field = element.getBoundingClientRect();
    const send = element.querySelector('[data-testid="composer-send-button"]')!.getBoundingClientRect();
    const selector = element.querySelector('[data-testid="composer-model-selector"]')!.getBoundingClientRect();
    const speech = element.querySelector('[data-testid="assistant-speech-toggle"]')!.getBoundingClientRect();
    const mic = element.querySelector('[data-testid="record-audio-button"]')!.getBoundingClientRect();
    return send.right <= field.right && send.left >= mic.right && selector.right <= speech.left;
  })).toBe(true);

  await editor.fill(EVENT_TITLE);
  const suggestions = page.getByTestId('chat-search-suggestions');
  await expect(suggestions).toBeVisible({ timeout: 30000 });
  const card = suggestions.getByTestId('recent-embed-search-result').filter({ hasText: EVENT_TITLE }).first();
  await expect(card).toBeVisible();
  await expect(suggestions.locator('.chat-result-wrapper:has(.embed-result-card) .card-date')).toHaveCount(0);
  await expect.poll(() => card.evaluate(element => {
    const card = element.getBoundingClientRect();
    const strip = element.closest('[data-testid="chat-search-suggestions"]')!.getBoundingClientRect();
    return card.left >= strip.left && card.right <= strip.right;
  })).toBe(true);
  await expect(chat).toHaveAttribute('data-current-chat-id', CHAT_ID);

  await editor.fill('');
  await fullscreen.getByTestId('embed-header-title').click();
  await expect(field).toHaveAttribute('data-focused', 'false');
  await expect(expand).toHaveCount(0);
});
