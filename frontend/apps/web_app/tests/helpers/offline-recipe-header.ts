import type { Browser, BrowserContext } from '@playwright/test';
import { createIsolatedBrowserContext, declareTestState } from './chat-test-helpers';

const offlineRecipeState = declareTestState({
	auth: 'none',
	browserStorage: 'fresh',
	account: 'none',
	chat: 'none',
	notifications: 'none',
	securityReminders: 'none',
});

const unavailable = { blue: false, red: false, lexend: false, hasLexend: false };
const inertRoot = `<!doctype html><meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">`;

/** Inspect only self-contained styles, in a fresh context with no storage or provider access. */
export async function inspectOfflineRecipeHeader(browser: Browser, source: unknown) {
	if (typeof source !== 'string' || !source || source.length > 2_000_000) return unavailable;
	const context: BrowserContext = await createIsolatedBrowserContext(browser, offlineRecipeState, {
		javaScriptEnabled: false, offline: true, serviceWorkers: 'block',
	});
	try {
		await context.route('**/*', route => route.abort('blockedbyclient'));
		const page = await context.newPage();
		await page.setContent(inertRoot);
		return await page.evaluate(({ html, unavailable }) => {
			const recipe = new DOMParser().parseFromString(html, 'text/html');
			// Transfer only inert markup into the controlled document. Its CSP
			// also blocks URL-bearing CSS and other remaining resource loads.
			for (const node of recipe.querySelectorAll('script, iframe, frame, frameset, object, embed, base, meta, link, portal, fencedframe, template')) {
				node.remove();
			}
			const resourceAttributes = /^(?:src|srcset|srcdoc|href|xlink:href|action|formaction|ping|poster|background|data)$/i;
			for (const node of recipe.querySelectorAll('*')) {
				for (const attribute of [...node.attributes]) {
					if (/^on/i.test(attribute.name) || resourceAttributes.test(attribute.name)) {
						node.removeAttribute(attribute.name);
					}
				}
			}
			for (const [from, to] of [[recipe.documentElement, document.documentElement], [recipe.body, document.body]]) {
				for (const attribute of from.attributes) to.setAttribute(attribute.name, attribute.value);
			}
			document.head.append(...recipe.head.childNodes);
			document.body.replaceChildren(...recipe.body.childNodes);

			const headers = [...document.querySelectorAll<HTMLElement>('body header, body [role="banner"]')];
			const banners = headers.filter(header => header.getAttribute('role') === 'banner'
				|| !header.parentElement?.closest('article, aside, main, nav, section'));
			const candidates = banners.length ? banners : headers.length ? headers
				: [...document.querySelectorAll<HTMLElement>('body #header, body .header, body #app-header, body .app-header')];
			const visible = candidates.filter(header => header.checkVisibility({ opacityProperty: true, visibilityProperty: true }));
			// An ambiguous or hidden header can't certify the required style.
			const header = visible.length === 1 ? visible[0] : undefined;
			if (!header) return unavailable;
			const style = getComputedStyle(header);
			const fonts = style.fontFamily.split(',').map(font => font.trim().replace(/^["']|["']$/g, '').toLowerCase());
			return {
				blue: style.backgroundColor === 'rgb(0, 85, 255)',
				red: style.backgroundColor === 'rgb(208, 0, 0)',
				lexend: fonts[0] === 'lexend deca',
				hasLexend: fonts.includes('lexend deca'),
			};
		}, { html: source, unavailable });
	} finally {
		await context.close();
	}
}
