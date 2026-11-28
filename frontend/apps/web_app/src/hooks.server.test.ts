import { describe, expect, it } from 'vitest';
import { handle } from './hooks.server';

describe('microphone permission for voice calls', () => {
	// contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
	it.each([
		['/', '(self)'],
		['/share/chat/example', '()'],
		['/example', '()'],
	])('limits microphone access on %s', async (path, microphone) => {
		const url = new URL(path, 'https://app.example');
		const response = await handle({
			event: { request: new Request(url), url } as Parameters<typeof handle>[0]['event'],
			resolve: async () => new Response(''),
		});
		expect(response.headers.get('Permissions-Policy')).toBe(
			`geolocation=(), microphone=${microphone}, camera=(), interest-cohort=()`
		);
		expect(response.headers.get('X-Frame-Options')).toBe('DENY');
	});
});
