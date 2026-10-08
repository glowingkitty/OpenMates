/* eslint-disable @typescript-eslint/no-require-imports -- Browser helpers expose CommonJS exports. */
/** Real encrypted workspace creation and list isolation across three contexts. */
export {};

import type { Page, Request, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type Resource = { id: string; name: string; context: string | null; version?: number };
type ContextResources = { project: Resource; workflow: Resource; task: Resource };

function isResponse(response: Response, method: string, path: string): boolean {
	return response.request().method() === method && new URL(response.url()).pathname === path;
}

function scopedUrl(apiUrl: string, path: string, teamId: string | null): string {
	const url = new URL(path, apiUrl);
	if (teamId) url.searchParams.set('team_id', teamId);
	return url.toString();
}

async function openContextPicker(page: Page): Promise<void> {
	if (!(await page.getByTestId('settings-menu').isVisible().catch(() => false))) {
		await page.getByTestId('profile-container').click();
	}
	await expect(page.getByTestId('team-context-dropdown')).toBeVisible({ timeout: 30000 });
	await page.getByTestId('team-context-dropdown').click();
}

async function switchContext(page: Page, teamId: string | null, name: string): Promise<void> {
	await openContextPicker(page);
	if (teamId && !(await page.getByTestId(`team-context-option-${teamId}`).isVisible().catch(() => false))) {
		await page.getByTestId('team-context-show-more').click();
	}
	const option = page.getByTestId(teamId ? `team-context-option-${teamId}` : 'team-context-personal');
	if ((await option.getAttribute('aria-checked')) !== 'true') await option.click();
	else await page.keyboard.press('Escape');
	await expect(page.getByTestId('team-context-dropdown')).toContainText(name, { timeout: 30000 });
	await page.getByTestId('icon-button-close').click();
	await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
}

async function createTeam(page: Page, name: string, onCreated: (id: string) => void): Promise<string> {
	const created = page.waitForResponse((response: Response) => isResponse(response, 'POST', '/v1/teams'));
	await page.getByTestId('team-create-open').click();
	await page.getByTestId('team-name-input').fill(name);
	await page.getByTestId('team-create-continue').click();
	await expect(page.getByTestId('team-avatar-preview')).toBeVisible({ timeout: 30000 });
	await page.getByTestId('team-create-submit').click();
	const response = await created;
	expect(response.ok(), await response.text()).toBe(true);
	const id = String((await response.json()).team?.team_id ?? '');
	expect(id).toBeTruthy();
	onCreated(id);
	await expect(page.getByTestId('teams-settings-detail')).toBeVisible({ timeout: 30000 });
	await page.getByTestId('banner-back-button').click();
	await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });
	return id;
}

async function createProject(page: Page, name: string, teamId: string | null, onCreated: (resource: Resource) => void): Promise<Resource> {
	await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
	const created = page.waitForResponse((response: Response) => isResponse(response, 'POST', '/v1/projects'));
	await page.getByTestId('project-input-textarea').fill(name);
	await page.getByTestId('project-input-submit').click();
	await expect(page.getByTestId('project-write-policy-dialog')).toBeVisible();
	await page.getByTestId('project-write-policy-apply-and-show').check();
	await page.getByTestId('project-write-policy-confirm').click();
	const response = await created;
	expect(response.ok(), await response.text()).toBe(true);
	const body = await response.json();
	const id = String(body.project?.project_id ?? '');
	expect(id).toBeTruthy();
	const resource = { id, name, context: teamId };
	onCreated(resource);
	expect(new URL(response.url()).searchParams.get('team_id')).toBe(teamId);
	await expect(page.getByTestId('workspace-detail-title')).toHaveText(name, { timeout: 30000 });
	return resource;
}

