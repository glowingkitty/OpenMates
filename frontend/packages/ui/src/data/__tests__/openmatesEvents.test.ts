// frontend/packages/ui/src/data/__tests__/openmatesEvents.test.ts
//
// Guards the generated public OpenMates event bundle consumed by the chat
// sidebar, event SEO pages, sitemap, and hash-based event embed deep links.
// The source of truth is shared/events/openmates_events.yml; this test checks
// the generated runtime shape rather than duplicating the YAML parser.

import { describe, expect, it } from 'vitest';
import { getAllOpenMatesEvents, getOpenMatesEventBySlug } from '../openmatesEvents';

describe('OPENMATES_EVENTS generated bundle', () => {
	// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity
	it('contains the published launch event set with served static images', () => {
		const events = getAllOpenMatesEvents();

		expect(events).toHaveLength(7);
		for (const event of events) {
			expect(event.id).toBe(event.slug);
			expect(event.embed_id).toBe(event.slug);
			expect(event.provider).toBe('luma');
			expect(event.url).toMatch(/^https:\/\/luma\.com\//);
			expect(event.image_url).toBe(`/event-assets/openmates/${event.slug}.jpg`);
			expect(new Date(event.date_end).getTime()).toBeGreaterThan(new Date(event.date_start).getTime());
			expect(event.summary.length).toBeGreaterThan(24);
		}
	});

	// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity
	it('resolves each event by slug and embed id', () => {
		for (const event of getAllOpenMatesEvents()) {
			expect(getOpenMatesEventBySlug(event.slug)).toBe(event);
			expect(getOpenMatesEventBySlug(event.embed_id)).toBe(event);
		}
	});
});
