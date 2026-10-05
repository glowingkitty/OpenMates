import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const summary = { title: 'Ada Lovelace', canonical_title: 'Ada_Lovelace', language: 'en',
  extract: 'Ada Lovelace explored how the analytical engine could manipulate symbols.',
  description: 'English mathematician', source_url: 'https://en.wikipedia.org/wiki/Ada_Lovelace' };
const guide = { canonical_title: 'Ada Lovelace', language: 'en', source_url: summary.source_url,
  expires_in_seconds: 86400,
  questions: ['How did Ada Lovelace contribute to computing?', 'How did her work connect to Charles Babbage?', 'Ask me to recall one idea from her notes.'],
  related_articles: [{ title: 'Charles Babbage', canonical_title: 'Charles Babbage', language: 'en', description: 'Mathematician and inventor' }] };
const preview = (variant = '', width = 1280) => `/dev/preview/embeds/wiki/WikipediaFullscreen?theme=light&background=%23dbeafe&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;

test.beforeEach(async ({ page }) => {
  test.setTimeout(60000); // Includes cold Vite mounting and both responsive profiles.
  await page.addInitScript(() => {
    (window as unknown as { wikiActions: unknown[] }).wikiActions = [];
    document.addEventListener('preview-wiki-action', event => {
      (window as unknown as { wikiActions: unknown[] }).wikiActions.push((event as CustomEvent).detail);
    });
  });
  await page.route('**/v1/wikipedia/summary?**', route => route.fulfill({ json: summary }));
  await page.route('**/v1/wikipedia/learning?**', route => route.fulfill({ json: guide }));
});

test.describe('Wiki learning fullscreen', () => {
  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  test('article, questions, related topics and saved-goal controls fit laptop and phone', async ({ page }) => {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(preview('', width));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText('Ada Lovelace');
      await expect(page.getByTestId('wiki-question')).toHaveCount(3);
      await expect(page.getByTestId('wiki-related-article')).toContainText('Charles Babbage');
      await expect(page.getByTestId('wiki-save-interest')).toBeEnabled();
      await expect(page.locator('[data-skill-icon="study"]').first()).toBeVisible();
      await page.getByTestId('wiki-question').first().hover();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`wiki-learning-${width}.png`), fullPage: true });
      await page.getByTestId('wiki-question').first().focus();
      await expect(page.getByTestId('wiki-question').first()).toBeFocused();
      await page.getByTestId('wiki-save-interest').click();
      await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
      await page.getByRole('button', { name: 'Edit learning goal', exact: true }).click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: string }[] }).wikiActions.find(x => x.action === 'edit')?.value)).toBe('preview-study-goal');
      await page.getByTestId('wiki-related-article').click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: { canonical_title: string } }[] }).wikiActions.find(x => x.action === 'related')?.value.canonical_title)).toBe('Charles Babbage');
    }
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  test('the article and saving stay available while questions load', async ({ page }) => {
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/v1/wikipedia/learning?**', async route => {
      await pending;
      await route.fulfill({ json: guide });
    });
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-guide-loading')).toBeVisible();
    await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText('Ada Lovelace');
    await page.getByTestId('wiki-save-interest').click();
    await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
    release();
    await expect(page.getByTestId('wiki-question')).toHaveCount(3);
    await expect(page.getByTestId('wiki-guide-loading')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  test('a question closes only after accepted submission and repeated taps send once', async ({ page }) => {
    await page.goto(preview('pendingSend'));
    await waitForComponentPreview(page);
    const question = page.getByTestId('wiki-question').first();
    await question.click();
    await expect(question).toBeDisabled();
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'send').length)).toBe(1);
    expect(await page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'close').length)).toBe(0);
    await page.evaluate(() => document.dispatchEvent(new Event('preview-wiki-resolve-send')));
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'close').length)).toBe(1);
    await page.goto(preview('failedSend'));
    await waitForComponentPreview(page);
    await page.getByTestId('wiki-question').first().click();
    await expect(page.getByRole('alert')).toContainText('could not be sent');
    await expect(page.getByTestId('wiki-fullscreen-title')).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.length)).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.public-cache,wikipedia-mentions.learning.chat-and-memory
  test('provider failure retains the article and saving; retry loads questions; guests can sign in', async ({ page }) => {
    let requests = 0;
    await page.route('**/v1/wikipedia/learning?**', async route => {
      requests++;
      if (requests === 1) await route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
      else await route.fulfill({ json: guide });
    });
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-guide-retry')).toBeVisible();
    await expect(page.getByTestId('wiki-fullscreen-title')).toBeVisible();
    await expect(page.getByTestId('wiki-save-interest')).toBeEnabled();
    await page.getByTestId('wiki-guide-retry').click();
    await expect(page.getByTestId('wiki-question')).toHaveCount(3);
    await page.goto(preview('signedOut'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-learning-login')).toBeVisible();
    await expect(page.getByTestId('wiki-question')).toHaveCount(0);
    await expect(page.getByTestId('wiki-save-interest')).toHaveCount(0);
    await page.getByTestId('wiki-learning-login').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.at(-1)?.action)).toBe('login');
    expect(requests).toBe(2);
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.links.name-consistency
  test('mismatched link names stay plain text and redirects with another name fail closed', async ({ page }) => {
    await page.goto('/dev/preview/embeds/wiki/WikiInlineLink?chrome=0&variant=wrongName');
    await waitForComponentPreview(page);
    await expect(page.getByText('Einstein', { exact: true })).toBeVisible();
    await expect(page.getByTestId('component-preview-canvas').getByRole('link')).toHaveCount(0);
    await expect(page.getByTestId('wiki-inline-link')).toHaveCount(0);
    await page.goto('/dev/preview/embeds/wiki/WikiInlineLink?chrome=0&variant=disambiguation');
    await waitForComponentPreview(page);
    await expect(page.getByRole('link', { name: 'Mercury' })).toBeVisible();
    await page.evaluate(() => document.addEventListener('wikifullscreen', event => {
      (window as unknown as { wikiClicked: unknown }).wikiClicked = (event as CustomEvent).detail;
    }, { once: true }));
    await page.getByRole('link', { name: 'Mercury' }).focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiClicked: { wikiTitle: string } }).wikiClicked?.wikiTitle)).toBe('Mercury_(planet)');
    await page.route('**/v1/wikipedia/summary?**', route => route.fulfill({ json: { ...summary, title: 'Charles Babbage' } }));
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-question')).toHaveCount(0);
    await expect(page.getByTestId('wiki-learning')).toHaveCount(0);
    await expect(page.getByText('Article not found', { exact: true })).toBeVisible();
  });
});
