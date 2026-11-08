/**
 * Saved-item reminder parity vectors: the real flag-off scheduleSavedEmbedReminders
 * (fetch stubbed, no reminder is created) records the plan, trigger instants and
 * every posted body; reminders_tests.rs replays them through the Rust op.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', async (importOriginal) => ({
	...(await importOriginal<typeof import('../../../config/api')>()),
	getApiUrl: () => 'https://api.test',
}));
vi.mock('../../../stores/userProfile', async () => {
	const { writable } = await import('svelte/store');
	return { userProfile: writable({ timezone: 'Europe/Berlin' }) };
});

import {
	buildSavedReminderPlan, getReminderTriggerDateTimes, savedReminderScheduleInput, scheduleSavedEmbedReminders,
	type SavedReminderKind,
} from '../../savedEmbedReminders';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/reminders_ts_vectors.json');
const NOW = Date.parse('2026-11-07T10:00:00Z');
type Json = Record<string, unknown>;
type Case = [string, string, SavedReminderKind | null, string, Json, string?, number?];

let requests: Array<{ url: string; init?: RequestInit }> = [];

const long = (char: string, count: number) => char.repeat(count);
const CASES: Case[] = [
	['event with venue object', 'ev-1', 'event', 'events', {
		title: 'Jazz night', date_start: '2026-12-01T20:00:00Z', date_end: '2026-12-01T23:00:00Z',
		venue: { name: 'Club', address: ' ', city: 'Berlin', country: 'DE' }, provider: 'Tickets', price: 25,
		image_url: 'https://example.org/a.jpg', chat_id: 'chat-from-content',
	}, 'chat-1'],
	['event with flat venue and markup', 'ev-2', 'event', 'events', {
		title: '<b>Talk</b> &amp;amp; Q&A', date_start: '2026-12-10', venue_name: 'Hall', venue_city: 'Paris',
		description: '<p>Intro</p><script type="x">alert(1)</script > after <STYLE>p{}</style>&nbsp;end &#39;q&#39; &quot;z&quot; &lt;tag&gt;',
		summary: 'a\u0000b\u0007c\u007fd\u0085e\tf', icon: 'music', category: 'events', timezone: 'Europe/Paris',
	}],
	['online event without venue', 'ev-3', 'event', 'events', { title: 'Webinar', date_start: '2026-11-20T09:00:00+01:00', event_type: 'ONLINE' }],
	['event venue array and unclosed script', 'ev-4', 'event', 'events', {
		title: 'Fair', date_start: '2026-12-02T10:00:00Z', venue: ['x'], location: 'ignored',
		description: 'before <script>never closed', summary: 'x <scripts>y</scripts> z <a href="x">link</a',
	}],
	['event local time and invalid zone', 'ev-5', 'event', 'events', { title: 'Local', date_start: '2026-12-03T18:30:00', timezone: 'Mars/Base' }],
	['event non-ISO date string', 'ev-6', 'event', 'events', { title: 'Loose', date_start: 'December 24, 2026 18:00' }],
	['event invalid date', 'ev-7', 'event', 'events', { title: 'x', date_start: 'garbage' }],
	['event without title', 'ev-8', 'event', 'events', { date_start: '2026-12-05T12:00:00Z', title: '' }],
	['event partly past triggers', 'ev-9', 'event', 'events', { title: 'Soon', date_start: '2026-11-07T12:00:00Z' }],
	['event fully past', 'ev-10', 'event', 'events', { title: 'Past', date_start: '2026-11-01T12:00:00Z' }],
	['event without embed id', '', 'event', 'events', { title: 'No id', date_start: '2026-12-05T12:00:00Z' }],
	['no kind', 'ev-11', null, 'events', { title: 'x', date_start: '2026-12-05T12:00:00Z' }],
	['unknown kind', 'ev-12', 'concert' as SavedReminderKind, 'events', { title: 'x', date_start: '2026-12-05T12:00:00Z' }],
	['event emoji title truncation', 'ev-13', 'event', 'events', { title: long('😀', 300), date_start: '2026-12-05T12:00:00Z', description: long('x', 3000) }],
	['event multibyte budget', 'ev-14', 'event', 'events', {
		title: long('旅', 200), date_start: '2026-12-05T12:00:00Z', description: long('描', 2000), summary: long('要', 500),
		location: long('所', 1000), provider: long('供', 512), origin: long('発', 512), destination: long('着', 512),
		transport_method: long('鉄', 512), price: long('金', 512), duration: long('時', 512), property_type: long('宿', 512),
		speciality: long('医', 512), venue_name: long('場', 900),
	}],
	['event budget chops description', 'ev-15', 'event', 'events', {
		title: long('旅', 200), date_start: '2026-12-05T12:00:00Z', description: long('😀', 2000), summary: long('要', 500),
	}],
	['home listing', 'home-1', 'home_listing', 'home', {
		title: 'Flat', available_from: '2026-12-15', price_label: 'EUR 900', property_type: 'Apartment', cover_url: '/img/flat.jpg',
	}],
	['home listing without date', 'home-2', 'home_listing', 'home', { title: 'Flat' }],
	['travel stay check_in_date', 'stay-1', 'travel_stay', 'travel', {
		name: 'Hotel', check_in_date: '2026-12-20', check_out_date: '2026-12-22', booking_provider: 'Booking', thumbnail_url: 'https://example.org/t.png',
	}],
	['travel stay check_in', 'stay-2', 'travel_stay', 'travel', { check_in: '2026-12-20T15:00:00Z', check_in_date: 'ignored' }],
	['travel connection legs', 'conn-1', 'travel_connection', 'travel', {
		route_display: 'Berlin → Paris', legs: [{ departure: '2027-01-10T08:00:00+01:00', arrival: 'x' }],
		arrival: '2027-01-10T16:00:00+01:00', origin: 'Berlin', destination: 'Paris', transport_method: 'train', duration: 480,
	}],
	['travel connection departure', 'conn-2', 'travel_connection', 'travel', {
		title: 'Flight', departure: '2027-01-12T06:00:00Z', legs: [{ departure: '2027-01-11T06:00:00Z' }], price: 1.5e21,
	}],
	['travel connection null leg', 'conn-3', 'travel_connection', 'travel', { legs: [null], title: 'x' }],
	['travel connection default title', 'conn-4', 'travel_connection', 'travel', { legs: [{ departure: '2027-02-01T10:00:00Z' }] }],
	['health appointment', 'health-1', 'health_appointment', 'health', {
		name: 'Dr X', speciality: 'Dentist', slot_datetime: '2026-12-01T09:30:00Z', address: 'Main St 1',
	}, 'chat-h'],
	['health appointment speciality title', 'health-2', 'health_appointment', 'health', { speciality: 'GP', slot_datetime: '2026-12-02T09:30:00Z' }],
	['health appointment invalid slot', 'health-3', 'health_appointment', 'health', { name: 'Dr Y', slot_datetime: 'soon' }],
	['health appointment long ISO-shaped slot', 'health-4', 'health_appointment', 'health', {
		name: 'Dr Z', slot_datetime: '2026-12-03T09:30:00.000Z', appointment_time: '2026-12-03T10:00:00Z',
	}],
	['event numeric fields and blank location', 'ev-17', 'event', 'events', {
		title: 42, date_start: '2026-12-07T12:00:00Z', location: '   ', address: 'Fallback 1', where: 'w', price: 0, duration: -3.25,
	}],
];

/**
 * Keeps the committed file small: a string ending in one code point repeated
 * 16+ times is stored as `{"$repeat": [char, count]}` or, after a short head,
 * `{"$repeat": [char, count, head]}` (reminders_tests.rs expands it).
 */
