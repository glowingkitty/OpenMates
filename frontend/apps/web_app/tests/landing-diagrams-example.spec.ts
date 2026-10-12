// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo, Locator } from '@playwright/test';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import { admitLandingExample } from './landing-app-example-admission';
import { getE2EDebugUrl } from './signup-flow-helpers';
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const { test, expect } = require('./helpers/cookie-audit');
const chatId = 'example-online-shop-checkout-flow';
const chat = ALL_EXAMPLE_CHATS.find(example => example.chat_id === chatId);

async function expectCheckoutDiagram(container: Locator): Promise<void> {
  await expect(container.getByTestId('diagram-html-error')).toHaveCount(0);
  await expect(container.getByTestId('diagram-html-loading')).toHaveCount(0);
  const frame = container.frameLocator('[data-testid="diagram-html-frame"]');
  await expect(frame.locator('svg[data-om-diagram]')).toBeVisible();
  const body = frame.locator('body');
  for (const label of ['Shopping Cart', 'Checkout Details', 'Payment Processing', 'Order Confirmation', 'Change Method', 'RETRY PAYMENT']) {
    await expect(body).toContainText(label);
  }
}

// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('diagrams landing example is a completed real HTML diagram', () => {
  expect(chat).toBeDefined();
  expect(Object.entries(landingAppExamples).find(([appId]) => appId === 'diagrams')?.[1]).toBe(chatId);
  const diagram = chat!.embeds.find(embed => embed.type === 'diagram_html');
  expect(diagram).toBeDefined();
  expect(diagram!.content).toContain('app_id: diagrams');
  expect(diagram!.content).toContain('skill_id: html');
  expect(diagram!.content).toContain('status: finished');
  expect(diagram!.content).toContain('html_source:');
});

for (const viewport of ['phone', 'laptop'] as const) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test(`diagrams landing example admits its complete real chat on ${viewport}`, async ({ page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo) => {
    test.setTimeout(90_000);
    expect(chat).toBeDefined();
    await page.setViewportSize(viewport === 'phone' ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
    await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
    const preview = page.getByTestId('diagram-html-preview');
    await expect(preview).toBeVisible({ timeout: 30_000 });
    await expectCheckoutDiagram(preview);
    const fullscreen = await openFullscreen(page, page.getByTestId('embed-preview').first());
    await expect(fullscreen.getByTestId('diagram-html-fullscreen')).toBeVisible();
    await expectCheckoutDiagram(fullscreen);
    await closeFullscreen(page, fullscreen);
    await admitLandingExample(page, request, testInfo, 'diagrams', chat!, viewport);
  });
}