async function createWorkflow(page: Page, project: Resource, name: string, onCreated: (resource: Resource) => void): Promise<Resource> {
	await page.getByTestId('project-tab-folders').click();
	await page.getByTestId('project-folder-create-menu-button').click();
	await page.getByTestId('project-create-workflow').click();
	await expect(page.getByTestId('workflow-blank-creator')).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('workflow-project-target')).toContainText(project.name);
	await page.getByTestId('workflow-blank-title-input').fill(name);
	const created = page.waitForResponse((response: Response) => isResponse(response, 'POST', '/v1/workflows'));
	const linked = page.waitForResponse((response: Response) =>
		isResponse(response, 'POST', `/v1/projects/${project.id}/items`));
	await page.getByTestId('workflow-blank-create').click();
	const response = await created;
	expect(response.ok(), await response.text()).toBe(true);
	const id = String((await response.json()).workflow?.id ?? '');
	expect(id).toBeTruthy();
	const resource = { id, name, context: project.context };
	onCreated(resource);
	expect(response.request().postDataJSON().team_id ?? null).toBe(project.context);
	const linkedResponse = await linked;
	expect(linkedResponse.ok(), await linkedResponse.text()).toBe(true);
	expect(linkedResponse.request().postDataJSON().target_id).toBe(id);
	await expect(page.getByTestId('workspace-detail-title')).toHaveText(name, { timeout: 30000 });
	return resource;
}

async function createTask(page: Page, name: string, teamId: string | null, onCreated: (resource: Resource) => void): Promise<Resource> {
	await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
	const created = page.waitForResponse((response: Response) => isResponse(response, 'POST', '/v1/user-tasks'));
	await page.getByTestId('task-workspace-input').fill(name);
	await page.getByTestId('task-workspace-submit').click();
	const response = await created;
	expect(response.ok(), await response.text()).toBe(true);
	const body = await response.json();
	const id = String(body.task?.task_id ?? '');
	expect(id).toBeTruthy();
	const resource = { id, name, context: teamId, version: Number(body.task.version) };
	onCreated(resource);
	const payload = response.request().postDataJSON();
	expect(payload.team_id ?? null).toBe(teamId);
	expect(['user', 'unassigned']).toContain(payload.assignee_type);
	const card = page.locator(`[data-testid="task-card"][data-task-id="${id}"]`);
	await expect(card).toBeVisible({ timeout: 30000 });
	await expect(card).toContainText(name);
	return resource;
}

async function expectInventory(page: Page, apiUrl: string, context: string | null, all: ContextResources[]): Promise<void> {
	for (const [path, key, kind, idKey] of [
		['/v1/projects', 'projects', 'project', 'project_id'],
		['/v1/workflows', 'workflows', 'workflow', 'id'],
		['/v1/user-tasks', 'tasks', 'task', 'task_id']
	] as const) {
		const url = new URL(scopedUrl(apiUrl, path, context));
		if (kind === 'task') {
			url.searchParams.set('paginate', 'true');
			url.searchParams.set('limit', '500');
		}
		const response = await page.request.get(url.toString());
		expect(response.ok(), `${path} list returned ${response.status()}`).toBe(true);
		const ids = new Set(((await response.json())[key] as Array<Record<string, string>>).map((item) => item[idKey]));
		for (const resources of all) {
			const resource = resources[kind];
			expect(ids.has(resource.id), `${path} ${resource.id} in ${context ?? 'Personal'}`).toBe(resource.context === context);
		}
	}
}

async function expectVisibleResources(page: Page, active: ContextResources, all: ContextResources[]): Promise<void> {
	await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
	for (const resources of all) {
		await expect(page.getByTestId('project-landing-card').filter({ hasText: resources.project.name }))
			.toHaveCount(resources === active ? 1 : 0, { timeout: 30000 });
	}
	await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
	for (const resources of all) {
		await expect(page.getByTestId('workflow-landing-card').filter({ hasText: resources.workflow.name }))
			.toHaveCount(resources === active ? 1 : 0, { timeout: 30000 });
	}
	await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
	for (const resources of all) {
		await expect(page.locator(`[data-testid="task-card"][data-task-id="${resources.task.id}"]`))
			.toHaveCount(resources === active ? 1 : 0, { timeout: 30000 });
	}
}

