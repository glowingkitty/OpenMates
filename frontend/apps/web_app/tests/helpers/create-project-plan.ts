import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Shared E2E helper exports CommonJS.
const { getE2EDebugUrl } = require('../signup-flow-helpers');

/** Create a Plan through its required Project context and open the stable detail URL. */
export async function createProjectPlanForTest(page: Page, projectName: string): Promise<{ projectId: string; planId: string }> {
  await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
  const projectCreated = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok());
  await page.getByTestId('project-input-textarea').fill(projectName);
  await page.getByTestId('project-input-submit').click();
  await page.getByTestId('project-write-policy-apply-and-show').check();
  await page.getByTestId('project-write-policy-confirm').click();
  const projectId = (await (await projectCreated).json()).project.project_id as string;

  const planCreated = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-plans') && response.ok());
  await page.getByTestId('project-readme-create').click();
  await expect(page.getByTestId('project-create-menu')).toBeVisible();
  await page.getByTestId('project-create-plan').click();
  const planId = (await (await planCreated).json()).plan.plan_id as string;
  await expect(page).toHaveURL(new RegExp(`/#plan-id=${planId}(?:&|$)`));
  await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
  return { projectId, planId };
}
