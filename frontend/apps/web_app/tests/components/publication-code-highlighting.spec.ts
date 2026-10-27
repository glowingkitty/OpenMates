import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'publication-code-highlighting', title: 'Publication syntax colors', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'landing.dev.openmates.org',
  transcript: [
    { id: 'light', text: 'Publication code uses readable syntax colors in the light theme. Long lines scroll inside their code block.', checkpoint: 'light', devices: ['web-phone', 'web-laptop'] },
    { id: 'dark', text: 'The dark theme preserves distinct syntax colors and safely displays unknown languages as plain text.', checkpoint: 'dark', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'publication-code-light', checkpoint: 'light', visual: 'TypeScript, Python, shell, and JSON tokens have distinct colors; long code stays within the article.', devices: ['web-phone', 'web-laptop'] },
    { id: 'publication-code-dark', checkpoint: 'dark', visual: 'Dark-theme code remains colored and readable, and HTML inside unknown-language code is inert text.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2200 },
});

for (const { width, height, device } of [
  { width: 390, height: 844, device: 'web-phone' },
  { width: 1512, height: 1000, device: 'web-laptop' },
]) {
  // contract-test: supporting surface=gui.web assertions=public-publications.content.media-groups,public-publications.authoring.public-boundary
  test(`publication code colors and scrolling (${device})`, async ({ page }, testInfo) => {
    test.setTimeout(75_000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height });
    const proof = createVideoProofRuntime(proofContract, {
      device, attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot(),
    });
    for (const theme of ['light', 'dark']) {
      await page.goto(`/dev/preview/newsroom/PublicNewsroomPreview?${new URLSearchParams({
        chrome: '0', theme, background: theme === 'light' ? '#dbeafe' : '#171717',
        width: String(width), variant: 'Code highlighting',
      })}`, { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const article = page.locator('.article-markdown');
      await expect(article).toBeVisible();
      await expect(article.locator('pre')).toHaveCount(6);
      await proof.assert(`publication-code-${theme}`, async () => {
        for (const [language, token] of [
          ['typescript', '.hljs-keyword'], ['python', '.hljs-keyword'],
          ['bash', '.hljs-string'], ['json', '.hljs-number'],
        ]) {
          const code = article.locator(`code.language-${language}`).first();
          const foreground = await code.evaluate(node => getComputedStyle(node).color);
          const syntax = code.locator(token).first();
          await expect(syntax).toBeAttached();
          const color = await syntax.evaluate(node => getComputedStyle(node).color);
          expect(color).not.toBe(foreground);
          // Verify the actual web-app keyword palette rather than only span markup.
          if (token === '.hljs-keyword') {
            expect(color).toBe(theme === 'light' ? 'rgb(215, 58, 73)' : 'rgb(255, 123, 114)');
          }
        }
        const plain = article.locator('code.language-unknown-language');
        await expect(plain).toContainText('<script>alert(');
        await expect(plain.locator('script, img, span')).toHaveCount(0);
        const wide = article.locator('pre').last();
        await wide.scrollIntoViewIfNeeded();
        const geometry = await wide.evaluate(node => ({
          client: node.clientWidth, scroll: node.scrollWidth,
          left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right,
          overflow: getComputedStyle(node).overflowX,
        }));
        expect(geometry.scroll).toBeGreaterThan(geometry.client);
        expect(geometry.overflow).toBe('auto');
        expect(geometry.left).toBeGreaterThanOrEqual(0);
        expect(geometry.right).toBeLessThanOrEqual(width);
        await wide.evaluate(node => { node.scrollLeft = 180; });
        expect(await wide.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
        await wide.evaluate(node => { node.scrollLeft = 0; });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
        await article.locator('pre').first().scrollIntoViewIfNeeded();
      });
      await proof.checkpoint(theme);
    }
    expect(errors).toEqual([]);
    await proof.attach();
  });
}
