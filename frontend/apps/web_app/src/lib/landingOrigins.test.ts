import { describe, expect, it } from 'vitest';
import { getLandingOrigins } from './landingOrigins';

describe('landing destinations', () => {
	// contract-test: supporting surface=gui.web assertions=marketing-landing.destinations
	it('keeps the temporary landing page connected to its own app deployment', () => {
		for (const origin of ['https://openmates.org', 'https://app.dev.openmates.org', 'http://localhost:5173']) {
			expect(getLandingOrigins(new URL(`${origin}/landing`))).toEqual({
				appBaseUrl: origin, websiteBaseUrl: origin
			});
		}
	});
	// contract-test: supporting surface=gui.web assertions=marketing-landing.destinations
	it('connects the future dev landing host to the dev app', () => {
		expect(getLandingOrigins(new URL('https://landing.dev.openmates.org/landing'))).toEqual({
			appBaseUrl: 'https://app.dev.openmates.org',
			websiteBaseUrl: 'https://landing.dev.openmates.org'
		});
	});
	// contract-test: supporting surface=gui.web assertions=marketing-landing.destinations
	it('supports independently deployed app and website origins', () => {
		expect(getLandingOrigins(new URL('https://openmates.org/landing'), {
			webapp: 'https://app.openmates.org/', website: 'https://openmates.org/'
		})).toEqual({appBaseUrl: 'https://app.openmates.org', websiteBaseUrl: 'https://openmates.org'});
	});
	// contract-test: supporting surface=gui.web assertions=marketing-landing.destinations
	it('rejects a non-web configured destination', () => {
		expect(() => getLandingOrigins(new URL('https://openmates.org/landing'), {webapp: 'javascript:alert(1)'})).toThrow();
	});
});
