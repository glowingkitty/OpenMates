import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const summary = { title: 'Ada Lovelace', canonical_title: 'Ada_Lovelace', language: 'en',
  extract: 'Ada Lovelace explored how the analytical engine could manipulate symbols.',
  description: 'English mathematician', source_url: 'https://en.wikipedia.org/wiki/Ada_Lovelace' };
const guide = { canonical_title: 'Ada Lovelace', language: 'en', source_url: summary.source_url,
  expires_in_seconds: 86400,
  questions: ['How did Ada Lovelace contribute to computing?', 'How did her work connect to Charles Babbage?', 'Ask me to recall one idea from her notes.'],
  related_articles: [
    { title: 'Charles Babbage', canonical_title: 'Charles Babbage', language: 'en', description: 'Mathematician and inventor', thumbnail_url: 'https://upload.wikimedia.org/babbage.jpg' },
    { title: 'Analytical engine', canonical_title: 'Analytical engine', language: 'en', description: 'Mechanical general-purpose computer' },
    { title: 'Algorithm', canonical_title: 'Algorithm', language: 'en', description: 'Sequence of instructions' },
  ] };
const preview = (variant = '', width = 1280) => `/dev/preview/embeds/wiki/WikipediaFullscreen?theme=light&background=%23dbeafe&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;

test.beforeEach(async ({ page }) => {
  test.setTimeout(60000); // Includes cold Vite mounting and both responsive profiles.
  await page.addInitScript(() => {
    (window as unknown as { wikiActions: unknown[] }).wikiActions = [];
    document.addEventListener('preview-wiki-action', event => {
      (window as unknown as { wikiActions: unknown[] }).wikiActions.push((event as CustomEvent).detail);
    });
  });
  await page.route('**/api/v1/image?**', route => route.fulfill({ path: 'static/store-examples/home-1.webp', contentType: 'image/webp', headers: { 'Access-Control-Allow-Origin': '*' } }));
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
      const attribution = page.getByTestId('wiki-source-attribution');
      await expect(attribution).toHaveCount(1);
      await expect(attribution).toContainText('Source: Wikipedia');
      const sourcePlacement = await page.getByTestId('wiki-fullscreen-content').evaluate(element => {
        const extract = element.querySelector('[data-testid="wiki-fullscreen-extract"]')!.getBoundingClientRect();
        const source = element.querySelector('[data-testid="wiki-source-attribution"]')!.getBoundingClientRect();
        const learning = element.querySelector('[data-testid="wiki-learning"]')!.getBoundingClientRect();
        return { belowArticle: source.top >= extract.bottom, aboveLearning: source.bottom <= learning.top };
      });
      expect(sourcePlacement).toEqual({ belowArticle: true, aboveLearning: true });
      const learning = page.getByTestId('wiki-learning');
      await expect(learning.getByRole('heading', { name: 'Learn more', level: 3 })).toBeVisible();
      const sectionHeading = learning.locator('.settings-section-heading');
      await expect(sectionHeading.locator('.heading-bar')).toBeVisible();
      await expect(sectionHeading.locator('.heading-bar')).toHaveCSS('height', '4px');
      const headingIcon = await sectionHeading.locator('.heading-icon').evaluate(element => {
        const expected = document.createElement('span');
        expected.style.maskImage = getComputedStyle(element).getPropertyValue('--icon-url-study').trim();
        return { expected: expected.style.maskImage, actual: getComputedStyle(element, '::after').maskImage };
      });
      expect(headingIcon.expected).not.toBe('');
      expect(headingIcon.actual).toBe(headingIcon.expected);
      expect(await sectionHeading.evaluate(element => element.getBoundingClientRect().right <= innerWidth)).toBe(true);
      await page.getByTestId('wiki-fullscreen-extract').scrollIntoViewIfNeeded();
      await expect(attribution).toBeInViewport();
      await expect(learning.getByRole('heading', { name: 'Learn more', level: 3 })).toBeInViewport();
      await page.screenshot({ path: test.info().outputPath(`wiki-source-${width}.png`), fullPage: true });
      await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(3);
      const relatedRow = page.getByTestId('wiki-related-articles');
      const relatedCards = page.getByTestId('wiki-related-article');
      await expect(relatedCards).toHaveCount(3);
      await expect(relatedCards.first().getByTestId('embed-preview')).toHaveAttribute('data-app-id', 'study');
      await expect(relatedCards.first()).toContainText('Charles Babbage');
      await expect(relatedCards.first().locator('img')).toHaveAttribute('src', /api.*image/);
      await expect(relatedCards.first().locator('.basic-infos-bar')).toContainText('Wikipedia');
      const rowLayout = await relatedRow.evaluate(element => {
        const cards = Array.from(element.children).map(card => card.getBoundingClientRect());
        return { scrollable: element.scrollWidth > element.clientWidth, sameRow: cards.every(card => Math.abs(card.top - cards[0].top) < 1), contained: element.getBoundingClientRect().right <= innerWidth };
      });
      expect(rowLayout).toEqual({ scrollable: true, sameRow: true, contained: true });
      await relatedRow.focus();
      await page.keyboard.press('ArrowRight');
      await expect.poll(() => relatedRow.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
      await relatedCards.last().getByRole('button').focus();
      await expect(relatedCards.last().getByRole('button')).toBeFocused();
      await page.keyboard.press('Enter');
      await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: { canonical_title: string } }[] }).wikiActions.find(x => x.action === 'related')?.value.canonical_title)).toBe('Algorithm');
      await page.evaluate(() => { (window as unknown as { wikiActions: unknown[] }).wikiActions = []; });
      await expect(page.getByTestId('wiki-save-interest')).toBeEnabled();
      await expect(page.locator('[data-skill-icon="study"]').first()).toBeVisible();
      await page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first().hover();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`wiki-learning-${width}.png`), fullPage: true });
      await page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first().focus();
      await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first()).toBeFocused();
      await page.getByTestId('wiki-save-interest').click();
      await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
      await page.getByRole('button', { name: 'Edit learning goal', exact: true }).click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: string }[] }).wikiActions.find(x => x.action === 'edit')?.value)).toBe('preview-study-goal');
      await relatedCards.first().getByRole('button').click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: { canonical_title: string } }[] }).wikiActions.find(x => x.action === 'related')?.value.canonical_title)).toBe('Charles Babbage');
    }
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  test('the article and saving stay available; suggestions fade in without a loading indicator', async ({ page }) => {
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/v1/wikipedia/learning?**', async route => {
      await pending;
      await route.fulfill({ json: guide });
    });
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-guide-loading')).toHaveCount(0);
    await expect(page.getByText('Loading questions…', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('wiki-questions')).toHaveCount(0);
    await expect(page.getByTestId('wiki-related-articles')).toHaveCount(0);
    await page.evaluate(() => {
      document.addEventListener('animationstart', event => {
        const target = event.target as HTMLElement;
        if (target.dataset.testid === 'wiki-guide-ready') {
          (window as unknown as { wikiGuideFade: { opacity: number; keyframes: Keyframe[] } }).wikiGuideFade = {
            opacity: Number(getComputedStyle(target).opacity),
            keyframes: target.getAnimations()[0].effect!.getKeyframes(),
          };
        }
      });
    });
    await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText('Ada Lovelace');
    await page.getByTestId('wiki-save-interest').click();
    await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
    release();
    await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(3);
    await expect(page.getByTestId('wiki-guide-loading')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiGuideFade?: unknown }).wikiGuideFade)).toBeTruthy();
    const fade = await page.evaluate(() => (window as unknown as { wikiGuideFade: { opacity: number; keyframes: Keyframe[] } }).wikiGuideFade);
    expect(fade.opacity).toBeLessThan(1);
    expect(fade.keyframes[0].opacity).toBe('0');
    expect(fade.keyframes.at(-1)!.opacity).toBe('1');
    await expect(page.getByTestId('wiki-guide-ready')).toHaveCSS('opacity', '1');
    const suggestions = page.getByTestId('wiki-questions');
    await expect(suggestions.getByTestId('suggestions-wrapper')).toHaveCSS('align-items', 'flex-end');
    await expect(suggestions.getByTestId('follow-up-suggestion-item').first()).toHaveCSS('border-style', 'none');
    await expect(suggestions.locator('.suggestion-enter-icon')).toHaveCount(3);
  });

  // contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  test('a question closes only after accepted submission and repeated taps send once', async ({ page }) => {
    const exactQuestion = '[Question] How do x<y> and x>y differ?';
    await page.route('**/v1/wikipedia/learning?**', route => route.fulfill({
      json: { ...guide, questions: [exactQuestion, ...guide.questions.slice(1)] },
    }));
    await page.goto(preview('pendingSend'));
    await waitForComponentPreview(page);
    const question = page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first();
    await expect(question).toHaveText(exactQuestion);
    await question.click();
    await expect(question).toBeDisabled();
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'send').length)).toBe(1);
    expect(await page.evaluate(() => (window as unknown as { wikiActions: { action: string; value: string }[] }).wikiActions.find(x => x.action === 'send')?.value)).toBe(exactQuestion);
    expect(await page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'close').length)).toBe(0);
    await page.evaluate(() => document.dispatchEvent(new Event('preview-wiki-resolve-send')));
    await expect.poll(() => page.evaluate(() => (window as unknown as { wikiActions: { action: string }[] }).wikiActions.filter(x => x.action === 'close').length)).toBe(1);
    await page.goto(preview('failedSend'));
    await waitForComponentPreview(page);
    await page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first().click();
    await expect(page.getByRole('alert')).toContainText('could not be sent');
    await expect(page.getByTestId('wiki-fullscreen-title')).toBeVisible();
    await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item').first()).toBeEnabled();
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
    await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(3);
    await page.goto(preview('signedOut'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('wiki-learning-login')).toBeVisible();
    await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(0);
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
    await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(0);
    await expect(page.getByTestId('wiki-learning')).toHaveCount(0);
    await expect(page.getByText('Article not found', { exact: true })).toBeVisible();
  });
});

// contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
test('shared follow-ups retain chat dismissal and filtering; disabled prompts do not send', async ({ page }) => {
  await page.goto('/dev/preview/FollowUpSuggestions?chrome=0');
  await waitForComponentPreview(page);
  const prompts = page.getByTestId('follow-up-suggestion-item');
  await expect(prompts).toHaveCount(4);
  await prompts.first().click();
  await expect(page.getByTestId('suggestions-wrapper')).toHaveCSS('opacity', '0');
  await page.goto('/dev/preview/FollowUpSuggestions?chrome=0&variant=disabled');
  await waitForComponentPreview(page);
  await expect(prompts.first()).toBeDisabled();
  await page.goto('/dev/preview/FollowUpSuggestions?chrome=0&variant=filtering');
  await waitForComponentPreview(page);
  await expect(prompts).toHaveText(['Compare their approaches.']);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
test('wiki suggestions and cards remain readable in dark mode with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(preview('', 390).replace('theme=light', 'theme=dark'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('wiki-questions').getByTestId('follow-up-suggestion-item')).toHaveCount(3);
  await expect(page.getByTestId('wiki-guide-ready')).toHaveCSS('animation-name', 'none');
  await expect(page.getByTestId('wiki-guide-ready')).toHaveCSS('opacity', '1');
  const card = page.getByTestId('wiki-related-article').first().getByRole('button');
  await card.scrollIntoViewIfNeeded();
  await expect(card).toBeVisible();
  const colors = await card.evaluate(element => ({ color: getComputedStyle(element.querySelector('p')!).color, background: getComputedStyle(element).backgroundColor }));
  expect(colors.color).not.toBe(colors.background);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
