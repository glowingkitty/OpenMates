import { describe, expect, it } from 'vitest';
import { isOfficialOpenMatesPublicationHost } from './publicationHosting';

describe('official publication hosting', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	it('serves publications on OpenMates cloud and local development hosts', () => {
		expect(isOfficialOpenMatesPublicationHost('openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('app.openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('app.dev.openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('localhost')).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	it('keeps publications disabled on self-hosted domains', () => {
		expect(isOfficialOpenMatesPublicationHost('openmates.example')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('openmates-selfhost.vercel.app')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('localhost', 'self_hosted')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('openmates.org', 'self_hosted')).toBe(false);
	});
});
