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
	it('contains the published event set with served static images', () => {
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
	it('publishes online events and the October community hour at Berlin winter time', () => {
		expect(getAllOpenMatesEvents().every((event) => event.event_type === 'ONLINE')).toBe(true);
		expect(getOpenMatesEventBySlug('openmates-berlin-meetup-2026-09-26')).toBeUndefined();
		expect(getOpenMatesEventBySlug('openmates-community-hour-2026-10-27')).toMatchObject({
			title: 'OpenMates Monthly Community Hour',
			date_start: '2026-10-27T19:00:00+01:00',
			date_end: '2026-10-27T20:00:00+01:00',
			timezone: 'Europe/Berlin',
			online_url: 'https://meet.openmates.org',
		});
	});

	// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity
	it('resolves each event by slug and embed id', () => {
		for (const event of getAllOpenMatesEvents()) {
			expect(getOpenMatesEventBySlug(event.slug)).toBe(event);
			expect(getOpenMatesEventBySlug(event.embed_id)).toBe(event);
		}
	});
});