test.describe('Teams resource context', () => {
	// contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
	test('creates and reloads Projects, Workflows and Tasks only in their active context', async ({ page }: { page: Page }) => {
		test.setTimeout(480000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams', 'platform:projects', 'platform:workflows', 'platform:tasks']);
		const suffix = `${Date.now()}-${test.info().workerIndex}`;
		const teams: Array<{ id: string; name: string }> = [];
		const resources: ContextResources[] = [];
		const createdResources: Array<{ path: string; resource: Resource }> = [];
		const listRequests: Array<{ path: string; teamId: string | null }> = [];
		page.on('request', (request: Request) => {
			if (request.method() !== 'GET') return;
			const url = new URL(request.url());
			if (['/v1/projects', '/v1/workflows', '/v1/user-tasks'].includes(url.pathname)) {
				listRequests.push({ path: url.pathname, teamId: url.searchParams.get('team_id') });
			}
		});
		const configuredApiUrl = process.env.PLAYWRIGHT_TEST_API_URL;
		const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
		const apiUrl = (configuredApiUrl || (base.hostname === 'localhost' ? 'http://localhost:8000' : `${base.protocol}//${base.hostname.replace(/^app\./, 'api.')}`)).replace(/\/$/, '');
		let flowError: unknown;
		const cleanupErrors: unknown[] = [];
		try {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);
			await dismissSecurityReminderIfPresent(page);
			await page.getByTestId('profile-container').click();
			await page.getByTestId('settings-teams-item').click();
			await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });
			for (const label of ['A', 'B']) {
				const name = `E2E resources Team ${label} ${suffix}`;
				await createTeam(page, name, (id) => teams.push({ id, name }));
			}
			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('icon-button-close').click();

			for (const context of [{ id: null, name: 'Personal' }, ...teams]) {
				await switchContext(page, context.id, context.name);
				const project = await createProject(page, `E2E ${context.name} Project ${suffix}`, context.id,
					(resource) => createdResources.push({ path: 'projects', resource }));
				const workflow = await createWorkflow(page, project, `E2E ${context.name} Workflow ${suffix}`,
					(resource) => createdResources.push({ path: 'workflows', resource }));
				const task = await createTask(page, `Create a new task for ${context.name} ${suffix}`, context.id,
					(resource) => createdResources.push({ path: 'user-tasks', resource }));
				resources.push({ project, workflow, task });
				await expectInventory(page, apiUrl, context.id, resources);
			}

			for (const context of [{ id: teams[0].id, name: teams[0].name }, { id: null, name: 'Personal' }, { id: teams[1].id, name: teams[1].name }]) {
				await switchContext(page, context.id, context.name);
				const active = resources.find((item) => item.project.context === context.id)!;
				await expectVisibleResources(page, active, resources);
				await expectInventory(page, apiUrl, context.id, resources);
				// A cold reload must restore the selected context before rebuilding each list.
				const requestStart = listRequests.length;
				await page.reload({ waitUntil: 'domcontentloaded' });
				await expectVisibleResources(page, active, resources);
				for (const path of ['/v1/projects', '/v1/workflows', '/v1/user-tasks']) {
					await expect.poll(() => listRequests.slice(requestStart).some((request) =>
						request.path === path && request.teamId === context.id), {
						message: `${path} was not loaded for ${context.name} after reload`, timeout: 10000
					}).toBe(true);
				}
			}

			for (const owned of resources) {
				const otherContext = owned.project.context === teams[0].id ? teams[1].id : teams[0].id;
				for (const [path, resource] of [
					['projects', owned.project], ['workflows', owned.workflow], ['user-tasks', owned.task]
				] as const) {
					const response = await page.request.get(scopedUrl(apiUrl, `/v1/${path}/${resource.id}`, otherContext));
					expect(response.status(), `${path} ${resource.id} leaked into ${otherContext}`).toBe(404);
				}
			}
		} catch (error) {
			flowError = error;
		} finally {
			for (const { path, resource } of [...createdResources].reverse()) {
				try {
					const url = new URL(scopedUrl(apiUrl, `/v1/${path}/${resource.id}`, resource.context));
					if (path === 'user-tasks') url.searchParams.set('version', String(resource.version));
					if (path === 'projects') url.searchParams.set('confirmation_project_id', resource.id);
					const response = await page.request.delete(url.toString());
					if (!response.ok()) cleanupErrors.push(new Error(`${path} ${resource.id}: ${response.status()} ${await response.text()}`));
				} catch (error) { cleanupErrors.push(error); }
			}
			for (const team of [...teams].reverse()) {
				try {
					const response = await page.request.delete(`${apiUrl}/v1/teams/${encodeURIComponent(team.id)}`);
					if (!response.ok()) cleanupErrors.push(new Error(`Team ${team.id}: ${response.status()} ${await response.text()}`));
				} catch (error) { cleanupErrors.push(error); }
			}
		}
		if (flowError || cleanupErrors.length) {
			const errors = [...(flowError ? [flowError] : []), ...cleanupErrors];
			throw new AggregateError(errors, `Resource context flow or cleanup failed: ${errors.map(String).join('; ')}`);
		}
	});
});