function compact(value: unknown): unknown {
	if (typeof value === 'string') {
		const chars = Array.from(value);
		const last = chars[chars.length - 1];
		let run = 0;
		while (run < chars.length && chars[chars.length - 1 - run] === last) run += 1;
		if (run < 16) return value;
		const head = chars.slice(0, chars.length - run).join('');
		return { $repeat: head ? [last, run, head] : [last, run] };
	}
	if (Array.isArray(value)) return value.map(compact);
	if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, compact(v)]));
	return value;
}

/** One case per line, so a CI log copy stays readable. */
function serialize(doc: { cases: unknown[] }): string {
	return `{"cases": [\n${doc.cases.map((item) => JSON.stringify(item)).join(',\n')}\n]}\n`;
}

async function buildVectors(): Promise<{ cases: Json[] }> {
	const cases: Json[] = [];
	for (const [name, embedId, kind, appId, content, chatId] of CASES) {
		const input = savedReminderScheduleInput(embedId, kind, appId, content, chatId, NOW);
		const plan = buildSavedReminderPlan(kind, appId, content, chatId);
		let expected: Json = { schedule: null };
		const triggers = plan && kind && embedId ? getReminderTriggerDateTimes(kind, plan.reminderDateTime, NOW) : [];
		if (plan && triggers.length) {
			requests = [];
			const now = vi.spyOn(Date, 'now').mockReturnValue(NOW);
			const count = await scheduleSavedEmbedReminders(embedId, kind, appId, content, chatId);
			now.mockRestore();
			expect(count).toBe(triggers.length);
			const context = JSON.parse(JSON.stringify(plan.notificationContext));
			// Every POST carries the plan's context; it is recorded once (`context`) and
			// each body keeps only its position (`$context`).
			const bodies = requests.map((request) => Object.entries(JSON.parse(String(request.init?.body)))
				.map(([key, value]) => {
					if (key !== 'notification_context') return [key, value];
					expect(value).toEqual(context);
					return [key, '$context'];
				}));
			expected = { schedule: {
				title: plan.title, promptTitle: plan.promptTitle, sourceChatId: plan.sourceChatId, thumbnailUrl: plan.thumbnailUrl,
				context: Object.entries(context), triggers,
				path: requests[0].url.replace('https://api.test', ''), method: requests[0].init?.method, bodies,
			} };
		}
		cases.push(compact({ name, input, expected }) as Json);
	}
	return { cases };
}

describe('saved-item reminder work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			return new Response(JSON.stringify({ data: { success: true } }), { status: 200 });
		});
	});

	// contract-test: supporting surface=gui.web assertions=notifications.reminder-email.durable-limited-context
	it('the flag-off reminder schedule reproduces every committed vector', async () => {
		const fresh = JSON.parse(JSON.stringify(await buildVectors()));
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, serialize(fresh));
		const committed = existsSync(VECTORS) ? JSON.parse(readFileSync(VECTORS, 'utf8')) : null;
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${serialize(fresh)}WORK_VECTORS_FRESH_END`);
		expect((fresh.cases as unknown[]).length).toBeGreaterThanOrEqual(25);
		expect(fresh).toEqual(committed);
	});
});
