import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);

// contract-test: direct surface=gui.web assertions=message-input.layout.responsive-parity,apps.results.shared-fullscreen
test('embedded followup matches the regular composer background in both themes', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const theme of ['light', 'dark']) {
    await page.goto(`/dev/preview/enter_message/MessageInput?chrome=0&theme=${theme}&width=390`);
    await waitForComponentPreview(page);
    const background = await page.getByTestId('message-field').evaluate(element => getComputedStyle(element).backgroundColor);
    await page.goto(`/dev/preview/apps/AppsRequestComposer?chrome=0&theme=${theme}&width=390&variant=embed`);
    await waitForComponentPreview(page);
    const composer = page.getByTestId('apps-request-composer');
    await expect(composer).toHaveCSS('background-color', background);
    await page.getByTestId('apps-request-textarea').fill('Ask about this result');
    await expect(composer).toHaveClass(/focused/);
    await expect(composer).toHaveCSS('background-color', background);
  }
});


// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('embedded followup uses readable canonical composer geometry and expands without losing draft or attachments', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.goto('/dev/preview/apps/AppsRequestComposer?chrome=0&theme=light&width=700&variant=embed');
  await waitForComponentPreview(page);
  const composer = page.getByTestId('apps-request-composer');
  const input = page.getByTestId('apps-request-textarea');
  await expect(composer).toHaveClass(/canonical-composer/);
  const collapsed = await composer.boundingBox();
  expect(collapsed!.width).toBeGreaterThan(600);
  expect(collapsed!.height).toBeGreaterThanOrEqual(60);
  expect(await input.evaluate(element => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  // Clicking the actual field padding focuses the same mounted input.
  await composer.click({ position: { x: collapsed!.width / 2, y: 4 } });
  await expect(input).toBeFocused();
  await expect.poll(async () => (await composer.boundingBox())!.height).toBeGreaterThanOrEqual(180);
  await input.fill('Keep this followup draft');
  await page.getByTestId('apps-request-file-input').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('visible facts') });
  await page.getByTestId('apps-request-submit').click();
  // A declined request must retain both the original text and attachments.
  await expect(input).toHaveValue('Keep this followup draft');
  await expect(page.getByTestId('apps-request-attachments')).toContainText('notes.txt');
  await expect(input).toBeFocused();
  await testInfo.attach('embedded-followup-expanded', { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  await input.press('Escape');
  await expect(input).not.toBeFocused();
  await expect(input).toHaveValue('Keep this followup draft');
});

