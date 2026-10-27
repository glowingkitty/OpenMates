import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview, waitForComponentMotion } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const components = [
  ['code/CodeRepoEmbed', 'lemmingDev/ESP32-BLE-Gamepad'],
  ['models3d/Model3DResultEmbed', 'Low-poly research observatory'],
  ['jobs/JobsResultEmbed', 'Climate Data Analyst'],
  ['business/BusinessCompanyFinancialResultEmbed', 'Cal-Maine Foods, Inc.'],
  ['social_media/SocialMediaPostEmbed', 'Small cafe bar layout notes'],
] as const;

async function openPreview(page: import('@playwright/test').Page, component: string, width: number, variant?: string, props?: Record<string, unknown>) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/dev/preview/embeds/${component}?chrome=0&width=${width}&theme=light${width > 400 && component.endsWith('Preview') ? '&context=chat' : ''}${variant ? `&variant=${variant}` : ''}${props ? `&props=${encodeURIComponent(JSON.stringify(props))}` : ''}`);
  await waitForComponentPreview(page);
  if (component.endsWith('Fullscreen')) await waitForComponentMotion(page.locator('.unified-embed-fullscreen-overlay').first());
}

for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`social image remains uncropped with a plain publication date at ${width}px`, async ({ page }, testInfo) => {
    await openPreview(page, 'social_media/SocialMediaPostEmbedPreview', width, undefined, { media_url: '/store-examples/events-1.webp' });
    const card = page.getByTestId('embed-preview');
    const image = card.locator('.card-media > img');
    await expect(image).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    await expect(card.getByTestId('social-post-publication-date')).toHaveText('May 24, 2026');
    await expect(card.getByTestId('embed-calendar-date')).toHaveCount(0);
    await testInfo.attach(`social-image-${width}`, { body: await card.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
for (const width of [390, 1000]) {
  test(`catalog results share concise cards and truthful missing states at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(240_000);
    const fixture = await page.request.get('/images/examples/group1.jpg');
    expect(fixture.ok()).toBeTruthy();
    const bytes = await fixture.body();
    await page.route('**/api/v1/image?*', route => route.fulfill({ status: 200, contentType: 'image/jpeg', body: bytes }));
    for (const [component, title] of components) {
      await openPreview(page, `${component}Preview`, width, width > 400 ? 'chat' : undefined);
      const card = page.getByTestId('embed-preview');
      await expect(card).toHaveClass(/result-preview/);
      await expect(page.locator('[data-testid="result-card-title"], [data-testid="code-repo-title"]')).toHaveText(title);
      if (width > 400) {
        await expect(card.locator('.result-tools a')).toHaveCount(0);
        await expect(card.getByTestId('preview-tools').getByRole('button')).toHaveCount(2);
      }
      const suppliedDate = component.startsWith('jobs/') ? '2026-10-01T00:00:00.000Z'

        : component.startsWith('business/') ? '2025-07-18T00:00:00.000Z' : undefined;
      if (component.startsWith('social_media/')) {
        await expect(card.getByTestId('embed-calendar-date')).toHaveCount(0);
        const publication = card.getByTestId('social-post-publication-date');
        await expect(publication).toHaveText('May 24, 2026');
        await expect(publication).toHaveAttribute('datetime', '2026-05-24T10:30:00.000Z');
        const pill = await publication.evaluate(element => {
          const style = getComputedStyle(element);
          return { radius: Number.parseFloat(style.borderTopLeftRadius), height: element.getBoundingClientRect().height, shadow: style.boxShadow };
        });
        expect(pill.radius).toBeGreaterThanOrEqual(pill.height / 2);
        expect(pill.shadow).not.toBe('none');
        await expect(publication.locator('strong')).toHaveCount(0);
        const bounds = await card.evaluate(element => {
          const card = element.getBoundingClientRect();
          return Array.from(element.querySelectorAll('[data-testid="social-post-publication-date"], [data-testid="result-card-title"], .card-source')).map(node => {
            const box = node.getBoundingClientRect();
            return box.left >= card.left && box.right <= card.right && box.top >= card.top && box.bottom <= card.bottom;
          });
        });
        expect(bounds).toEqual([true, true, true]);
      }
      if (suppliedDate) {
        const calendar = card.getByTestId('embed-calendar-date');
        await expect(calendar).toHaveCount(1);
        await expect(calendar).toBeVisible();
        await expect(calendar).toHaveAttribute('datetime', suppliedDate);
        await expect(calendar.locator('strong')).toHaveText(String(new Date(suppliedDate).getUTCDate()));
        await expect(card.getByRole('button', { name: 'Published', exact: true })).toHaveCount(0);
      }
      if (component.startsWith('business/')) {
        const financialFacts = [
          ['Revenue', 'USD 4.3B · FY 2025'],
          ['Net income', 'USD 1.2B · FY 2025'],
          ['Source filing', '10-K'],
        ] as const;
        for (const [label] of financialFacts) {
          const control = card.getByRole('button', { name: label, exact: true });
          await expect(control).toHaveText('');
          await expect(control).toHaveCSS('width', '44px');
          await expect(control).toHaveCSS('height', '44px');
        }
        // Measure the controls and both clipping ancestors in the same frame.
        const controls = await card.evaluate(root => {
          const content = root.querySelector('[data-testid="result-card-content"]')!;
          const facts = content.querySelector('.card-facts')!;
          const bounds = [root, content, facts].map(element => element.getBoundingClientRect());
          return Array.from(facts.querySelectorAll('button')).map(button => {
            const rect = button.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const points = [[centerX, centerY], [rect.left + 2, centerY], [rect.right - 2, centerY], [centerX, rect.top + 2], [centerX, rect.bottom - 2]];
            return {
              label: button.getAttribute('aria-label'),
              insideBounds: bounds.every(bound => rect.left >= bound.left && rect.top >= bound.top && rect.right <= bound.right && rect.bottom <= bound.bottom),
              hitTestable: points.every(([x, y]) => button.contains(document.elementFromPoint(x, y))),
            };
          });
        });
        expect(controls).toEqual(financialFacts.map(([label]) => ({ label, insideBounds: true, hitTestable: true })));
        for (const [label, explanation] of financialFacts) {
          const control = card.getByRole('button', { name: label, exact: true });
          await control.focus();
          await expect(page.getByRole('tooltip')).toContainText(explanation);
          await control.press('Escape');
          await expect(page.getByRole('tooltip')).toHaveCount(0);
          await control.click();
          await expect(control).toHaveAttribute('data-pinned', 'true');
          await expect(page.getByRole('tooltip')).toContainText(explanation);
          await control.press('Escape');
          await expect(page.getByRole('tooltip')).toHaveCount(0);
        }
      }
      const box = await card.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      await testInfo.attach(`${component.replaceAll('/', '-')}-${width}`, { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
      await openPreview(page, `${component}Preview`, width, 'longTitle');
      await expect(page.locator('[data-testid="result-card-title"], [data-testid="code-repo-title"]')).toBeVisible();
      expect(await page.getByTestId('result-card-content').evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
      await openPreview(page, `${component}Preview`, width, 'missingData', component.startsWith('social_media/') ? { published_at: '' } : undefined);
      if (suppliedDate) await expect(page.getByTestId('embed-calendar-date')).toHaveCount(0);
      await expect(page.locator('[data-testid="result-card-title"], [data-testid="code-repo-title"]')).not.toBeEmpty();
      if (component.startsWith('code/')) {
        await expect(page.getByRole('button', { name: 'Stars', exact: true })).toHaveCount(0);
      } else if (component.startsWith('models3d/')) {
        await expect(page.getByRole('button', { name: 'Free model', exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'License', exact: true })).toHaveCount(0);
      } else if (component.startsWith('jobs/')) {
        await expect(page.getByRole('button', { name: 'Remote work', exact: true })).toHaveAttribute('data-state', 'unknown');
        await expect(page.getByTestId('jobs-salary')).toHaveCount(0);
      } else if (component.startsWith('social_media/')) {
        await expect(page.getByTestId('social-post-publication-date')).toHaveCount(0);
        await expect(page.getByTestId('embed-calendar-date')).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Likes', exact: true })).toHaveCount(0);
        await openPreview(page, `${component}Preview`, width, 'invalidDate');
        await expect(page.getByTestId('social-post-publication-date')).toHaveCount(0);
        await expect(page.getByTestId('embed-calendar-date')).toHaveCount(0);
      }
      await openPreview(page, `${component}Fullscreen`, width);
      const fullscreen = page.getByTestId('result-embed-content');
      await expect(fullscreen).toBeVisible();
      if (component.startsWith('code/')) {
        await expect(page.getByRole('heading', { name: 'Languages', exact: true })).toBeVisible();
        await expect(page.getByRole('link', { name: 'Open on GitHub' })).toHaveAttribute('href', /github.com/);
      } else if (component.startsWith('models3d/')) {
        await expect(page.getByTestId('result-media').locator('img')).toHaveCSS('object-fit', 'contain');
        await expect(page.getByTestId('models3d-open-provider-cta')).toHaveAttribute('href', 'https://example.com/models/observatory');
      } else if (component.startsWith('jobs/')) {
        await expect(page.getByTestId('jobs-description')).toContainText('climate datasets');
        await expect(page.getByTestId('jobs-apply-link')).toHaveAttribute('href', /climate-data\/apply$/);
        const primary = page.getByTestId('jobs-apply-link');
        const source = page.getByTestId('jobs-detail-body').getByTestId('jobs-source-link');
        const facts = page.getByTestId('result-facts');
        await expect(primary).toBeVisible();
        await expect(source).toBeVisible();
        await expect(facts).toBeVisible();
        // One DOM evaluation measures a single animation frame while the pane opens.
        const geometry = await page.getByTestId('jobs-result-fullscreen').evaluate(root => {
          const primary = root.querySelector('[data-testid="jobs-apply-link"]')!.getBoundingClientRect();
          const facts = root.querySelector('[data-testid="result-facts"]')!.getBoundingClientRect();
          const source = root.querySelector('[data-testid="jobs-detail-body"] [data-testid="jobs-source-link"]')!.getBoundingClientRect();
          return { primaryBottom: primary.bottom, factsTop: facts.top, factsBottom: facts.bottom, sourceTop: source.top };
        });
        expect(geometry.primaryBottom).toBeLessThan(geometry.factsTop);
        expect(geometry.sourceTop).toBeGreaterThan(geometry.factsBottom);
      } else if (component.startsWith('business/')) {
        await expect(fullscreen).toContainText('Cal-Maine Foods');
        await expect(page.getByTestId('business-open-sec-filing')).toHaveAttribute('href', /sec.gov/);
      } else {
        await expect(fullscreen).toContainText('Community cafe research notes');
        await expect(page.getByRole('link', { name: 'Read the research notes' })).toHaveAttribute('href', 'https://example.com/cafe-research');
      }
      await testInfo.attach(`${component.replaceAll('/', '-')}-fullscreen-${width}`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
    }
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('repository facts explain known values on focus, keyboard, tap and Escape; fullscreen preserves provider and contributors', async ({ page }) => {
  const expansions: string[] = [];
  page.on('console', message => {
    if (message.text() === '[Preview] Repo fullscreen clicked') expansions.push(message.text());
  });
  await openPreview(page, 'code/CodeRepoEmbedPreview', 390);
  const stars = page.getByRole('button', { name: 'Stars', exact: true });
  await stars.focus();
  await expect(page.getByRole('tooltip')).toContainText('1516');
  await stars.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  const gridCard = page.getByTestId('embed-preview');
  await expect(gridCard).toHaveAttribute('role', 'button');
  for (const key of ['Enter', 'Space']) {
    await stars.focus();
    await stars.press(key);
    await expect(stars).toHaveAttribute('data-pinned', 'true');
    await expect(page.getByRole('tooltip')).toContainText('1516');
    expect(expansions).toHaveLength(0);
    await stars.press('Escape');
    await expect(stars).toHaveAttribute('data-pinned', 'false');
    await expect(page.getByRole('tooltip')).toHaveCount(0);
  }
  // Positive control proves the fixture callback detects outer-card expansion.
  await gridCard.focus();
  await gridCard.press('Enter');
  await expect.poll(() => expansions.length).toBe(1);
  await stars.click();
  await expect(stars).toHaveAttribute('data-pinned', 'true');
  // The pinned panel may cover the title; the canvas corner is outside the fact and panel.
  await page.getByTestId('component-preview-canvas').click({ position: { x: 2, y: 2 } });
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await openPreview(page, 'code/CodeRepoEmbedFullscreen', 1000);
  await expect(page.getByTestId('result-embed-content')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open on GitHub' })).toHaveAttribute('href', 'https://github.com/lemmingDev/ESP32-BLE-Gamepad');
  await expect(page.getByRole('heading', { name: 'Languages', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Top Contributors', exact: true })).toBeVisible();
  await expect(page.getByRole('link').filter({ hasText: 'lemmingDev' })).toHaveAttribute('href', 'https://github.com/lemmingDev');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('catalogue images stay uncropped and provider action never fetches model files', async ({ page }) => {
  // Eight independent mounts cover loaded, missing and failed images at both widths.
  test.setTimeout(120_000);
  const requestedModels: string[] = [];
  page.on('request', request => { if (/\.(glb|gltf|obj|stl|fbx)(\?|$)/i.test(request.url())) requestedModels.push(request.url()); });
  for (const width of [390, 1000]) {
    await openPreview(page, 'models3d/Model3DResultEmbedPreview', width, width > 400 ? 'chat' : undefined);
    const image = page.getByTestId('result-card-media').locator('img');
    await expect(image).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    const source = new URL((await image.getAttribute('src'))!, page.url());
    expect(source.pathname).toBe('/store-examples/generate-2.webp');
    await openPreview(page, 'models3d/Model3DResultEmbedFullscreen', width);
    const fullscreenImage = page.getByTestId('result-media').locator('img');
    await expect(fullscreenImage).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => fullscreenImage.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(page.getByTestId('embed-header-title')).toHaveText('Low-poly research observatory');
    await expect(page.getByText('Low-poly research observatory', { exact: true })).toHaveCount(1);
    await expect(page.locator('a[href="https://example.com/models/observatory"]')).toHaveCount(1);
    await expect(page.getByTestId('models3d-open-provider-cta')).toHaveAttribute('href', 'https://example.com/models/observatory');
    for (const variant of ['missingData', 'brokenImage']) {
      await openPreview(page, 'models3d/Model3DResultEmbedFullscreen', width, variant);
      await expect(page.getByTestId('result-media').locator('img')).toHaveCount(0);
      const fallback = page.getByTestId('models3d-preview-unavailable');
      await expect(fallback).toBeVisible();
      await expect(fallback).toHaveText('A preview is unavailable for this file.');
      const placeholderIcon = fallback.locator('.placeholder-icon');
      await expect(placeholderIcon).toHaveCSS('mask-image', /^url\(/);
      // Vite may inline the SVG or emit an asset URL; either must decode as a real image.
      expect(await placeholderIcon.evaluate(async element => {
        const mask = getComputedStyle(element).maskImage;
        const source = mask.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
        if (!source) return false;
        return await new Promise<boolean>(resolve => {
          const image = new Image();
          image.onload = () => resolve(image.naturalWidth > 0 && image.naturalHeight > 0);
          image.onerror = () => resolve(false);
          image.src = source;
        });
      })).toBe(true);
      await expect(page.locator('a[href="https://example.com/models/observatory"]')).toHaveCount(1);
    }
  }
  expect(requestedModels).toEqual([]);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('jobs, financials and social posts preserve their source, evidence and existing details', async ({ page }) => {
  await openPreview(page, 'jobs/JobsResultEmbedFullscreen', 390, 'richDetails');
  await expect(page.getByTestId('jobs-apply-link')).toHaveAttribute('href', 'https://example.com/jobs/climate-data/apply');
  await expect(page.getByTestId('jobs-source-link')).toHaveAttribute('href', 'https://example.com/jobs/climate-data');
  await expect(page.getByTestId('jobs-impact')).toContainText('healthcare');
  await expect(page.getByTestId('jobs-description')).toContainText('Benefits');
  await openPreview(page, 'jobs/JobsResultEmbedFullscreen', 390, 'summaryOnly');
  await expect(page.getByTestId('jobs-details-warning')).toBeVisible();
  await openPreview(page, 'business/BusinessCompanyFinancialResultEmbedFullscreen', 390);
  await expect(page.getByTestId('business-open-sec-filing')).toHaveAttribute('href', /sec.gov/);
  await page.getByRole('button', { name: 'Source filing', exact: true }).click();
  await expect(page.getByRole('tooltip')).toContainText('0000016160-25-000050');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(page.getByRole('tooltip')).toContainText('Normalized from SEC');
  await openPreview(page, 'social_media/SocialMediaPostEmbedFullscreen', 390, 'longPost');
  const expand = page.getByRole('button', { name: 'Expand post' });
  await expand.click();
  await expect(page.getByRole('button', { name: 'Show less' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Read the research notes' })).toHaveAttribute('href', 'https://example.com/cafe-research');
  await expect(page.getByText('The accessible shelf makes this much easier to use.')).toBeVisible();
});

for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
  test(`hosting and electronics keep facts and missing-data states at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    for (const [component, title] of [
      ['hosting/HostingDomainEmbed', 'cedarcomet.net'],
      ['electronics/ElectronicsComponentEmbed', 'TPS564257DRLR'],
    ]) {
      for (const variant of ['', 'missingData']) {
        await openPreview(page, `${component}Preview`, width, variant || (width > 400 ? 'chat' : undefined));
        await expect(page.getByTestId('result-card-title')).toContainText(variant ? (component.startsWith('hosting') ? 'cedarcomet.et' : title) : title);
        if (component.startsWith('hosting')) {
          if (width > 400) {
            await expect(page.locator('.result-tools a')).toHaveCount(0);
            await expect(page.getByTestId('preview-tools').getByRole('button')).toHaveCount(2);
          }
          const registration = page.getByTestId('hosting-domain-registration');
          await registration.click();
          await expect(page.getByRole('tooltip')).toContainText(variant ? /price unavailable/i : /first.year offer/i);
          await registration.press('Escape');
          if (variant) await expect(page.getByTestId('result-card-content').getByRole('button', { name: 'Could not check', exact: true })).toHaveAttribute('data-state', 'unknown');
        } else if (variant) {
          await expect(page.getByRole('button', { name: 'Efficiency', exact: true })).toHaveCount(0);
        } else {
          const efficiency = page.getByRole('button', { name: 'Efficiency', exact: true });
          await efficiency.focus();
          await expect(page.getByRole('tooltip')).toContainText('92.4%');
          await efficiency.press('Escape');
        }
        await testInfo.attach(`${component.replaceAll('/', '-')}-preview-${variant || 'default'}-${width}`, {
          body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
        });
        await openPreview(page, `${component}Fullscreen`, width, variant || undefined);
        await expect(page.getByTestId('result-embed-content')).toBeVisible();
        if (component.startsWith('hosting')) {
          await expect(page.getByRole('link', { name: /open on ExampleRegistrar/i })).toHaveAttribute('href', /^https:\/\/shop\.ExampleRegistrar\.net\//);
          await expect(page.getByTestId('hosting-domain-registration')).toContainText(variant ? /price unavailable/i : /13[.,]09/);
        } else if (variant) {
          await expect(page.getByTestId('result-embed-content')).toContainText('Example component');
          await expect(page.getByTestId('result-embed-content')).toContainText('Example source');
          await expect(page.getByRole('link', { name: 'Datasheet', exact: true })).toHaveCount(0);
          await expect(page.getByRole('button', { name: 'Input voltage', exact: true })).toHaveCount(0);
        } else {
          await expect(page.getByTestId('result-embed-content')).toContainText('TPS564257DRLR');
          await expect(page.getByRole('link', { name: 'Datasheet', exact: true })).toHaveAttribute('href', 'https://www.ti.com/lit/gpn/tps564257');
          await expect(page.getByRole('button', { name: 'Input voltage', exact: true })).toContainText('4.5 V');
        }
        await testInfo.attach(`${component.replaceAll('/', '-')}-fullscreen-${variant || 'default'}-${width}`, {
          body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
        });
      }
    }
  });

  // contract-test: supporting surface=gui.web assertions=hosting-domains.embeds.parent-child,trademarks.coverage,trademarks.evidence,trademarks.parity
  test(`hosting and trademark collections preserve source coverage and local details at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    for (const variant of ['', 'missingData']) {
      await openPreview(page, 'hosting/HostingSearchEmbedFullscreen', width, variant || undefined);
      const domains = page.getByTestId('hosting-domain-grid');
      await expect(domains.getByTestId('hosting-domain-preview')).toHaveCount(variant ? 1 : 2);
      if (variant) await expect(domains).toContainText(/could not check/i);
      await testInfo.attach(`hosting-collection-${variant || 'default'}-${width}`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
      await domains.getByTestId('hosting-domain-preview').first().click();
      await expect(page.getByTestId('hosting-domain-fullscreen')).toBeVisible();
      await expect(page.getByTestId('hosting-domain-ascii')).toContainText(variant ? 'cedarcomet.et' : 'cedarcomet.com');
      await testInfo.attach(`hosting-collection-child-${variant || 'default'}-${width}`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
      await openPreview(page, 'business/BusinessTrademarkSearchEmbedFullscreen', width, variant || undefined);
      await expect(page.getByTestId('trademark-search-coverage')).toContainText('DE');
      await expect(page.getByTestId('trademark-fullscreen-limitation')).toContainText('legal availability');
      const record = page.getByTestId('trademark-record');
      await expect(record).toContainText(variant ? 'Example mark' : 'ADIDAS');
      await testInfo.attach(`trademark-collection-${variant || 'default'}-${width}`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
      const initialHash = new URL(page.url()).hash;
      if (variant) {
        const status = record.getByTestId('result-card-content').getByRole('button', { name: 'Status unknown', exact: true });
        await status.click();
        await expect(page.getByRole('tooltip')).toContainText('Status unknown');
        await expect(page.getByTestId('trademark-record-fullscreen')).toHaveCount(0);
        await status.press('Escape');
      }
      await record.getByTestId('result-card-title').click();
      const detail = page.getByTestId('trademark-record-fullscreen');
      await expect(detail).toBeVisible();
      await waitForComponentMotion(detail);
      expect(new URL(page.url()).hash).toBe(initialHash);
      if (variant) {
        await expect(detail.getByTestId('trademark-record-source')).toHaveCount(0);
        await expect(detail.getByTestId('trademark-record-detail')).not.toContainText('Application:');
      } else {
        await expect(detail.getByTestId('trademark-record-source')).toHaveAttribute('href', /^https:\/\/tsdr\.ExampleTrademarks\.gov\//);
        await detail.locator('summary').click();
        await expect(detail).toContainText('Tote bags.');
      }
      await testInfo.attach(`trademark-record-${variant || 'default'}-${width}`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
    }
  });
}
