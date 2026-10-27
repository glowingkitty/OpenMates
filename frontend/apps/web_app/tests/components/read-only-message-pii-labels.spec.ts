// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant: string) =>
  `/dev/preview/ReadOnlyMessage?theme=light&background=%23dbeafe&width=520&chrome=0&variant=${variant}`;
const firstToken = '[ADDRESS_1_0000000000000001]';
const secondToken = '[ADDRESS_1_0000000000000002]';

// contract-test: supporting surface=gui.web assertions=pii.message.owner-local-reveal,pii.surface.semantic-parity
test('shows readable labels while keeping canonical copy text and distinct address ownership', async ({ page }) => {
  await page.goto(preview('compactPIIHidden'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  const labels = message.getByTestId('pii-placeholder-label');
  await expect(labels).toHaveCount(3);
  for (const [index, alias] of ['[ADDRESS_2]', '[ADDRESS_3]', '[ADDRESS_2]'].entries()) {
    const label = labels.nth(index);
    await expect(label).toBeVisible();
    await expect(label).toHaveAttribute('data-pii-display-label', alias);
    await expect(label).toHaveAccessibleName(new RegExp(alias.replaceAll('[', '\\[').replaceAll(']', '\\]')));
    await expect(label).toHaveCSS('font-size', '0px');
    const rendered = await label.evaluate(element => ({
      content: getComputedStyle(element, '::after').content,
      fontSize: getComputedStyle(element, '::after').fontSize,
      width: element.getBoundingClientRect().width,
    }));
    expect(rendered.content).toBe(JSON.stringify(alias));
    expect(parseFloat(rendered.fontSize)).toBeGreaterThan(0);
    expect(rendered.width).toBeGreaterThan(0);
  }
  await expect(message).toContainText('Literal [ADDRESS_1]');
  await expect(message).toContainText('Custom [MY_HOME]');
  await expect(message).toContainText('Legacy [EMAIL_1_test]');
  await expect(message).not.toContainText('Maple Avenue');
  await expect(message).not.toContainText('Birch Lane');
  await expect(message).toContainText(firstToken);
  await expect(message).toContainText(secondToken);
  await labels.first().hover();
  await labels.first().focus();
  await expect(labels.first()).toBeFocused();
  const selected = await labels.first().evaluate(element => {
    const selection = window.getSelection()!;
    const range = document.createRange();
    range.selectNodeContents(element);
    selection.removeAllRanges();
    selection.addRange(range);
    const text = selection.toString();
    selection.removeAllRanges();
    return text;
  });
  expect(selected, 'Selection copy retains the original unique token').toBe(firstToken);
  const bounds = await message.evaluate(element => {
    const box = element.getBoundingClientRect();
    return { width: box.width, scrollWidth: element.scrollWidth };
  });
  expect(bounds.scrollWidth).toBeLessThanOrEqual(Math.ceil(bounds.width) + 1);
});

// contract-test: supporting surface=gui.web assertions=pii.message.owner-local-reveal
test('reveals the correct originals and restores compact hidden labels after reload', async ({ page }) => {
  await page.goto(preview('compactPIIRevealed'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message).toContainText('Home Maple Avenue, work Birch Lane, home again Maple Avenue');
  await expect(message).toContainText('Custom Private Cottage');
  await expect(message).toContainText('Legacy owner@example.test');
  await expect(message).toContainText('Literal [ADDRESS_1]');
  await expect(message).not.toContainText(firstToken);
  await expect(message).not.toContainText(secondToken);
  await expect(message.getByTestId('pii-placeholder-label')).toHaveCount(0);
  await page.goto(preview('compactPIIHidden'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pii-placeholder-label')).toHaveCount(3);
  await page.reload();
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pii-placeholder-label').first())
    .toHaveAttribute('data-pii-display-label', '[ADDRESS_2]');
  await expect(page.getByTestId('message-content')).not.toContainText('Maple Avenue');
});

// contract-test: supporting surface=gui.web assertions=pii.message.owner-local-reveal
test('keeps compact labels readable in heading, body, bold and inline code text', async ({ page }) => {
  const props = {
    role: 'assistant',
    content: `# Heading ${firstToken}\n\nBody ${secondToken} and **bold ${firstToken}** with \`inline ${secondToken}\`.`,
  };
  await page.goto(`${preview('compactPIIHidden')}&props=${encodeURIComponent(JSON.stringify(props))}`);
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  const labels = message.getByTestId('pii-placeholder-label');
  await expect(labels).toHaveCount(4);
  for (const label of await labels.all()) {
    await expect(label).toBeVisible();
    const typography = await label.evaluate(element => ({
      parentSize: getComputedStyle(element.parentElement!).fontSize,
      labelSize: getComputedStyle(element, '::after').fontSize,
      parentSpacing: getComputedStyle(element.parentElement!).letterSpacing,
      labelSpacing: getComputedStyle(element, '::after').letterSpacing,
      width: element.getBoundingClientRect().width,
    }));
    expect(typography.labelSize).toBe(typography.parentSize);
    expect(typography.labelSpacing).toBe(typography.parentSpacing);
    expect(typography.width).toBeGreaterThan(0);
  }
  await expect(message.locator('h1').getByTestId('pii-placeholder-label')).toHaveCount(1);
  await expect(message.locator('strong').getByTestId('pii-placeholder-label')).toHaveCount(1);
  await expect(message.locator('code').getByTestId('pii-placeholder-label')).toHaveCount(1);
});