for (const theme of ['light', 'dark']) {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test(`embedded followup sparkle is decorative gray and its input surface expands in ${theme}`, async ({ page }) => {
    await page.goto(`/dev/preview/apps/AppsRequestComposer?chrome=0&theme=${theme}&width=700&variant=embed`);
    await waitForComponentPreview(page);
    const composer = page.getByTestId('apps-request-composer');
    const input = page.getByTestId('apps-request-textarea');
    const sparkle = composer.locator('.workspace-prompt-ai-icon');
    await expect(sparkle).toBeVisible();
    await expect(sparkle).toHaveAttribute('aria-hidden', 'true');
    await expect(sparkle).toHaveCSS('pointer-events', 'none');
    expect(await sparkle.evaluate(element => ({
      tag: element.tagName,
      button: !!element.closest('button, a, [role="button"]'),
      tabIndex: (element as HTMLElement).tabIndex,
    }))).toEqual({ tag: 'SPAN', button: false, tabIndex: -1 });
    const normalInputGray = await sparkle.evaluate(element => {
      const probe = document.createElement('span');
      // The actual normal message input uses this same placeholder color.
      probe.style.background = 'var(--empty-input-placeholder-color, color-mix(in srgb, var(--color-font-primary) 72%, transparent))';
      element.parentElement!.appendChild(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return color;
    });
    await expect(sparkle).toHaveCSS('background-color', normalInputGray);
    await expect(page.getByTestId('apps-request-add-files')).toHaveCount(0);
    const iconBounds = (await sparkle.boundingBox())!;
    // Pointer input on the decorative icon reaches the same clickable field.
    await page.mouse.click(iconBounds.x + iconBounds.width / 2, iconBounds.y + iconBounds.height / 2);
    await expect(input).toBeFocused();
    await expect(composer).toHaveClass(/focused/);
    await expect.poll(async () => (await composer.boundingBox())!.height).toBeGreaterThanOrEqual(180);
    await expect(sparkle).toHaveCount(0);
    await expect(page.getByTestId('apps-request-add-files')).toBeVisible();
    await input.press('Escape');
    await expect(sparkle).toBeVisible();
  });
}

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('natural request composer submits text with compatible files and preserves the draft on empty submit', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsRequestComposer?chrome=0&theme=light&width=390');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-request-mic')).toBeVisible();
  await expect(page.getByTestId('apps-request-add-files')).toBeVisible();
  await page.getByTestId('apps-request-file-input').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('quiet cafes') });
  await expect(page.getByTestId('apps-request-attachments')).toContainText('notes.txt');
  await page.getByTestId('apps-request-textarea').fill('Find quiet cafés in Berlin');
  const submitted = page.evaluate(() => new Promise(resolve => window.addEventListener('apps-request-preview-submit', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('apps-request-submit').click();
  expect(await submitted).toEqual({ text: 'Find quiet cafés in Berlin', filenames: ['notes.txt'] });
  await expect(page.getByTestId('apps-request-textarea')).toHaveValue('');
  await expect(page.getByTestId('apps-request-attachments')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('saved result fullscreen keeps typed cards, toggleable filters and a followup composer with native context', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=sharedResults');
  await waitForComponentPreview(page);
  const grid = page.getByTestId('search-template-grid');
  await expect(grid.getByTestId('embed-preview')).toHaveCount(12);
  await expect(grid.getByTestId('preview-tools')).toHaveCount(0);
  // The grid can be ready while its fullscreen ancestor is still sliding in.
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const composer = page.getByTestId('apps-request-composer');
  const before = await composer.boundingBox();
  const contentArea = page.locator('.content-area').first();
  // An absolute fullscreen needs the same definite scrollport as the real Apps host.
  const scrollport = await contentArea.boundingBox();
  expect(scrollport?.height ?? 0).toBeGreaterThan(300);
  await contentArea.evaluate(element => element.scrollTop = element.scrollHeight);
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('search-template-filter-button')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('search-template-filter')).toBeFocused();
  await expect(page.getByTestId('search-template-toolbar')).toBeInViewport();
  await expect(composer).toBeInViewport();
  const after = await composer.boundingBox();
  expect(Math.abs((before?.y ?? 0) - (after?.y ?? 0))).toBeLessThan(2);
  await page.getByTestId('search-template-filter').fill('books');
  await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
  await expect(grid).toContainText('Cafe 1');
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
  await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
  await expect(page.getByTestId('search-template-query')).toHaveText('Saved cafes');
  for (const id of ['search-template-save-search', 'search-template-create-workflow']) {
    const action = page.getByTestId(id);
    await expect(action).toHaveCSS('text-decoration-line', 'none');
    await action.hover();
    await expect(action).toHaveCSS('text-decoration-line', 'none');
    await action.focus();
    await expect(action).toBeFocused();
    await expect(action).toHaveCSS('text-decoration-line', 'none');
  }
  const saved = page.evaluate(() => new Promise<unknown>(resolve => window.addEventListener('apps-result-preview-save', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('search-template-save-search').click();
  expect(await saved).toMatchObject({ skill_id: 'search', input: { requests: [{ query: 'Saved cafes' }] } });
  await expect(page.getByTestId('search-template-save-search')).toHaveText('Saved search');
  await expect(page.getByTestId('search-template-save-search')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('search-template-save-search')).toBeDisabled();
  await expect(page.getByTestId('search-template-save-search').locator('.search-heart')).toHaveCSS('background-color', 'rgb(253, 80, 160)');
  await page.getByTestId('apps-request-textarea').fill('Which has outdoor seats?');
  const followup = page.evaluate(() => new Promise<unknown>(resolve => window.addEventListener('apps-result-preview-followup', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('apps-request-submit').click();
  expect(await followup).toMatchObject({ text: 'Which has outdoor seats?', context: { skill_id: 'search', input: { requests: [{ query: 'Saved cafes' }] }, result: { results: expect.any(Array) } } });
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('fullscreen map collections reuse actual previews in a vertical grid with typed filters', async ({ page }) => {
  await page.goto('/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=390&variant=fullscreen');
  await waitForComponentPreview(page);
  const view = page.getByTestId('embeds-map-view');
  await expect(view.getByTestId('embeds-map-view-card')).toHaveCount(5);
  await expect(view.getByTestId('embeds-map-view-map')).toHaveAttribute('data-map-hydrated', 'true');
  const cards = view.getByTestId('embeds-map-view-card');
  const first = await cards.nth(0).boundingBox(); const second = await cards.nth(1).boundingBox();
  expect((second?.y ?? 0)).toBeGreaterThan((first?.y ?? 0));
  expect(Math.abs((first?.x ?? 0) - (second?.x ?? 0))).toBeLessThan(2);
  await expect(view.getByTestId('embeds-map-view-filter-button')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('calendar collections initialize after real entries load and preserve subsequent user tab choice', async ({ page }) => {
  await page.goto('/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=1000&variant=fullscreenCalendar');
  await waitForComponentPreview(page);
  const view = page.getByTestId('embeds-map-view');
  await expect(view.getByTestId('embeds-results-view-tab-calendar')).toHaveAttribute('aria-selected', 'true');
  await expect(view.getByTestId('embeds-results-view-calendar')).toBeVisible();
  await expect(view.getByTestId('embeds-results-view-calendar-item')).toHaveCount(10);
  await view.getByTestId('embeds-results-view-tab-map').click();
  await expect(view.getByTestId('embeds-results-view-tab-map')).toHaveAttribute('aria-selected', 'true');
  await expect(view.getByTestId('embeds-map-view-map')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('native paid audio transcription opens the shared recording fullscreen with its transcript', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=transcription');
  await waitForComponentPreview(page);
  await expect(page.getByText('The meeting starts at nine.', { exact: true })).toBeVisible();
  await expect(page.getByTestId('embed-header-title')).toContainText('Meeting notes');
  await expect(page.getByText('This result could not be opened.', { exact: true })).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
test('reopened search fullscreen recognizes the saved native request without another save', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=1000&variant=savedResults');
  await waitForComponentPreview(page);
  const saveSearch = page.getByTestId('search-template-save-search');
  await expect(saveSearch).toHaveText('Saved search');
  await expect(saveSearch).toHaveAttribute('aria-pressed', 'true');
  await expect(saveSearch).toBeDisabled();
  await expect(saveSearch.locator('.search-heart')).toHaveCSS('background-color', 'rgb(253, 80, 160)');
  await expect(page.getByTestId('search-template-create-workflow')).toBeVisible();
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
test('declining a guest search save leaves the search unsaved and retryable', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=guestSaveDeclined');
  await waitForComponentPreview(page);
  await page.evaluate(() => {
    const browser = window as Window & { signupAttempts?: number };
    browser.signupAttempts = 0;
    window.addEventListener('apps-result-preview-signup', () => { browser.signupAttempts = (browser.signupAttempts ?? 0) + 1; });
  });
  const saveSearch = page.getByTestId('search-template-save-search');
  for (const attempts of [1, 2]) {
    await saveSearch.click();
    await expect.poll(() => page.evaluate(() => (window as Window & { signupAttempts?: number }).signupAttempts)).toBe(attempts);
    await expect(saveSearch).toHaveText('Save this search');
    await expect(saveSearch).toHaveAttribute('aria-pressed', 'false');
    await expect(saveSearch).toBeEnabled();
  }
});

// contract-test: supporting surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('Apps result host preserves the image renderer privacy projection in actual followup requests', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1000, height: 720 });
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&width=700&variant=projectedImagePrivacy');
  await waitForComponentPreview(page);
  const result = page.getByTestId('result-embed-content');
  await expect(result).toHaveAttribute('data-app-id', 'images');
  const image = page.locator('.full-image');
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('src', '/images/examples/group1.jpg');
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(result).toContainText('2.0 KB');
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const expectImageAboveComposer = async () => {
    await expect.poll(async () => {
      const imageBounds = await image.boundingBox();
      const composerBounds = await page.getByTestId('apps-request-composer').boundingBox();
      return composerBounds!.y - imageBounds!.y - imageBounds!.height;
    }).toBeGreaterThanOrEqual(8);
  };
  await expectImageAboveComposer();
  await page.getByTestId('apps-request-textarea').fill('Describe the visible image facts');
  await expectImageAboveComposer();
  const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('apps-request-submit').click();
  const request = await pending;
  const context = request.postDataJSON().context;
  expect(context.result).toEqual({ filename: 'Projected photo.jpg', file_size: 2048, file_type: 'image/jpeg' });
  expect(context.skill_id).toBe('view');
  expect(context.input).toEqual({ prompt: 'A visible parent request' });
  const serialized = JSON.stringify(context.result);
  for (const sentinel of ['parent-private-crypto-sentinel', 'parent-private-storage-sentinel', 'child-private-crypto-sentinel', 'child-private-storage-sentinel']) {
    expect(serialized).not.toContain(sentinel);
  }
  for (const key of ['aes_key', 'aesKey', 'aes_nonce', 'aesNonce', 's3_base_url', 'files']) {
    expect(context.result).not.toHaveProperty(key);
  }
  await testInfo.attach('AppsResultFullscreen-image-projected-followup', { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen,events-search.surface-parity
test('event fullscreen forwards visible event fields while excluding raw and nested transport metadata', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  await page.goto('/dev/preview/embeds/events/EventEmbedFullscreen?chrome=0&width=700&variant=projectedPrivacy');
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  await expect(page.getByTestId('event-organizer-card')).toContainText('AI Berlin Community');
  await expect(page.getByTestId('event-venue-card')).toContainText('Factory Berlin');
  await page.getByTestId('apps-request-textarea').fill('What should I know about this event?');
  const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('apps-request-submit').click();
  const request = await pending;
  const payload = request.postDataJSON();
  const result = payload.context.result;
  expect(payload.app_id).toBe('events');
  expect(result).toMatchObject({
    embed_id: 'preview-event-fullscreen-1', title: 'AI & Machine Learning Berlin Meetup – Spring Edition',
    provider: 'meetup', date_start: '2026-03-15T19:00:00+01:00', date_end: '2026-03-15T22:00:00+01:00', timezone: 'Europe/Berlin',
    organizer: { id: 'org-ai-berlin', name: 'AI Berlin Community', slug: 'ai-berlin' },
    venue: { name: 'Factory Berlin', address: 'Rheinsberger Str. 76-77', city: 'Berlin', country: 'Germany', lat: 52.5393, lon: 13.4028 },
    fee: { amount: 0, currency: 'EUR' }, rsvp_count: 142, is_paid: false,
  });
  expect(Object.keys(result.organizer).sort()).toEqual(['id', 'name', 'slug']);
  expect(Object.keys(result.venue).sort()).toEqual(['address', 'city', 'country', 'lat', 'lon', 'name']);
  expect(Object.keys(result.fee).sort()).toEqual(['amount', 'currency']);
  const serialized = JSON.stringify(result);
  for (const scope of ['event', 'flat', 'organizer', 'venue', 'fee']) {
    for (const kind of ['crypto', 'storage']) expect(serialized).not.toContain(`${scope}-private-${kind}-sentinel`);
  }
  for (const key of ['aes_key', 'aes_nonce', 's3_base_url', 'files', 'organizer_name', 'organizer_private_encryption', 'venue_s3_key']) expect(result).not.toHaveProperty(key);
  await testInfo.attach('EventFullscreen-projected-followup', { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
});
