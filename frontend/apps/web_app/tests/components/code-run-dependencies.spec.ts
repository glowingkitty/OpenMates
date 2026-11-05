// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.setTimeout(90_000);

// Frozen regression metadata: registry latest cannot install on sandbox Python 3.11.
// This spec proves the real component's request construction, not sandbox execution.
const packages = [
  { package: 'sympy', import_name: 'sympy', latest_version: '1.14.0' },
  { package: 'numpy', import_name: 'numpy', latest_version: '2.5.4', requires_python: '>=3.12' },
  { package: 'matplotlib', import_name: 'matplotlib.pyplot', latest_version: '3.10.8' },
  { package: 'ipython', import_name: 'IPython.display', latest_version: '9.7.0' },
];

// contract-test: supporting surface=gui.web assertions=code-run.request.validated,code-run.gui.split-layout-width
test('Python imports default to compatible resolution and retain explicit version choices', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const query = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: '1200', chrome: '0' });
  await page.goto(`/dev/preview/embeds/code/CodeEmbedFullscreen?${query}`);
  await waitForComponentPreview(page, 60_000);
  await expect(page.getByTestId('code-fullscreen-code')).toContainText('interface Props');

  await page.route('**/v1/code/run/prepare', route => route.fulfill({ json: {
    dependency_suggestions: packages.map(pkg => ({
      ...pkg, ecosystem: 'python', source: 'pypi',
      latest_released_at: '2026-10-20T00:00:00Z',
      versions: [{ version: pkg.latest_version, released_at: '2026-10-20T00:00:00Z' },
        ...(pkg.package === 'numpy' ? [{ version: '2.4.6', released_at: '2026-09-01T00:00:00Z' }] : [])],
    })),
  } }));
  await page.route('**/v1/code/run', route => route.fulfill({ status: 400, json: { detail: 'Component request captured; no sandbox started' } }));

  for (const choice of ['automatic', '2.4.6', '2.5.4']) {
    query.set('variant', 'pythonDependencies');
    await page.goto(`/dev/preview/embeds/code/CodeEmbedFullscreen?${query}`);
    await waitForComponentPreview(page, 60_000);
    const prepareRequest = page.waitForRequest('**/v1/code/run/prepare');
    await page.getByTestId('embed-run-button').click();
    expect((await prepareRequest).postDataJSON().client_files[0].code).toContain('from IPython.display import display');
    const selection = page.getByTestId('code-run-file-selection');
    await expect(selection).toBeVisible();
    for (const pkg of packages) {
      const row = selection.getByRole('switch').filter({ has: page.locator('.code-run-file-title', { hasText: new RegExp(`^${pkg.package}$`) }) });
      await expect(row).toHaveAttribute('aria-checked', 'true');
      await expect(row.locator('.download')).toBeVisible();
      await expect(row.getByRole('combobox')).toHaveValue('automatic');
    }
    const versions = selection.getByRole('combobox', { name: 'numpy · Version', exact: true });
    await versions.focus();
    await expect(versions).toBeFocused();
    await expect(versions.locator('option')).toHaveText(['Automatic (compatible)', /2.5.4/, /2.4.6/]);
    await versions.selectOption('2.4.6');
    await expect(versions).toHaveValue('2.4.6');
    await versions.selectOption(choice);
    await expect(versions).toHaveValue(choice);
    const row = versions.locator('xpath=ancestor::button');
    await expect(row).toHaveAttribute('aria-checked', 'true');
    await row.hover();
    const bounds = await versions.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(1280);
    await test.step(`dependency selection ready: ${choice}`, async () => {
      await expect(selection.getByTestId('code-run-continue')).toBeEnabled();
      await testInfo.attach(`dependency-selection-${choice}`, { body: await selection.screenshot(), contentType: 'image/png' });
    });
    const request = page.waitForRequest('**/v1/code/run');
    await selection.getByTestId('code-run-continue').click();
    const payload = (await request).postDataJSON();
    expect(payload.dependency_installs).toEqual(packages.map(pkg => ({
      ecosystem: 'python',
      packages: [pkg.package === 'numpy' && choice !== 'automatic' ? `numpy==${choice}` : pkg.package],
    })));
    expect(payload.client_files[0].filename).toBe('math_demo.py');
  }
});
