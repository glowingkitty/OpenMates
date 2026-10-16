import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required reason=guest_legal_website_navigation
// Regression: legal documents must never be registered or opened as chat content.
// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content
test('settings legal links open the standalone website and the sidebar has no legal section', async ({ page, baseURL }) => {
  // The isolated backend is self-hosted. Exercise the cloud settings edition explicitly,
  // preserving the real status response and changing only edition metadata.
  await page.route('**/v1/settings/server-status', async route => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    const status = await response.json();
    await route.fulfill({ response, json: { ...status, is_self_hosted: false, is_development: true, server_edition: 'development' } });
  });
  await page.goto('/');
  await page.getByTestId('profile-container').click();
  const footer = page.getByTestId('settings-footer');
  await expect(footer).toBeVisible();
  const configured = process.env.PUBLIC_LANDING_WEBSITE_URL;
  const host = new URL(baseURL ?? page.url()).hostname;
  const development = host === 'localhost' || host === '127.0.0.1' || host.includes('.dev.') || host.startsWith('dev.') || host.endsWith('.vercel.app');
  const website = configured ? new URL(configured).origin : development ? 'https://landing.dev.openmates.org' : 'https://openmates.org';
  for (const slug of ['privacy', 'terms', 'imprint']) {
    const link = footer.getByTestId(`settings-legal-${slug}`);
    await expect(link).toHaveAttribute('href', `${website}/legal/${slug}`);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
  // Intercept the destination so clicking exercises the actual anchor without external network dependencies.
  await page.context().route(`${website}/legal/privacy`, route => route.fulfill({ contentType: 'text/html', body: '<main>Public privacy document</main>' }));
  const popup = page.waitForEvent('popup');
  await footer.getByTestId('settings-legal-privacy').click();
  const document = await popup;
  await expect(document).toHaveURL(`${website}/legal/privacy`);
  await expect(document.getByText('Public privacy document')).toBeVisible();
  await document.close();
  await expect(page).not.toHaveURL(/chat-id=legal-/);
  await page.getByTestId('profile-container').click();
  if (!await page.getByTestId('activity-history-wrapper').isVisible()) await page.getByTestId('sidebar-toggle').click();
  await expect(page.getByTestId('activity-history-wrapper')).toBeVisible();
  const sidebar = page.getByTestId('sidebar-toggle');
  if (await sidebar.isVisible() && await sidebar.getAttribute('aria-expanded') !== 'true') await sidebar.click();
  await expect(page.getByTestId('activity-history-wrapper')).toBeInViewport();
  await expect(page.locator('[data-group-key="legal"]')).toHaveCount(0);
  await expect(page.locator('[data-chat-id^="legal-"]')).toHaveCount(0);
});

for (const slug of ['privacy', 'terms', 'imprint']) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content
  test(`legacy legal ${slug} chat link leaves the app for the public document`, async ({ page }) => {
    await page.context().route(`**/legal/${slug}*`, route => route.fulfill({ contentType: 'text/html', body: '<main>Public legal document</main>' }));
    await page.goto(`/?lang=de#chat-id=legal-${slug}`);
    await expect(page).toHaveURL(new RegExp(`/legal/${slug}\\?lang=de$`));
    await expect(page.getByText('Public legal document')).toBeVisible();
    await expect(page.getByTestId('message-editor')).toHaveCount(0);
  });
}

for (const path of ['/legal/privacy', '/legal/terms', '/legal/imprint', '/privacy']) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content
  test(`legacy document route ${path} redirects directly to the public website`, async ({ request, baseURL }) => {
    const response = await request.get(`${path}?lang=de`, { maxRedirects: 0 });
    const host = new URL(baseURL ?? 'http://localhost:5173').hostname;
    const development = host === 'localhost' || host === '127.0.0.1' || host.includes('.dev.') || host.startsWith('dev.') || host.endsWith('.vercel.app');
    const website = process.env.PUBLIC_LANDING_WEBSITE_URL ? new URL(process.env.PUBLIC_LANDING_WEBSITE_URL).origin : development ? 'https://landing.dev.openmates.org' : 'https://openmates.org';
    expect(response.status()).toBe(302);
    expect(response.headers().location).toBe(`${website}${path === '/privacy' ? '/legal/privacy' : path}?lang=de`);
  });
}
