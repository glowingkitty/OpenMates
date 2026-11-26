/** The runner owns the app origin for a locally built private benchmark. */
import type { BrowserContext, Route } from '@playwright/test';

const APP_ORIGIN = 'https://app.dev.openmates.org';
const API_ORIGIN = 'https://api.dev.openmates.org';
const PREVIEW_ORIGIN = 'http://127.0.0.1:5174';

export function privateWebRequest(url: string, method: string, preview: string) {
	if (preview !== PREVIEW_ORIGIN) throw new Error('Invalid private web preview origin');
	const request = new URL(url);
	if (request.origin === API_ORIGIN) return { kind: 'dev-api' } as const;
	if (request.origin !== APP_ORIGIN || !['GET', 'HEAD'].includes(method)) {
		return { kind: 'blocked' } as const;
	}
	// Assign pathname rather than resolving a URL reference, so a leading //
	// or escaped path cannot change the destination authority.
	const target = new URL(PREVIEW_ORIGIN);
	target.pathname = request.pathname;
	target.search = request.search;
	return { kind: 'preview', target } as const;
}

function replyHeaders(response: Response): Record<string, string> {
	const headers: Record<string, string> = {};
	// Node fetch decompresses the body. Let Playwright calculate its new size.
	for (const name of ['content-type', 'cache-control', 'etag', 'last-modified',
		'content-security-policy', 'cross-origin-embedder-policy', 'cross-origin-opener-policy',
		'cross-origin-resource-policy', 'referrer-policy', 'x-content-type-options']) {
		const value = response.headers.get(name);
		if (value !== null) headers[name] = value;
	}
	return headers;
}

async function routePrivateWebRequest(route: Route, preview: string): Promise<void> {
	const request = route.request();
	const directive = privateWebRequest(request.url(), request.method(), preview);
	if (directive.kind === 'blocked') {
		await route.abort('blockedbyclient');
		return;
	}
	if (directive.kind === 'dev-api') {
		await route.continue();
		return;
	}
	try {
		// The preview is a document/static asset source. Real API cookies,
		// authorization headers and form contents never go to loopback.
		const response = await fetch(directive.target, {
			method: request.method(),
			redirect: 'manual',
			signal: AbortSignal.timeout(10000),
			headers: { accept: request.headers().accept ?? '*/*' },
		});
		if (!response.ok) {
			await route.abort('failed');
			return;
		}
		await route.fulfill({
			status: response.status,
			headers: replyHeaders(response),
			body: Buffer.from(await response.arrayBuffer()),
		});
	} catch {
		// Missing or broken candidate assets must never come from deployed dev.
		await route.abort('failed');
	}
}

/** Install before navigating or authenticating. Service workers must be blocked
 * for the benchmark context so they cannot bypass the trusted network route. */
export async function preparePersonalDevtestWebOrigin(context: BrowserContext): Promise<void> {
	const preview = process.env.OPENMATES_PRIVATE_WEB_PREVIEW;
	if (!preview) return;
	if (preview !== PREVIEW_ORIGIN) throw new Error('Invalid private web preview origin');
	await context.route('**/*', route => routePrivateWebRequest(route, preview));
	await context.routeWebSocket(/^(?!wss:\/\/api\.dev\.openmates\.org\/v1\/ws(?:\?|$))/, async socket => {
		await socket.close({ code: 1008, reason: 'Private benchmark origin required' });
	});
}
