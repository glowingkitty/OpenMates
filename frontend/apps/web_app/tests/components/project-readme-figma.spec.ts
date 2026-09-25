const requireFromHere = process.getBuiltinModule('node:module').createRequire(import.meta.url);
const { mkdir } = requireFromHere('node:fs/promises') as typeof import('node:fs/promises');
const path = requireFromHere('node:path') as typeof import('node:path');
const { expect, test } = requireFromHere('@playwright/test') as typeof import('@playwright/test');
const { waitForComponentPreview } = requireFromHere('../helpers/component-preview') as typeof import('../helpers/component-preview');

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/ProjectReadme?theme=light&background=%23dbeafe&chrome=0';
const EVIDENCE_DIR = path.resolve(import.meta.dirname, '../../../../../test-results/figma/projects-redesign/rendered');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('project-readme-action', (event) => {
      const actions = JSON.parse(document.documentElement.dataset.projectReadmeActions || '[]');
      actions.push((event as CustomEvent<string>).detail);
      document.documentElement.dataset.projectReadmeActions = JSON.stringify(actions);
    }, true);
  });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.files.no-server-decryption-authority
test('renders GitHub-like README content with safe images', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${PREVIEW}&width=920`);
  await waitForComponentPreview(page);

  const root = page.getByTestId('project-readme');
  await expect(root).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.uiFont)).toBe('lexend');
  const loadedFont = await page.evaluate(async () => {
    const faces = await document.fonts.load('500 16px "Lexend Deca Variable"');
    return { count: faces.length, ready: document.fonts.check('500 16px "Lexend Deca Variable"') };
  });
  expect(loadedFont.count).toBeGreaterThan(0);
  expect(loadedFont.ready).toBe(true);
  await expect(root).toHaveCSS('font-family', /Lexend Deca/);
  await expect(root.getByRole('heading', { name: 'Aurora project' })).toBeVisible();
  await expect(root.getByRole('table')).toBeVisible();
  await expect(root.locator('pre code')).toContainText('pnpm dev');
  const image = root.getByRole('img', { name: 'Project overview' });
  await expect(image).toHaveAttribute('src', '/favicon.png');
  await expect(root.locator('script')).toHaveCount(0);
  expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'project-readme-rendered.png'), fullPage: true });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('empty overview exposes keyboard-safe Upload and Create callbacks', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&variant=empty&width=350`);
  await waitForComponentPreview(page);

  const empty = page.getByTestId('project-readme-empty');
  await expect(empty).toContainText('No project overview created yet.');
  const upload = page.getByTestId('project-readme-upload');
  const create = page.getByTestId('project-readme-create');
  await expect(upload.locator('.tray-icon.upload-icon')).toBeVisible();
  await expect(create.locator('.clickable-icon.icon_create')).toBeVisible();
  for (const action of [upload, create]) {
    const icon = action.locator('.readme-action-icon');
    const label = action.locator('span').last();
    await expect(action).toHaveCSS('box-shadow', 'none');
    await expect(icon).toHaveCSS('box-shadow', 'none');
    await expect(icon).toHaveCSS('filter', 'none');
    const iconBox = await icon.boundingBox();
    const labelBox = await label.boundingBox();
    expect(iconBox).not.toBeNull();
    expect(labelBox).not.toBeNull();
    expect(Math.abs(iconBox!.x + iconBox!.width / 2 - labelBox!.x - labelBox!.width / 2)).toBeLessThanOrEqual(1);
    expect(iconBox!.y + iconBox!.height).toBeLessThan(labelBox!.y);
  }
  await mkdir(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'project-readme-empty.png'), fullPage: true });
  await upload.focus();
  await expect(upload).toBeFocused();
  await page.keyboard.press('Enter');
  await create.click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectReadmeActions)).toBe('["upload","create"]');
  expect(await empty.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('shows a retry without offering a conflicting README when source access fails', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=error&width=720`);
  await waitForComponentPreview(page);

  await expect(page.getByTestId('project-readme-error')).toContainText('Could not load the connected README.');
  await expect(page.getByTestId('project-readme-upload')).toHaveCount(0);
  await expect(page.getByTestId('project-readme-create')).toHaveCount(0);
  await page.getByTestId('project-readme-retry').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectReadmeActions)).toBe('["retry"]');
});

// contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.surface.semantic-parity
test('sanitizes executable markup, proxies remote images, and blocks unresolved relative loads', async ({ page }) => {
  const state = {
    status: 'ready',
    document: {
      path: 'README.md',
      origin: 'connected',
      imageUrls: {},
      content: '# Safe\n\n<script>window.projectReadmePwned = true</script>\n\n![Remote](https://cdn.example.test/readme.png)\n\n![Private](../private.png)',
    },
  };
  const props = encodeURIComponent(JSON.stringify({ state }));
  await page.goto(`${PREVIEW}&width=720&props=${props}`);
  await waitForComponentPreview(page);

  const root = page.getByTestId('project-readme');
  await expect(root.locator('script')).toHaveCount(0);
  await expect(root.getByRole('img', { name: 'Remote' })).toHaveAttribute('src', /\/api\/v1\/image\?/);
  await expect(root).toContainText('[Image: Private]');
  expect(await page.evaluate(() => (window as Window & { projectReadmePwned?: boolean }).projectReadmePwned)).toBeUndefined();
});
