import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const base = (dir: string, name: string) => `/dev/preview/embeds/${dir}/${name}?chrome=0&theme=light&width=420`;
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, url: string) {
  await page.goto(url);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen,contracts.ui.human-readable-default
test('specification skill preview shows a readable draft card', async ({ page }, testInfo) => {
  await open(page, base('specifications', 'SpecificationSkillEmbedPreview'));
  const card = page.getByTestId('specification-embed-card');
  await expect(card).toContainText('Shared shopping lists');
  await expect(card.getByTestId('specification-status')).toContainText('Draft');
  await expect(card.getByTestId('specification-proof-summary')).toContainText('3');
  await testInfo.attach('spec-skill-preview', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen,contracts.ui.human-readable-default
test('specification skill fullscreen shows the unsaved-draft notice, requirements and flows', async ({ page }, testInfo) => {
  await open(page, base('specifications', 'SpecificationSkillEmbedFullscreen'));
  await expect(page.getByTestId('specification-draft-notice')).toContainText('Draft — not saved yet');
  await expect(page.getByTestId('specification-save-to-project')).toHaveCount(0);
  const doc = page.getByTestId('specification-fullscreen');
  await expect(doc).toContainText('A member can add an item that every other member sees.');
  await expect(doc).toContainText('Add an item');
  await testInfo.attach('spec-skill-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: direct surface=gui.web assertions=contracts.guided.assumptions-explicit,contracts.guided.linked-split
test('guided specification fullscreen shows its role, open assumptions, design decisions and linked Specifications', async ({ page }, testInfo) => {
  for (const width of [1000, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, `${base('specifications', 'SpecificationSkillEmbedFullscreen')}&variant=guided`);
    const doc = page.getByTestId('specification-fullscreen');
    await expect(doc.getByTestId('spec-role')).toHaveText('Product Specification');
    await expect(doc.getByTestId('spec-assumptions')).toContainText('Open assumptions');
    await expect(doc.getByTestId('spec-assumption')).toHaveCount(2);
    await expect(doc.getByTestId('spec-assumption').first()).toContainText('Pickup only, no delivery');
    await expect(doc.getByTestId('spec-design-decisions')).toContainText('One-page order form');
    const link = doc.getByTestId('spec-related-item');
    await expect(link).toContainText('Online sourdough ordering - technical');
    await expect(link).toContainText('Technical Specification');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await doc.getByTestId('spec-assumptions').scrollIntoViewIfNeeded();
    await testInfo.attach(`spec-guided-fullscreen-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  }
});

// contract-test: supporting surface=gui.web assertions=checks.project.encrypted-embed,contracts.ui.human-readable-default
test('check skill preview shows a never-run draft Check without a run button', async ({ page }, testInfo) => {
  await open(page, base('checks', 'CheckSkillEmbedPreview'));
  const card = page.getByTestId('check-preview');
  await expect(card).toContainText('Shared list items sync between members');
  await expect(card.getByTestId('check-preview-status')).toContainText('Never run');
  await expect(card.getByTestId('check-preview-run')).toHaveCount(0);
  await testInfo.attach('check-skill-preview', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=checks.project.encrypted-embed,contracts.ui.human-readable-default
test('check skill fullscreen lists the sources and offers no run action', async ({ page }, testInfo) => {
  await open(page, base('checks', 'CheckSkillEmbedFullscreen'));
  const body = page.getByTestId('check-fullscreen-body');
  await expect(body).toContainText('Two members see the same list');
  await expect(body).toContainText('Owner confirms the invite flow');
  await expect(page.getByTestId('check-run')).toHaveCount(0);
  await testInfo.attach('check-skill-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen,contracts.ui.human-readable-default
test('plan create preview shows a draft Plan with its title', async ({ page }, testInfo) => {
  await open(page, base('plans', 'PlanCreateEmbedPreview'));
  const card = page.getByTestId('plan-embed-preview');
  await expect(card.getByTestId('plan-embed-title')).toContainText('Launch the household shopping app');
  await expect(card).toHaveAttribute('data-approval-state', 'draft');
  await testInfo.attach('plan-create-preview', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen,contracts.ui.human-readable-default
test('plan create fullscreen shows the draft Plan goal', async ({ page }, testInfo) => {
  await open(page, base('plans', 'PlanCreateEmbedFullscreen'));
  await expect(page.getByTestId('plan-fullscreen-title')).toContainText('Launch the household shopping app');
  await expect(page.getByTestId('plan-embed-fullscreen')).toContainText('Households can create, share and tick off');
  await testInfo.attach('plan-create-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
});
