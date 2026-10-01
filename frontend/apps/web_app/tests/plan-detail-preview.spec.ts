import { expect, test } from './helpers/cookie-audit';
// contract-test-file: tooling

test('Plan detail preview renders its sanitized fixture and keeps edits local', async ({ page }) => {
  const planWrites: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/v1/user-plans')) {
      planWrites.push(request.url());
    }
  });

  await page.goto('/dev/preview/plans/PlanDetailPage?width=402', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('plan-detail-page')).toBeVisible();
  await expect(page.getByTestId('plan-assumption-summary')).toContainText('1');
  await expect(page.getByTestId('plan-criteria-summary')).toContainText('1');
  await expect(page.getByTestId('plan-assumption-item')).toHaveCount(1);

  await page.getByTestId('plan-assumption-input').fill('A second launch requirement is documented');
  await page.getByTestId('plan-assumption-add-button').click();
  await expect(page.getByTestId('plan-assumption-item')).toHaveCount(2);
  await expect(page.getByTestId('plan-assumption-summary')).toContainText('2');
  expect(planWrites).toEqual([]);
});
