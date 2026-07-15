/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflow template sharing browser contract.
 * It uses an opaque mock projection and a fragment key to exercise local
 * decryption and import while proving a client mock cannot fabricate binding success.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { webcrypto } = require('node:crypto');

const crypto = webcrypto as Crypto;

function encodeBase64Url(value: Uint8Array): string {
	return Buffer.from(value).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function checksum(value: string): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
	return `sha256:${encodeBase64Url(new Uint8Array(digest))}`;
}

async function encryptedProjection(payload: Record<string, unknown>, key: Uint8Array): Promise<string> {
	const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt']);
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, new TextEncoder().encode(JSON.stringify(payload)));
	const combined = new Uint8Array(iv.length + encrypted.byteLength);
	combined.set(iv);
	combined.set(new Uint8Array(encrypted), iv.length);
	return encodeBase64Url(combined);
}

test('imports a locally decrypted template and completes bindings before enable', async ({ page }: { page: any }) => {
	const templateId = 'template-e2e';
	const key = crypto.getRandomValues(new Uint8Array(32));
	const payload = {
		template_version: 1,
		title: 'Morning weather',
		description: 'Send my own weather reminder.',
		trigger_template: { id: 'trigger', type: 'schedule_trigger', config: { schedule: { type: 'daily', time: '08:00' } } },
		node_templates: [
			{ id: 'weather', type: 'app_skill_action', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', days: 1 } } },
			{ id: 'notify', type: 'send_notification', config: { title: 'Weather', body: 'Check the forecast.' } },
		],
		edge_templates: [{ from: 'trigger', to: 'weather' }, { from: 'weather', to: 'notify' }],
		variables_schema: {},
		required_capabilities: ['weather', 'weather.forecast'],
		binding_requirements: [
			{ type: 'schedule', node_id: 'trigger' },
			{ type: 'app_skill', node_id: 'weather', app_id: 'weather', skill_id: 'forecast' },
			{ type: 'notification_preferences', node_id: 'notify' },
		],
	};
	const ciphertext = await encryptedProjection(payload, key);
	const requests: string[] = [];

	await page.route(`**/v1/workflows/template-projections/${templateId}`, async (route: any) => {
		await route.fulfill({ json: { template_id: templateId, ciphertext, ciphertext_checksum: await checksum(ciphertext), projection_schema_version: 1 } });
	});
	await page.route('**/v1/workflows/template-import', async (route: any) => {
		requests.push('import');
		await route.fulfill({ json: { workflow: { id: 'imported-workflow', title: payload.title, status: 'disabled', enabled: false, current_version_id: 'v1', version: 1, graph: {}, binding_requirements: payload.binding_requirements } } });
	});
	await page.route('**/v1/workflows/imported-workflow/binding-requirements/complete', async (route: any) => {
		requests.push('binding');
		await route.fulfill({ status: 409, json: { detail: { code: 'UNRESOLVED_WORKFLOW_BINDING', reason: 'APP_SKILL_UNAVAILABLE' } } });
	});
	await page.route('**/v1/workflows/imported-workflow/enable', async (route: any) => {
		requests.push('enable');
		await route.fulfill({ json: { workflow: { id: 'imported-workflow', title: payload.title, status: 'active', enabled: true, current_version_id: 'v1', version: 1, graph: {} } } });
	});

	await page.goto(`/share/workflow-template/${templateId}#key=${encodeBase64Url(key)}`);
	await expect(page.getByTestId('workflow-template-preview')).toBeVisible();
	await expect(page.getByTestId('workflow-template-title')).toHaveText(payload.title);
	await page.getByTestId('workflow-template-import').click();
	await expect(page.getByTestId('workflow-template-bindings')).toBeVisible();
	await expect(page.getByTestId('workflow-template-binding-requirement')).toHaveCount(3);
	await expect(page.getByTestId('workflow-template-enable')).toBeDisabled();
	await page.getByTestId('workflow-template-complete-binding').first().click();
	await expect(page.getByTestId('workflow-template-enable')).toBeDisabled();
	await expect.poll(() => requests).toEqual(['import', 'binding']);
});
