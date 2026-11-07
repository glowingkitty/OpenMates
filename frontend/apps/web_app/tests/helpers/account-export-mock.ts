import type { Page, Route } from '@playwright/test';

/**
 * Route mock of the Account Export V1 job API (`/v1/account-exports`) shared by the
 * account export specs: fixed manifest and one ready chunk per selected domain.
 */
export {};

export type AccountExportMockConfig = {
	exportId: string;
	selectedDomains: string[];
	completeStatus?: string;
	failures?: Array<Record<string, unknown>>;
};

export type AccountExportMockCall = {
	method: string;
	path: string;
	body: Record<string, unknown> | null;
};

async function installAccountExportMock(page: Page, config: AccountExportMockConfig): Promise<AccountExportMockCall[]> {
	const calls: AccountExportMockCall[] = [];
	const chunks = config.selectedDomains.map((domain: string, index: number) => ({
		chunk_id: `${domain}-chunk-1`,
		domain,
		sequence: index + 1,
		status: 'ready',
		payload: buildMockDomainPayload(domain),
	}));
	const domains = Object.fromEntries(chunks.map((chunk: Record<string, unknown>) => [chunk.domain, {
		status: 'ready',
		count: payloadCount(chunk.payload as Record<string, unknown>),
		source: mockDomainSource(String(chunk.domain)),
	}]));
	const manifest = {
		schema_version: 'account-export-v1',
		selected_domains: config.selectedDomains,
		filters: {},
		domains,
		report: {
			status: config.completeStatus === 'partial' ? 'partial' : 'complete',
			failures: config.failures ?? [],
			partial_requires_acceptance: config.completeStatus === 'partial',
			redactions: ['api_credentials'],
		},
	};

	await page.route('**/v1/account-exports**', async (route: Route) => {
		const request = route.request();
		const url = new URL(request.url());
		let body: Record<string, unknown> | null = null;
		try {
			body = request.postData() ? JSON.parse(request.postData() || '{}') : null;
		} catch {
			body = null;
		}
		calls.push({ method: request.method(), path: url.pathname, body });

		if (request.method() === 'POST' && url.pathname === '/v1/account-exports') {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'queued', selected_domains: body?.domains ?? config.selectedDomains } }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'ready', selected_domains: config.selectedDomains, progress: { total_parts: chunks.length } } }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}/manifest`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ manifest }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}/chunks`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ chunks: chunks.map(({ chunk_id, domain, sequence, status }: Record<string, unknown>) => ({ chunk_id, domain, sequence, status })) }) });
			return;
		}
		const chunk = chunks.find((candidate: Record<string, unknown>) => url.pathname === `/v1/account-exports/${config.exportId}/chunks/${candidate.chunk_id}`);
		if (request.method() === 'GET' && chunk) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ chunk }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/complete`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: config.completeStatus ?? 'complete' } }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/accept-partial`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'partial_accepted' } }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/cancel`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'cancelled' } }) });
			return;
		}
		await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: `Unhandled mock route ${request.method()} ${url.pathname}` }) });
	});
	return calls;
}

function buildMockDomainPayload(domain: string): Record<string, unknown> {
	if (domain === 'usage') {
		return { source: 'usage+usage_archives', items: [{ id: 'usage-row-1', usage_type: 'chat', credits_charged: 1 }], archives: [] };
	}
	if (domain === 'chats') {
		return { source: 'chats+messages+embeds', items: [{ id: 'chat-row-1', title: 'Mock chat', messages: [{ role: 'user', content: 'Hello export' }], embeds: [] }] };
	}
	return { source: mockDomainSource(domain), items: [{ id: `${domain}-row-1` }] };
}

function mockDomainSource(domain: string): string {
	return ({ usage: 'usage+usage_archives', chats: 'chats+messages+embeds' } as Record<string, string>)[domain] ?? domain;
}

function payloadCount(payload: Record<string, unknown>): number {
	const items = Array.isArray(payload.items) ? payload.items.length : 0;
	const runs = Array.isArray(payload.runs) ? payload.runs.length : 0;
	return items + runs;
}

module.exports = { installAccountExportMock };
