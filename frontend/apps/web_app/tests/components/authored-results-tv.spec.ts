import { expect, test } from '../helpers/cookie-audit';
import {
  authoredChild, openAuthoredComponent, isolateAuthoredImages,
  assertReadableAuthoredBounds, authoredCapture,
} from '../helpers/authored-result-fixtures';

// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1100]) for (const theme of ['light', 'dark'] as const) {
  // contract-test: supporting surface=gui.web assertions=tv-titles.authoring.relevant-and-flexible,tv-titles.presentation.posters-and-details,authored-results.facts.provenance-and-drafts
  test(`supplied movie retains its poster, source score and facts at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await isolateAuthoredImages(page);
    const child = authoredChild('tv.movie');
    await openAuthoredComponent(page, 'tv/TVTitleEmbedPreview', { width, theme, context: 'chat',
      props: { id: child.embed_id, content: child.content, isMobile: width === 390 } });
    const preview = page.getByTestId('embed-preview');
    const card = preview.getByTestId('result-card-content');
    await expect(card).toBeVisible();
    await expect(preview).toHaveCSS('border-radius', '30px');
    await expect(card.getByTestId('tv-title')).toHaveText('Supplied: tv.movie');
    const media = card.getByTestId('result-card-media');
    const mediaBounds = await media.boundingBox();
    const cardBounds = await card.boundingBox();
    expect(mediaBounds).not.toBeNull();
    expect(cardBounds).not.toBeNull();
    if (width === 1100) {
      // Existing wide cards reserve one third for copy, two thirds for media.
      expect(mediaBounds!.x - cardBounds!.x).toBeCloseTo(cardBounds!.width / 3, 0);
      expect(mediaBounds!.width).toBeCloseTo(cardBounds!.width * 2 / 3, 0);
    } else {
      await expect(preview).toHaveCSS('width', '150px');
      expect(mediaBounds!.width).toBeCloseTo(cardBounds!.width, 0);
    }
    await expect(page.getByTestId('tv-preview-facts')).toContainText('2026');
    await expect(page.getByTestId('tv-preview-facts')).toContainText('112');
    await expect(page.getByTestId('tv-preview-score')).toContainText('8.2 / 10');
    await expect(page.getByTestId('tv-preview-score')).toContainText('Supplied score');
    await expect(page.getByTestId('authored-result-origin')).toHaveText('User-provided');
    const poster = page.getByTestId('tv-poster');
    await expect(poster).toBeVisible();
    await expect(poster).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => poster.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await assertReadableAuthoredBounds(page, page.getByTestId('embed-preview'));
    await authoredCapture(page, testInfo, `movie-card-${width}-${theme}`);

    await openAuthoredComponent(page, 'tv/TVTitleEmbedFullscreen', { width, theme,
      props: { embedId: child.embed_id, data: { decodedContent: child.content } } });
    const shell = page.getByTestId('embed-fullscreen-overlay');
    const result = shell.getByTestId('result-embed-content');
    await expect(result).toHaveClass(/immersive/);
    await expect(result.getByTestId('result-facts').getByTestId('tv-runtime')).toBeVisible();
    await expect(result.getByTestId('result-media').getByTestId('tv-fullscreen-poster')).toBeVisible();
    await expect(shell.getByTestId('embed-fixed-bottom')).toBeVisible();
    await expect(result.getByTestId('tv-title-fullscreen')).toBeVisible();
    await expect(page.getByTestId('tv-synopsis')).toHaveText('A supplied film synopsis.');
    await expect(page.getByTestId('tv-runtime')).toContainText('112');
    await expect(page.getByTestId('tv-metadata')).toContainText('Example Director');
    await expect(page.getByTestId('tv-metadata')).toContainText('Example Actor');
    await expect(page.getByTestId('tv-score-source').getByRole('link')).toHaveAttribute('href', 'https://example.org/movie-score');
    await expect(page.getByTestId('tv-open-source')).toHaveAttribute('href', 'https://example.org/movie');
    await expect(page.getByTestId('authored-result-context').getByRole('link')).toHaveAttribute('href', 'https://example.org/reference');
    await expect(page.getByTestId('tv-fullscreen-poster')).toHaveCSS('object-fit', 'contain');
    await assertReadableAuthoredBounds(page, page.getByTestId('tv-title-fullscreen'));
    await authoredCapture(page, testInfo, `movie-fullscreen-${width}-${theme}`);
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.series.supplied-seasons,tv-titles.presentation.posters-and-details,authored-results.content.typed-and-useful
  test(`series preserves specials and an explicitly partial supplied season guide at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await isolateAuthoredImages(page);
    const child = authoredChild('tv.series');
    await openAuthoredComponent(page, 'tv/TVTitleEmbedFullscreen', { width, theme,
      props: { embedId: child.embed_id, data: { decodedContent: child.content } } });
    const result = page.getByTestId('embed-fullscreen-overlay').getByTestId('result-embed-content');
    await expect(result).toHaveClass(/immersive/);
    await expect(result.getByTestId('result-facts').getByTestId('tv-season-total')).toBeVisible();
    await expect(result.getByTestId('result-media').getByTestId('tv-fullscreen-poster')).toBeVisible();
    await expect(page.getByTestId('tv-synopsis')).toHaveText('A supplied series synopsis.');
    await expect(page.getByTestId('tv-season-total')).toContainText('4');
    await expect(page.getByTestId('tv-episode-total')).toContainText('30');
    await expect(page.getByTestId('tv-season')).toHaveCount(2);
    const specials = page.locator('[data-testid="tv-season"][data-season-number="0"]');
    await expect(specials).toContainText('Specials');
    await expect(specials).toContainText('2');
    await expect(page.locator('[data-testid="tv-season"][data-season-number="1"]')).toContainText('Supplied first-season synopsis.');
    await expect(page.getByTestId('tv-partial-guide')).toBeVisible();
    await expect(page.getByTestId('tv-partial-guide')).toContainText(/supplied|partial|complete/i);
    await expect(page.getByTestId('tv-score')).toHaveCount(0);
    await expect(page.getByTestId('tv-score-source')).toHaveCount(0);
    await expect(page.getByTestId('tv-title-fullscreen')).not.toContainText(/Netflix|Prime Video|Disney|Season 2|Season 3|Season 4/);
    await assertReadableAuthoredBounds(page, page.getByTestId('tv-title-fullscreen'));
    await authoredCapture(page, testInfo, `series-specials-partial-${width}-${theme}`);
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.presentation.posters-and-details,tv-titles.lifecycle.groups-and-actions,authored-results.media.safe-and-attributed
  test(`missing TV facts and failed poster stay readable without fabricated actions at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await isolateAuthoredImages(page, true);
    const child = authoredChild('tv.movie');
    await openAuthoredComponent(page, 'tv/TVTitleEmbedFullscreen', { width, theme,
      props: { embedId: child.embed_id, data: { decodedContent: child.content } } });
    await expect(page.getByTestId('tv-poster-fallback')).toBeVisible();
    await expect(page.getByTestId('tv-synopsis')).toHaveText('A supplied film synopsis.');
    await authoredCapture(page, testInfo, `movie-failed-poster-${width}-${theme}`);
    for (const variant of ['unknownMovie', 'unknownSeries']) {
      await openAuthoredComponent(page, 'tv/TVTitleEmbedFullscreen', { width, theme, variant });
      // The metadata region has no rendered facts for a title-only movie.
      // Readability belongs to the real shell, title and fallback instead.
      const fullscreen = page.getByTestId('embed-fullscreen-overlay');
      await expect(fullscreen).toBeVisible();
      await expect(fullscreen.getByTestId('embed-header-title')).toHaveText(variant === 'unknownMovie' ? 'A supplied movie title' : 'A supplied series title');
      await expect(fullscreen.getByTestId('authored-result-origin')).toHaveText('User-provided');
      for (const id of ['tv-year', 'tv-runtime', 'tv-score', 'tv-season-total', 'tv-episode-total', 'tv-seasons', 'tv-open-source']) {
        await expect(page.getByTestId(id), `${variant}: absent facts stay absent`).toHaveCount(0);
      }
      await expect(page.getByTestId('tv-poster-fallback')).toBeVisible();
      await expect(fullscreen).not.toContainText(/0 min|0 seasons|0 episodes|0 \/ 10|Netflix|IMDb/);
      await assertReadableAuthoredBounds(page, fullscreen);
      if (variant === 'unknownSeries') await expect(fullscreen.getByTestId('tv-synopsis')).toHaveText('Only this synopsis was supplied.');
      else await expect(fullscreen.getByTestId('tv-synopsis')).toHaveCount(0);
      await authoredCapture(page, testInfo, `${variant}-missing-facts-${width}-${theme}`);
    }
  });
}
