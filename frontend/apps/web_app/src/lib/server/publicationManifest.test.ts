import { describe, expect, it } from 'vitest';
import rawManifest from '../publications/publicationManifest.v1.json';
import { parsePublicPublicationManifest } from './publicationManifest';

describe('public publication manifest', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.authoring.public-boundary,public-publications.social.official-backfill,public-publications.media.read-only-delivery
	it('accepts the allowlisted publication backfill', () => {
		const manifest = parsePublicPublicationManifest(rawManifest);
		const social = manifest.publications.filter((entry) => entry.kind === 'social');
		expect(manifest.schemaVersion).toBe(1);
		expect(manifest.publications.some((entry) => entry.kind === 'blog')).toBe(false);
		expect(social).toHaveLength(4);
		expect(social.every((entry) => entry.media?.url.startsWith('https://openmates-buffer-media.nbg1.your-objectstorage.com/publications/social/'))).toBe(true);
		expect(social.every((entry) => entry.media?.posterUrl?.startsWith('/publications/social/'))).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.authoring.public-boundary
	it('rejects private or operational fields instead of passing them through', () => {
		const candidate = structuredClone(rawManifest) as Record<string, unknown>;
		(candidate.publications as Array<Record<string, unknown>>)[0].internal_notes = 'private';
		expect(() => parsePublicPublicationManifest(candidate)).toThrow(/non-public field: internal_notes/);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.social.official-backfill,public-publications.media.read-only-delivery
	it('rejects unapproved media and social hosts', () => {
		const mediaCandidate = structuredClone(rawManifest) as Record<string, unknown>;
		const social = (mediaCandidate.publications as Array<Record<string, unknown>>)[1];
		(social.media as Record<string, unknown>).url = 'https://cdn.instagram.com/private-video.mp4';
		expect(() => parsePublicPublicationManifest(mediaCandidate)).toThrow(/approved HTTPS host/);

		const linkCandidate = structuredClone(rawManifest) as Record<string, unknown>;
		const links = ((linkCandidate.publications as Array<Record<string, unknown>>)[1].socialLinks as Array<Record<string, unknown>>);
		links[0].href = 'https://example.com/fabricated-post';
		expect(() => parsePublicPublicationManifest(linkCandidate)).toThrow(/approved HTTPS host/);
	});
});
