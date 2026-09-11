import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('settings and history opening do not resize the chat on every animation frame', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto('/#chat-id=example-ai-workshops-meetups-berlin');
  await expect(page.getByTestId('chat-history-container')).toBeVisible();
  for (const name of ['Open settings menu', 'Toggle menu']) {
    const button = page.getByRole('button', { name, exact: true });
    const measure = async (control = button) => control.evaluate(async (element: HTMLElement) => {
      const chat = document.querySelector('[data-testid="chat-history-container"]')!;
      const widths: number[] = [];
      element.click();
      const start = performance.now();
      await new Promise<void>((resolve) => {
        function sample(now: number) {
          widths.push(Math.round(chat.getBoundingClientRect().width));
          if (now - start < 450) requestAnimationFrame(sample); else resolve();
        }
        requestAnimationFrame(sample);
      });
      return { widths: [...new Set(widths)], connected: chat.isConnected };
    });
    const opening = await measure();
    expect(opening.connected).toBe(true);
    expect(opening.widths.length).toBeLessThanOrEqual(2);
    const close = name === 'Open settings menu'
      ? page.getByRole('button', { name: 'Close settings menu', exact: true })
      : page.locator('.sidebar').getByRole('button', { name: 'Close', exact: true });
    const closing = await measure(close);
    expect(closing.connected).toBe(true);
    expect(closing.widths.length).toBeLessThanOrEqual(2);
  }
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('fullscreen pending frame gives identity without flashing visible Loading text', async ({ page }) => {
  const props = { data: { embedType: 'app-skill-use', decodedContent: { app_id: 'web', skill_id: 'search', query: 'A specific search', provider: 'Brave Search' } }, failed: false };
  await page.goto(`/dev/preview/embeds/EmbedFullscreenLoading?chrome=0&props=${encodeURIComponent(JSON.stringify(props))}`);
  const frame = page.getByTestId('embed-fullscreen-loading');
  await expect(frame).toBeVisible();
  await expect(frame).toContainText('A specific search');
  await expect(frame).toContainText('Brave Search');
  await expect(frame.getByTestId('embed-minimize')).toBeVisible();
  await expect(frame.getByRole('status')).toHaveCSS('clip-path', 'inset(50%)');
  await expect(frame.locator('p')).toHaveCount(0);
  await expect(frame.locator('.orb')).toHaveCount(0);
  await expect(frame.locator('.header-center')).toHaveCSS('animation-name', 'none');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('result views hide invalid sources and render date-only calendar entries', async ({ page }) => {
  const open = async (embedRefs: string[], sourceRefs: string[] = []) => {
    const props = { id: 'eligibility-check', embedRefs, sourceRefs, highlightRefs: [] };
    await page.goto(`/dev/preview/embeds/EmbedsMapView?chrome=0&props=${encodeURIComponent(JSON.stringify(props))}`);
    await expect(page.getByTestId('embeds-map-view-resolution')).toHaveAttribute('data-loading', 'false');
  };
  await open(['preview-invalid-entry']);
  await expect(page.getByTestId('results-view-admin-error')).toHaveCount(0);
  await expect(page.locator('.results-view-mount')).toBeHidden();
  await expect(page.getByTestId('embeds-map-view')).toHaveCount(0);
  await open([], ['preview-missing-source']);
  await expect(page.getByTestId('embeds-map-view')).toHaveCount(0);
  await open(['preview-date-only']);
  await expect(page.getByTestId('embeds-results-view-calendar-date-only')).toContainText('Date-only event');
  await expect(page.getByTestId('embeds-map-view-map')).toHaveCount(0);
  await expect(page.getByTestId('embeds-results-view-calendar-item')).toHaveCount(0);
  await expect(page.locator('.calendar-time-column, .calendar-items')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('unresolved fullscreen identity never renders a generic orb banner', async ({ page }) => {
  const props = { data: { embedType: 'app-skill-use' }, failed: false };
  await page.goto(`/dev/preview/embeds/EmbedFullscreenLoading?chrome=0&props=${encodeURIComponent(JSON.stringify(props))}`);
  const frame = page.getByTestId('embed-fullscreen-loading');
  await expect(frame).toBeVisible();
  await expect(frame.locator('.embed-header, .orb')).toHaveCount(0);
  await expect(frame.getByTestId('embed-minimize')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('inline links forward their badge identity and mount into the already-open pane', async ({ page }) => {
  await page.goto('/#chat-id=example-ai-workshops-meetups-berlin');
  const link = page.getByRole('link', { name: 'Event Details & RSVP', exact: true }).first();
  await expect(link).toBeVisible();
  const identity = page.evaluate(() => new Promise<{ appId?: string; title?: string }>((resolve) => {
    document.addEventListener('embedfullscreen', (event) => {
      const detail = (event as CustomEvent).detail;
      resolve({ appId: detail.attrs?.appId, title: detail.attrs?.title });
    }, { once: true });
  }));
  await link.click();
  expect((await identity).appId).toBe('events');
  const pane = page.getByTestId('embed-fullscreen-container');
  const viewer = pane.locator('.unified-embed-fullscreen-overlay.host-presented').first();
  await expect(viewer).toBeVisible();
  await expect(viewer).toHaveCSS('transform', 'none');
  await expect(viewer).toHaveCSS('transition-duration', '0s');
  await expect(viewer.locator('.orb')).toHaveCount(0);
});
