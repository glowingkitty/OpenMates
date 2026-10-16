// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';
import { habitGardenWebApplicationChat } from '../../../packages/ui/src/demo_chats/data/example_chats/habit-garden-web-application';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';

const { test, expect } = require('./helpers/cookie-audit');

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test(`Code landing example admits its real application and screenshot on ${viewport}`, async (
    { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
  ) => {
    test.setTimeout(150_000);
    await page.addInitScript(() => {
      const diagnosticWindow = window as typeof window & {
        codeFullscreenEvents?: Array<{ embedId: string; embedType: string }>;
        codePreviewClicks?: Array<{ target: string; previewClass: string; previewStatus: string }>;
      };
      diagnosticWindow.codeFullscreenEvents = [];
      diagnosticWindow.codePreviewClicks = [];
      document.addEventListener('click', event => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const preview = target.closest('[data-testid="embed-preview"]');
        if (!preview || preview.getAttribute('data-app-id') !== 'code') return;
        diagnosticWindow.codePreviewClicks?.push({
          target: `${target.tagName.toLowerCase()}${target.getAttribute('data-testid') ? `[data-testid="${target.getAttribute('data-testid')}"]` : ''}`,
          previewClass: preview.className,
          previewStatus: preview.getAttribute('data-status') ?? '',
        });
      }, true);
      document.addEventListener('embedfullscreen', event => {
        const detail = (event as CustomEvent<{ embedId?: string; embedType?: string }>).detail;
        diagnosticWindow.codeFullscreenEvents?.push({
          embedId: detail?.embedId ?? '',
          embedType: detail?.embedType ?? '',
        });
      });
    });
    const pageErrors: string[] = [];
    const embedWarnings: string[] = [];
    const previewStartRequests: string[] = [];
    page.on('pageerror', error => pageErrors.push(error.message.slice(0, 300)));
    page.context().on('request', request => {
      if (request.method() === 'POST' && /\/v1\/applications\/[^/]+\/preview\/start(?:\?|$)/.test(request.url())) {
        previewStartRequests.push(request.url());
      }
    });
    page.on('console', message => {
      if (/UnifiedEmbedPreview|ApplicationEmbedPreview|ActiveChat.*fullscreen|GroupRenderer.*fullscreen/i.test(message.text())) {
        embedWarnings.push(message.text().slice(0, 300));
      }
    });
    const chat = habitGardenWebApplicationChat;
    expect(landingAppExamples.code).toBe(chat.chat_id);
    expect(chat.category).toBe('software_development');
    expect(chat.follow_up_suggestions).toHaveLength(6);
    const application = chat.embeds.find(embed => embed.type === 'application');
    expect(application).toBeDefined();
    expect(application!.content).toMatch(
      /latest_screenshot_url: "https:\/\/(?:dev-)?openmates-public-examples\.nbg1\.your-objectstorage\.com\/reviewed-media\/application_preview\/preview\/sha256-[a-f0-9]{64}\.png"/
    );

    // Shared admission checks inline and fullscreen pixels, transcript and mate,
    // follow-up controls, and the same surfaces after a reload.
    try {
      await admitLandingExample(page, request, testInfo, 'code', chat, viewport);
    } catch (error) {
      const diagnostic = await page.evaluate(() => {
        const diagnosticWindow = window as typeof window & {
          codeFullscreenEvents?: Array<{ embedId: string; embedType: string }>;
          codePreviewClicks?: Array<{ target: string; previewClass: string; previewStatus: string }>;
        };
        const events = diagnosticWindow.codeFullscreenEvents ?? [];
        const preview = document.querySelector('[data-testid="application-preview-screenshot-image"]')?.closest('[data-testid="embed-preview"]');
        return {
          events,
          clicks: diagnosticWindow.codePreviewClicks ?? [],
          hash: window.location.hash,
          fullscreenContainerCount: document.querySelectorAll('[data-testid="embed-fullscreen-container"]').length,
          fullscreenOverlayCount: document.querySelectorAll('.unified-embed-fullscreen-overlay').length,
          previewStatus: preview?.getAttribute('data-status'),
          previewDisabled: preview?.getAttribute('aria-disabled'),
        };
      }).catch(() => null);
      await testInfo.attach(`code-fullscreen-diagnostic-${viewport}.json`, {
        body: Buffer.from(JSON.stringify({ diagnostic, pageErrors, embedWarnings }, null, 2)),
        contentType: 'application/json',
      });
      throw error;
    }
    await expect(page.getByTestId('chat-mate-name').first()).toHaveText('Sophia');
    const answer = page.getByTestId('message-assistant').first().getByTestId('message-content').first();
    await expect(answer, 'Svelte runes remain literal inline code after reload').toContainText('$state');
    await expect(answer, 'derived rune remains literal inline code after reload').toContainText('$derived');
    await expect(answer, 'math placeholders must never leak into the public transcript').not.toContainText(/MATH_(?:INLINE|BLOCK)_\d+/);
    expect(previewStartRequests, 'public example viewing must not start a paid application preview').toEqual([]);
  });
}
