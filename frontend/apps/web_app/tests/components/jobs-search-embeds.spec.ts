import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('Jobs parent preview uses bounded metadata and shows truthful states at laptop and phone widths', async ({ page }) => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
    for (const [variant, expected] of [
      ['', '2 jobs'], ['empty', 'No results found'], ['processing', 'Processing'],
      ['cancelled', 'Cancelled'], ['error', 'Search source unavailable'],
    ] as const) {
      const query = new URLSearchParams({ chrome: '0', theme: 'light', width: String(width) });
      if (variant) query.set('variant', variant);
      await page.goto(`/dev/preview/embeds/jobs/JobsSearchEmbedPreview?${query}`);
      await waitForComponentPreview(page);
      const preview = page.getByTestId('jobs-search-preview');
      await expect(preview).toContainText(expected);
      await expect(preview).not.toContainText('Analyse public climate datasets');
      expect(await preview.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    }
  }
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('Jobs fullscreen opens a listing and keeps unknown remote and salary claims absent', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedFullscreen?chrome=0&theme=light');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('jobs-search-fullscreen')).toBeVisible();
  const cards = page.getByTestId('jobs-result-card');
  await expect(cards).toHaveCount(2);
  await cards.first().click();
  const detail = page.getByTestId('jobs-result-fullscreen');
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('Climate Data Analyst');
  await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute('href', 'https://example.com/jobs/climate-data');
  await expect(detail.getByTestId('jobs-remote-badge')).toHaveCount(0);
  await expect(detail.getByTestId('jobs-salary')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('Jobs child detail validates external actions and fits a phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedFullscreen?chrome=0&theme=light&width=390');
  await waitForComponentPreview(page);
  const search = page.getByTestId('jobs-search-fullscreen');
  await expect(search.getByTestId('jobs-result-card')).toHaveCount(2);
  expect(await search.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

  await page.goto('/dev/preview/embeds/jobs/JobsResultEmbedFullscreen?chrome=0&theme=light&width=390');
  await waitForComponentPreview(page);
  const detail = page.getByTestId('jobs-result-fullscreen');
  await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute('href', 'https://example.com/jobs/climate-data');
  await expect(detail.getByTestId('jobs-apply-link')).toHaveAttribute('href', 'https://example.com/jobs/climate-data/apply');
  await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(detail.getByTestId('jobs-remote-badge')).toHaveCount(0);
  await expect(detail.getByTestId('jobs-salary')).toHaveCount(0);
  expect(await detail.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

  await page.goto('/dev/preview/embeds/jobs/JobsResultEmbedFullscreen?chrome=0&theme=light&width=390&variant=longMetadata');
  await waitForComponentPreview(page);
  const body = page.getByTestId('jobs-detail-body');
  const company = body.getByTestId('jobs-company-value');
  await expect(company).toContainText('Sustainable Digital Infrastructure and Research');
  expect((await body.boundingBox())!.width).toBeGreaterThan(300);
  expect((await company.boundingBox())!.width).toBeGreaterThan(200);
  expect((await company.boundingBox())!.height).toBeLessThan(100);
  expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

  await page.goto('/dev/preview/embeds/jobs/JobsResultEmbedFullscreen?chrome=0&theme=light&width=390&variant=unsafeUrl');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('jobs-source-link')).toHaveCount(0);
  await expect(page.getByTestId('jobs-apply-link')).toHaveCount(0);

  await page.goto('/dev/preview/embeds/jobs/JobsResultEmbedFullscreen?chrome=0&theme=light&width=390&variant=credentialUrl');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('jobs-source-link')).toHaveCount(0);
  await expect(page.getByTestId('jobs-apply-link')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('Jobs recorded Stockholm example keeps real provider attribution and unknown claims', async ({ page }) => {
  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedFullscreen?chrome=0&theme=light&variant=realStockholm');
  await waitForComponentPreview(page);
  const search = page.getByTestId('jobs-search-fullscreen');
  await expect(search).toContainText('JobTech');
  await expect(search).toContainText('Stockholm · SE');
  const cards = search.getByTestId('jobs-result-card');
  await expect(cards).toHaveCount(5);
  await expect(cards.first()).toContainText('Senior Systemutvecklare');
  await cards.first().click();
  const detail = page.getByTestId('jobs-result-fullscreen');
  await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute('href', 'https://arbetsformedlingen.se/platsbanken/annonser/31589252');
  await expect(detail.getByTestId('jobs-remote-badge')).toHaveCount(0);
  await expect(detail.getByTestId('jobs-salary')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('Jobs parent shows singleton location and selected countries from parent metadata', async ({ page }) => {
  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedPreview?chrome=0&theme=light&variant=located');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('jobs-search-scope')).toHaveText('Stockholm · SE');

  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedPreview?chrome=0&theme=light&variant=multiCountry');
  await waitForComponentPreview(page);
  const preview = page.getByTestId('jobs-search-preview');
  await expect(preview.getByTestId('jobs-search-scope')).toHaveText('Berlin · DE, SE');
  await expect(preview).toContainText('Arbeitsagentur, Arbeitnow, 80,000 Hours, Hard Problems, JobTech');
  await expect(preview).not.toContainText('eighty_thousand_hours');
  await expect(preview.getByTestId('jobs-result-card')).toHaveCount(0);

  await page.goto('/dev/preview/embeds/jobs/JobsSearchEmbedFullscreen?chrome=0&theme=light&variant=multiCountry');
  await waitForComponentPreview(page);
  const fullscreen = page.getByTestId('jobs-search-fullscreen');
  await expect(fullscreen).toContainText('Berlin · DE, SE');
  await expect(fullscreen).toContainText('Arbeitsagentur, Arbeitnow, 80,000 Hours, Hard Problems, JobTech');
});
